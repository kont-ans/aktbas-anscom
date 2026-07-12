import logging
import random
import warnings
import asyncio
warnings.filterwarnings("ignore", category=UserWarning)

from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.error import BadRequest, Forbidden, TelegramError
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

from . import config
from .config import (
    TOKEN, ADMIN_IDS, is_admin,
    POLL_INTERVAL_SEC, SESSION_DURATION_SEC, PAID_SESSION_DURATION_SEC,
    NUMBERS_PER_PAGE, COUNTRIES_PER_PAGE, USERS_PER_PAGE,
    PAID_NUMBER_PRICE, PAID_SERVICES,
    MIN_WITHDRAWAL, WITHDRAW_METHODS, DEPOSIT_METHODS, DEPOSIT_ADDRESSES, DEPOSIT_NETWORKS,
    REFERRALS_PER_CARD, WHEEL_PRIZES,
    FORCE_SUB_CHANNEL, FORCE_SUB_CHANNEL_URL,
    SUPPORT_USERNAME, SUPPORT_URL,
)
from . import database as db
from .database import (
    add_force_channel, remove_force_channel, list_force_channels, get_force_channel,
    add_broadcast_admin, remove_broadcast_admin, is_broadcast_admin, list_broadcast_admins,
    get_setting, set_setting,
)
from .scraper import (
    get_countries,
    get_numbers_by_country,
    get_messages_by_number,
)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)


# ── v3: مساعدات إعدادات البوت ────────────────────────────────────────

def _bot_enabled() -> bool:
    """هل البوت في وضع التشغيل (ليس الصيانة)؟"""
    return get_setting("bot_enabled", "1") == "1"

def _deposit_enabled() -> bool:
    """هل نظام الإيداع مفعّل؟"""
    return get_setting("deposit_enabled", "1") == "1"

def _paid_numbers_enabled() -> bool:
    """هل نظام الأرقام المدفوعة مفعّل؟"""
    return get_setting("paid_numbers_enabled", "1") == "1"


# ── Caches ───────────────────────────────────────────────────────────
_COUNTRIES_CACHE: list[dict] = []
_COUNTRIES_CACHE_AT: float = 0.0
_COUNTRIES_TTL = 600

_NUMBERS_CACHE: dict[str, tuple[float, list[dict]]] = {}
_NUMBERS_TTL = 60

_SUB_CACHE: dict[int, tuple[float, bool]] = {}
_SUB_TTL = 60


def _get_countries_cached() -> list[dict]:
    import time
    global _COUNTRIES_CACHE, _COUNTRIES_CACHE_AT
    if time.time() - _COUNTRIES_CACHE_AT < _COUNTRIES_TTL and _COUNTRIES_CACHE:
        return _COUNTRIES_CACHE
    fresh = get_countries()
    if fresh:
        _COUNTRIES_CACHE = fresh
        _COUNTRIES_CACHE_AT = time.time()
    return _COUNTRIES_CACHE or fresh


def _get_numbers_cached(slug: str) -> list[dict]:
    import time
    cached = _NUMBERS_CACHE.get(slug)
    if cached and time.time() - cached[0] < _NUMBERS_TTL:
        return cached[1]
    fresh = get_numbers_by_country(slug)
    if fresh:
        _NUMBERS_CACHE[slug] = (time.time(), fresh)
    return fresh


# ╔══════════════════════════════════════════════════════════════════╗
# ║                      FORCE SUBSCRIPTION                         ║
# ╚══════════════════════════════════════════════════════════════════╝

def _all_force_channels() -> list[dict]:
    """
    Returns the combined list of force-sub channels:
    DB channels + the static fallback from config (if not already in DB).
    """
    db_channels = list_force_channels()
    ids_in_db = {c["channel_id"] for c in db_channels}
    result = list(db_channels)
    # Always include the static channel from config as fallback
    if FORCE_SUB_CHANNEL and FORCE_SUB_CHANNEL not in ids_in_db:
        result.insert(0, {
            "id": 0,
            "channel_id": FORCE_SUB_CHANNEL,
            "channel_url": FORCE_SUB_CHANNEL_URL,
            "channel_name": "القناة الرئيسية",
        })
    return result


async def check_subscription(bot, user_id: int) -> bool:
    """Check if user is subscribed to ALL force-sub channels (cached 60s)."""
    import time
    cached = _SUB_CACHE.get(user_id)
    if cached and time.time() - cached[0] < _SUB_TTL:
        return cached[1]

    channels = _all_force_channels()
    if not channels:
        _SUB_CACHE[user_id] = (time.time(), True)
        return True

    all_ok = True
    for ch in channels:
        try:
            member = await bot.get_chat_member(ch["channel_id"], user_id)
            ok = member.status in ("member", "administrator", "creator")
        except Exception as e:
            logger.warning("Sub check failed for %s in %s: %s", user_id, ch["channel_id"], e)
            ok = False
        if not ok:
            all_ok = False
            break

    _SUB_CACHE[user_id] = (time.time(), all_ok)
    if all_ok:
        db.set_joined_channel(user_id, True)
    return all_ok


def force_sub_keyboard(verify_target: str = "verify_sub") -> InlineKeyboardMarkup:
    channels = _all_force_channels()
    rows = []
    for i, ch in enumerate(channels):
        label = ch.get("channel_name") or f"قناة {i+1}"
        rows.append([InlineKeyboardButton(f"📢 {label}", url=ch["channel_url"])])
    rows.append([InlineKeyboardButton("✅ تحققت من الاشتراك", callback_data=verify_target)])
    return InlineKeyboardMarkup(rows)


def force_sub_text() -> str:
    channels = _all_force_channels()
    ch_lines = ""
    for i, ch in enumerate(channels, 1):
        name = ch.get("channel_name") or f"قناة {i}"
        ch_lines += f"  {i}. [{name}]({ch['channel_url']})\n"
    return (
        "🔒 *الاشتراك في القنوات إجباري*\n\n"
        f"للاستفادة من البوت، يجب الاشتراك في القنوات التالية:\n\n"
        f"{ch_lines}\n"
        "اضغط على اسم كل قناة للاشتراك، ثم اضغط *تحققت من الاشتراك*."
    )


async def gate_or_proceed(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Returns True if user passed the gate (subscribed), else shows gate UI."""
    user = update.effective_user
    if not user:
        return False
    # Admin bypass — الأدمن يتجاوز جميع القيود
    if is_admin(user.id):
        return True

    # v3: فحص وضع الصيانة
    if not _bot_enabled():
        maintenance_text = (
            "🔧 *البوت تحت الصيانة*\n\n"
            "نعتذر منك، البوت يخضع حالياً لأعمال الصيانة والتطوير.\n"
            "سيعود للعمل قريباً إن شاء الله. 🙏\n\n"
            f"للاستفسار: {SUPPORT_USERNAME}"
        )
        if update.callback_query:
            try:
                await update.callback_query.answer("🔧 البوت تحت الصيانة", show_alert=True)
                await update.callback_query.edit_message_text(
                    maintenance_text, parse_mode=ParseMode.MARKDOWN
                )
            except BadRequest:
                await context.bot.send_message(
                    user.id, maintenance_text, parse_mode=ParseMode.MARKDOWN
                )
        elif update.message:
            await update.message.reply_text(maintenance_text, parse_mode=ParseMode.MARKDOWN)
        return False

    if await check_subscription(context.bot, user.id):
        return True
    # Show gate
    text = force_sub_text()
    kb = force_sub_keyboard()
    if update.callback_query:
        try:
            await update.callback_query.edit_message_text(text, reply_markup=kb,
                                                          parse_mode=ParseMode.MARKDOWN)
        except BadRequest:
            await context.bot.send_message(user.id, text, reply_markup=kb,
                                           parse_mode=ParseMode.MARKDOWN)
    elif update.message:
        await update.message.reply_text(text, reply_markup=kb, parse_mode=ParseMode.MARKDOWN)
    return False


# ╔══════════════════════════════════════════════════════════════════╗
# ║                          UI HELPERS                             ║
# ╚══════════════════════════════════════════════════════════════════╝

def main_menu_keyboard(user_id: int) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton("📲 رقم مجاني", callback_data="countries:0"),
         InlineKeyboardButton("💎 رقم مدفوع", callback_data="paid:menu")],
        [InlineKeyboardButton("💰 محفظتي", callback_data="wallet:home"),
         InlineKeyboardButton("🎁 الإحالات", callback_data="ref:home")],
        [InlineKeyboardButton("🎰 عجلة الحظ", callback_data="wheel:home")],
        [InlineKeyboardButton("📥 صندوق الوارد", callback_data="inbox"),
         InlineKeyboardButton("⏹️ إيقاف الجلسة", callback_data="stop")],
        [InlineKeyboardButton("🆘 الدعم", url=SUPPORT_URL),
         InlineKeyboardButton("ℹ️ مساعدة", callback_data="help")],
    ]
    if is_admin(user_id):
        rows.append([InlineKeyboardButton("👑 لوحة الأدمن", callback_data="admin:home")])
    return InlineKeyboardMarkup(rows)


def main_menu_text(user: dict) -> str:
    bal = float(user.get("balance") or 0)
    return (
        "👋 *أهلاً بك في بوت الأرقام المؤقتة*\n\n"
        f"💰 رصيدك: *{bal:.2f}$*\n"
        f"🎁 إحالاتك: *{int(user.get('referrals_count') or 0)}*\n"
        f"🎫 بطاقات العجلة: *{int(user.get('wheel_cards') or 0)}*\n\n"
        "اختر من القائمة:"
    )


def fmt_money(x) -> str:
    return f"{float(x):.2f}$"


def format_message_card(msg: dict, idx: int = 0) -> str:
    sender = msg.get("sender") or "غير معروف"
    time_str = msg.get("time") or ""
    body = msg.get("body") or ""
    if len(body) > 600:
        body = body[:600] + "..."
    prefix = f"*رسالة {idx}*\n" if idx else ""
    return (
        f"{prefix}"
        f"📨 *من:* `{sender}`\n"
        f"🕐 {time_str}\n"
        f"💬 {body}"
    )


def msg_signature(msg: dict) -> str:
    s = (msg.get("sender", "") + "|" + (msg.get("body", "") or "")[:80])
    return str(abs(hash(s)))


def snapshot_seen(messages: list[dict]) -> str:
    return ",".join(msg_signature(m) for m in messages[:60])


async def safe_edit(query_or_msg, text, reply_markup=None,
                    parse_mode=ParseMode.MARKDOWN, disable_web_preview=True):
    try:
        if hasattr(query_or_msg, "edit_message_text"):
            await query_or_msg.edit_message_text(
                text, reply_markup=reply_markup, parse_mode=parse_mode,
                disable_web_page_preview=disable_web_preview,
            )
        else:
            await query_or_msg.edit_text(
                text, reply_markup=reply_markup, parse_mode=parse_mode,
                disable_web_page_preview=disable_web_preview,
            )
    except BadRequest as e:
        if "not modified" not in str(e).lower():
            logger.warning("Edit failed: %s", e)


async def _ensure_user(update: Update) -> bool:
    """Save/update user. Returns False if banned."""
    u = update.effective_user
    if not u:
        return False
    db.upsert_user(u.id, u.username, u.first_name, u.last_name, u.language_code)
    if db.is_banned(u.id):
        target = update.effective_message
        if target:
            await target.reply_text("🚫 لقد تم حظرك من استخدام هذا البوت.")
        return False
    return True


async def show_main_menu(update_or_query, context, user_id: int):
    user = db.get_user(user_id) or {}
    text = main_menu_text(user)
    kb = main_menu_keyboard(user_id)
    if hasattr(update_or_query, "edit_message_text"):
        await safe_edit(update_or_query, text, kb)
    else:
        await update_or_query.message.reply_text(text, reply_markup=kb,
                                                 parse_mode=ParseMode.MARKDOWN)


# ╔══════════════════════════════════════════════════════════════════╗
# ║                          /start                                 ║
# ╚══════════════════════════════════════════════════════════════════╝

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _ensure_user(update):
        return

    user = update.effective_user
    args = context.args or []

    # Referral link: /start ref_<id>
    if args:
        arg = args[0]
        if arg.startswith("ref_") or arg.startswith("ref"):
            try:
                ref_id = int(arg.replace("ref_", "").replace("ref", ""))
                if ref_id and ref_id != user.id:
                    db.set_referrer(user.id, ref_id)
            except ValueError:
                pass

    # Force subscription gate
    if not await gate_or_proceed(update, context):
        return

    # Credit referral if any (now that they're subscribed)
    result = db.credit_referral(user.id)
    if result:
        try:
            ref_id = result["referrer_id"]
            if result.get("awarded_card"):
                await context.bot.send_message(
                    ref_id,
                    f"🎉 *تهانينا!* أكملت {REFERRALS_PER_CARD} إحالات ناجحة.\n"
                    f"حصلت على *🎫 بطاقة عجلة الحظ* جديدة!\n\n"
                    f"اضغط /start ثم *عجلة الحظ* لتدوير العجلة.",
                    parse_mode=ParseMode.MARKDOWN,
                )
            else:
                await context.bot.send_message(
                    ref_id,
                    f"✨ مستخدم جديد انضم بإحالتك! المجموع: *{result['total']}*",
                    parse_mode=ParseMode.MARKDOWN,
                )
        except (Forbidden, BadRequest):
            pass

    await show_main_menu(update, context, user.id)


async def cmd_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if db.get_user_pending(user_id):
        db.clear_user_pending(user_id)
        await update.message.reply_text("✅ تم إلغاء العملية.")
    else:
        await update.message.reply_text("لا توجد عملية للإلغاء.")


# ── Verify subscription callback ────────────────────────────────────

async def cb_verify_sub(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    user_id = q.from_user.id
    _SUB_CACHE.pop(user_id, None)  # invalidate cache
    if await check_subscription(context.bot, user_id):
        await q.answer("✅ تم التحقق", show_alert=False)
        # Credit referral if any
        result = db.credit_referral(user_id)
        if result:
            try:
                ref_id = result["referrer_id"]
                if result.get("awarded_card"):
                    await context.bot.send_message(
                        ref_id,
                        f"🎉 *تهانينا!* أكملت {REFERRALS_PER_CARD} إحالات ناجحة.\n"
                        f"حصلت على *🎫 بطاقة عجلة الحظ* جديدة!",
                        parse_mode=ParseMode.MARKDOWN,
                    )
            except Exception:
                pass
        await show_main_menu(q, context, user_id)
    else:
        await q.answer("❌ لم يتم العثور على اشتراكك. تأكد من الانضمام للقناة.",
                       show_alert=True)


async def cb_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if not await gate_or_proceed(update, context):
        return
    await show_main_menu(q, context, q.from_user.id)


async def cb_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    text = (
        "ℹ️ *كيفية الاستخدام*\n\n"
        "*📲 رقم مجاني:* اختر دولة → اختر رقم → استلم الرسائل تلقائياً (10 دقائق)\n\n"
        "*💎 رقم مدفوع:* تيليجرام / واتساب فقط — السعر *0.50$*. "
        "يقوم الأدمن بتفعيله خلال دقائق وستحصل على رقم خاص (30 دقيقة).\n\n"
        "*💰 المحفظة:* اشحن رصيدك واسحب أرباحك. الحد الأدنى للسحب: *6$*.\n\n"
        f"*🎁 الإحالات:* لكل {REFERRALS_PER_CARD} إحالات ناجحة تحصل على بطاقة عجلة حظ.\n\n"
        "*🎰 العجلة:* جوائز من 0.01$ حتى 2$ تُضاف لرصيدك مباشرة.\n\n"
        "*الأوامر:*\n"
        "/start — القائمة الرئيسية\n"
        "/inbox — الرسائل الجديدة\n"
        "/stop — إيقاف الجلسة\n"
        "/cancel — إلغاء عملية\n\n"
        f"🆘 الدعم: {SUPPORT_USERNAME}"
    )
    await safe_edit(q, text, InlineKeyboardMarkup([
        [InlineKeyboardButton("🆘 الدعم", url=SUPPORT_URL)],
        [InlineKeyboardButton("🏠 الرئيسية", callback_data="main_menu")],
    ]))


# ╔══════════════════════════════════════════════════════════════════╗
# ║                  FREE NUMBER FLOW                                ║
# ╚══════════════════════════════════════════════════════════════════╝

async def cb_countries(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if not await gate_or_proceed(update, context): return
    page = int(q.data.split(":")[1])

    await safe_edit(q, "⏳ جاري جلب قائمة الدول...")
    countries = _get_countries_cached()
    if not countries:
        await safe_edit(q, "❌ تعذّر جلب قائمة الدول.", InlineKeyboardMarkup([
            [InlineKeyboardButton("🔄 إعادة المحاولة", callback_data="countries:0")],
            [InlineKeyboardButton("🏠 الرئيسية", callback_data="main_menu")],
        ]))
        return

    start = page * COUNTRIES_PER_PAGE
    end = start + COUNTRIES_PER_PAGE
    page_items = countries[start:end]

    buttons, row = [], []
    for c in page_items:
        label = c["name"] + (f" ({c['count']})" if c.get("count") else "")
        row.append(InlineKeyboardButton(label, callback_data=f"country:{c['slug']}:0"))
        if len(row) == 2:
            buttons.append(row); row = []
    if row: buttons.append(row)

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("⬅️ السابق", callback_data=f"countries:{page-1}"))
    if end < len(countries):
        nav.append(InlineKeyboardButton("التالي ➡️", callback_data=f"countries:{page+1}"))
    if nav: buttons.append(nav)
    buttons.append([InlineKeyboardButton("🏠 الرئيسية", callback_data="main_menu")])

    total_pages = (len(countries) + COUNTRIES_PER_PAGE - 1) // COUNTRIES_PER_PAGE
    await safe_edit(q,
        f"🌍 *اختر الدولة* (صفحة {page+1}/{total_pages})\n"
        f"إجمالي: {len(countries)} دولة",
        InlineKeyboardMarkup(buttons))


async def cb_country(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if not await gate_or_proceed(update, context): return
    parts = q.data.split(":")
    slug, page = parts[1], int(parts[2])

    countries = _get_countries_cached()
    country_name = next((c["name"] for c in countries if c["slug"] == slug), slug)
    await safe_edit(q, f"⏳ جاري جلب أرقام {country_name}...")

    numbers = _get_numbers_cached(slug)
    if not numbers:
        await safe_edit(q, f"❌ لا توجد أرقام متاحة حالياً في {country_name}.",
            InlineKeyboardMarkup([
                [InlineKeyboardButton("🔄 إعادة المحاولة", callback_data=f"country:{slug}:0")],
                [InlineKeyboardButton("🌍 دولة أخرى", callback_data="countries:0")],
                [InlineKeyboardButton("🏠 الرئيسية", callback_data="main_menu")],
            ]))
        return

    start = page * NUMBERS_PER_PAGE
    end = start + NUMBERS_PER_PAGE
    page_items = numbers[start:end]
    buttons = [[InlineKeyboardButton(f"📱 {n['phone']}",
                callback_data=f"pick:{slug}:{n['phone_digits']}")]
               for n in page_items]

    nav = []
    if page > 0: nav.append(InlineKeyboardButton("⬅️", callback_data=f"country:{slug}:{page-1}"))
    if end < len(numbers): nav.append(InlineKeyboardButton("➡️", callback_data=f"country:{slug}:{page+1}"))
    if nav: buttons.append(nav)
    buttons.append([
        InlineKeyboardButton("🌍 دولة أخرى", callback_data="countries:0"),
        InlineKeyboardButton("🏠 الرئيسية", callback_data="main_menu"),
    ])

    total_pages = (len(numbers) + NUMBERS_PER_PAGE - 1) // NUMBERS_PER_PAGE
    await safe_edit(q,
        f"🇺🇳 *{country_name}*\n"
        f"📱 اختر رقماً (صفحة {page+1}/{total_pages}, إجمالي: {len(numbers)}):",
        InlineKeyboardMarkup(buttons))


async def cb_pick(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if not await gate_or_proceed(update, context): return
    parts = q.data.split(":")
    slug, digits = parts[1], parts[2]
    user_id = q.from_user.id

    countries = _get_countries_cached()
    country_name = next((c["name"] for c in countries if c["slug"] == slug), slug)
    phone_display = f"+{digits}"

    await safe_edit(q, f"⏳ جاري تفعيل الرقم {phone_display}...")
    try:
        existing = get_messages_by_number(slug, digits, limit=20)
    except Exception:
        existing = []
    seen_csv = snapshot_seen(existing)

    expires_at = (datetime.now() + timedelta(seconds=SESSION_DURATION_SEC)).isoformat()
    db.set_active_number(user_id, phone_display, slug, country_name,
                         expires_at, seen_csv=seen_csv, kind="free")

    await safe_edit(q,
        f"✅ *تم تفعيل الرقم المجاني*\n\n"
        f"🇺🇳 الدولة: {country_name}\n"
        f"📱 الرقم: `{phone_display}`\n"
        f"⏱️ نشط لمدة: 10 دقائق\n"
        f"🔄 فحص الرسائل تلقائياً كل {POLL_INTERVAL_SEC} ثانية\n\n"
        f"📌 *سيتم عرض الرسائل الجديدة فقط* بعد هذه اللحظة.",
        InlineKeyboardMarkup([
            [InlineKeyboardButton("📥 فحص الرسائل", callback_data="inbox")],
            [InlineKeyboardButton("⏹️ إيقاف", callback_data="stop"),
             InlineKeyboardButton("🏠 الرئيسية", callback_data="main_menu")],
        ]))


async def check_active_session(bot, session: dict) -> None:
    """
    Checks one active session (a row dict from db.list_active_numbers() /
    db.get_active_number()) and delivers any new messages to the user.

    Keys expected in session:
        id, user_id, phone, country_slug, country_name, kind,
        started_at, expires_at, seen_messages, is_active
    """
    record_id = session["id"]
    user_id = session["user_id"]
    chat_id = user_id  # private chats: chat_id == user_id
    phone_display = session["phone"]
    slug = session["country_slug"]
    digits = phone_display.lstrip("+")
    kind = session.get("kind", "free")

    duration = PAID_SESSION_DURATION_SEC if kind == "paid" else SESSION_DURATION_SEC

    # Parse started_at — may be a datetime object (Postgres) or ISO string
    started_at_raw = session["started_at"]
    if isinstance(started_at_raw, str):
        started_at = datetime.fromisoformat(started_at_raw)
    else:
        started_at = started_at_raw

    # Expiry check
    if datetime.now() - started_at >= timedelta(seconds=duration):
        db.stop_active_number(user_id)
        try:
            await bot.send_message(
                chat_id,
                f"⌛ *انتهت جلسة الرقم* `{phone_display}`\n\nاضغط /start للقائمة الرئيسية.",
                parse_mode=ParseMode.MARKDOWN,
            )
        except Exception:
            pass
        return

    # Confirm session is still the same record
    active = db.get_active_number(user_id)
    if not active or active["id"] != record_id:
        return

    try:
        messages = get_messages_by_number(slug, digits, limit=20)
    except Exception as e:
        logger.warning("check_active_session fetch failed: %s", e)
        return

    if not messages:
        return

    seen_csv = active.get("seen_messages") or ""
    seen_set = set(seen_csv.split(",")) if seen_csv else set()
    new_msgs, new_sigs = [], []
    for m in messages:
        sig = msg_signature(m)
        new_sigs.append(sig)
        if sig not in seen_set:
            new_msgs.append(m)

    if not new_msgs:
        return

    combined = list(dict.fromkeys(new_sigs + list(seen_set)))[:60]
    db.update_seen_messages(record_id, ",".join(combined))

    for m in reversed(new_msgs[:5]):
        try:
            await bot.send_message(
                chat_id,
                f"🔔 *رسالة جديدة على* `{phone_display}`\n\n" + format_message_card(m),
                parse_mode=ParseMode.MARKDOWN,
            )
        except Exception as e:
            logger.warning("check_active_session send failed: %s", e)


# ── Inbox & Stop ─────────────────────────────────────────────────────

async def cmd_inbox(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _ensure_user(update): return
    if not await gate_or_proceed(update, context): return
    await _show_inbox(update, context, update.effective_user.id, from_command=True)


async def cb_inbox(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if not await gate_or_proceed(update, context): return
    await _show_inbox(update, context, q.from_user.id, from_command=False)


async def _show_inbox(update, context, user_id: int, from_command: bool):
    active = db.get_active_number(user_id)
    if not active:
        text = "❌ لا يوجد رقم نشط حالياً.\n\nاضغط /start ثم اختر رقماً."
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("📲 رقم مجاني", callback_data="countries:0"),
             InlineKeyboardButton("💎 رقم مدفوع", callback_data="paid:menu")],
            [InlineKeyboardButton("🏠 الرئيسية", callback_data="main_menu")],
        ])
        if from_command:
            await update.message.reply_text(text, reply_markup=kb, parse_mode=ParseMode.MARKDOWN)
        else:
            await safe_edit(update.callback_query, text, kb)
        return

    if not from_command:
        await safe_edit(update.callback_query, "⏳ جاري جلب الرسائل...")

    messages = get_messages_by_number(active["country_slug"],
                                      active["phone"].lstrip("+"), limit=20)
    seen_set = set((active.get("seen_messages") or "").split(",")) if active.get("seen_messages") else set()
    new_msgs = [m for m in messages if msg_signature(m) not in seen_set]

    kind = "💎 مدفوع" if active.get("kind") == "paid" else "📲 مجاني"
    header = (
        f"📥 *صندوق الوارد* — {kind}\n"
        f"📱 الرقم: `{active['phone']}`\n"
        f"🇺🇳 الدولة: {active['country_name']}\n\n"
    )
    if not new_msgs:
        text = header + "_لا توجد رسائل جديدة بعد. سيتم إخطارك عند وصول رسالة._"
    else:
        parts = [header]
        for i, m in enumerate(new_msgs[:5], 1):
            parts.append(format_message_card(m, idx=i))
            parts.append("─" * 20)
        text = "\n".join(parts)

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 تحديث", callback_data="inbox")],
        [InlineKeyboardButton("⏹️ إيقاف", callback_data="stop"),
         InlineKeyboardButton("🏠 الرئيسية", callback_data="main_menu")],
    ])
    if from_command:
        await update.message.reply_text(text, reply_markup=kb, parse_mode=ParseMode.MARKDOWN)
    else:
        await safe_edit(update.callback_query, text, kb)


async def cmd_stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _ensure_user(update): return
    user_id = update.effective_user.id
    _stop_user_session(user_id)
    await update.message.reply_text("⏹️ تم إيقاف الجلسة.",
        reply_markup=main_menu_keyboard(user_id))


async def cb_stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    _stop_user_session(q.from_user.id)
    await show_main_menu(q, context, q.from_user.id)


def _stop_user_session(user_id: int):
    db.stop_active_number(user_id)


# ╔══════════════════════════════════════════════════════════════════╗
# ║                  PAID NUMBER FLOW                                ║
# ╚══════════════════════════════════════════════════════════════════╝

async def cb_paid_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if not await gate_or_proceed(update, context): return
    parts = q.data.split(":")
    action = parts[1]
    user_id = q.from_user.id

    if action == "menu":
        # v3: فحص إذا كانت الأرقام المدفوعة معطلة
        if not _paid_numbers_enabled() and not is_admin(user_id):
            await safe_edit(q,
                "⏸️ *الأرقام المدفوعة متوقفة مؤقتاً*\n\n"
                "تم إيقاف خدمة الأرقام المدفوعة مؤقتاً من قبل الإدارة.\n"
                "سيتم تفعيلها قريباً.\n\n"
                f"للاستفسار: {SUPPORT_USERNAME}",
                InlineKeyboardMarkup([
                    [InlineKeyboardButton("🆘 الدعم", url=SUPPORT_URL)],
                    [InlineKeyboardButton("🏠 الرئيسية", callback_data="main_menu")],
                ]))
            return
        text = (
            "💎 *الأرقام المدفوعة*\n\n"
            f"السعر: *{fmt_money(PAID_NUMBER_PRICE)}* لكل رقم\n"
            "الفئات المتاحة:\n"
            "• 💬 تيليجرام\n"
            "• 🟢 واتساب\n\n"
            "📌 يقوم الأدمن بتفعيل الرقم خلال دقائق."
        )
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("💬 تيليجرام", callback_data="paid:buy:telegram"),
             InlineKeyboardButton("🟢 واتساب", callback_data="paid:buy:whatsapp")],
            [InlineKeyboardButton("🏠 الرئيسية", callback_data="main_menu")],
        ])
        await safe_edit(q, text, kb)
        return

    if action == "buy":
        service = parts[2]
        if service not in PAID_SERVICES:
            await q.answer("خدمة غير صالحة", show_alert=True); return
        # v3: فحص إذا كانت الأرقام المدفوعة معطلة
        if not _paid_numbers_enabled() and not is_admin(user_id):
            await safe_edit(q,
                "⏸️ *الأرقام المدفوعة متوقفة مؤقتاً*\n\n"
                "تم إيقاف خدمة الأرقام المدفوعة مؤقتاً من قبل الإدارة.\n\n"
                f"للاستفسار: {SUPPORT_USERNAME}",
                InlineKeyboardMarkup([
                    [InlineKeyboardButton("🏠 الرئيسية", callback_data="main_menu")],
                ]))
            return
        bal = db.get_balance(user_id)
        if bal < PAID_NUMBER_PRICE:
            await safe_edit(q,
                f"❌ *رصيد غير كافٍ*\n\n"
                f"السعر: {fmt_money(PAID_NUMBER_PRICE)}\n"
                f"رصيدك: {fmt_money(bal)}\n\n"
                "اشحن محفظتك أولاً.",
                InlineKeyboardMarkup([
                    [InlineKeyboardButton("💰 شحن المحفظة", callback_data="wallet:deposit")],
                    [InlineKeyboardButton("🏠 الرئيسية", callback_data="main_menu")],
                ]))
            return
        # Go to country selection for paid
        await safe_edit(q,
            f"💎 *شراء رقم {PAID_SERVICES[service]}*\n\n"
            f"السعر: *{fmt_money(PAID_NUMBER_PRICE)}*\n"
            f"رصيدك: *{fmt_money(bal)}*\n\n"
            "اختر الدولة التي تريد رقماً منها:",
            InlineKeyboardMarkup([
                [InlineKeyboardButton("🌍 اختر الدولة", callback_data=f"ppick:{service}:0")],
                [InlineKeyboardButton("⬅️ رجوع", callback_data="paid:menu")],
            ]))
        return

    if action == "confirm":
        # Legacy — redirect to menu
        await safe_edit(q, "👇 اختر الخدمة:", InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅️ رجوع", callback_data="paid:menu")]
        ]))



# ╔══════════════════════════════════════════════════════════════════╗
# ║            PAID COUNTRY / NUMBER SELECTION                       ║
# ╚══════════════════════════════════════════════════════════════════╝

import secrets as _secrets
import string as _string

def _gen_purchase_code(service: str) -> str:
    chars = _string.ascii_uppercase + _string.digits
    rand = "".join(_secrets.choice(chars) for _ in range(8))
    prefix = "TG" if service == "telegram" else "WA"
    return f"{prefix}-{rand}"


async def cb_ppick_countries(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Paid: country selection."""
    q = update.callback_query
    await q.answer()
    if not await gate_or_proceed(update, context): return
    parts = q.data.split(":")
    service, page = parts[1], int(parts[2])

    await safe_edit(q, "⏳ جاري جلب الدول...")
    countries = _get_countries_cached()
    if not countries:
        await safe_edit(q, "❌ تعذّر جلب الدول.", InlineKeyboardMarkup([
            [InlineKeyboardButton("🔄 إعادة المحاولة", callback_data=f"ppick:{service}:0")],
            [InlineKeyboardButton("⬅️ رجوع", callback_data=f"paid:buy:{service}")],
        ]))
        return

    start = page * COUNTRIES_PER_PAGE
    end = start + COUNTRIES_PER_PAGE
    buttons, row = [], []
    for c in countries[start:end]:
        label = c["name"] + (f" ({c['count']})" if c.get("count") else "")
        row.append(InlineKeyboardButton(label, callback_data=f"ppcountry:{service}:{c['slug']}:0"))
        if len(row) == 2:
            buttons.append(row); row = []
    if row: buttons.append(row)
    nav = []
    if page > 0: nav.append(InlineKeyboardButton("⬅️", callback_data=f"ppick:{service}:{page-1}"))
    if end < len(countries): nav.append(InlineKeyboardButton("➡️", callback_data=f"ppick:{service}:{page+1}"))
    if nav: buttons.append(nav)
    buttons.append([InlineKeyboardButton("⬅️ رجوع", callback_data=f"paid:buy:{service}")])
    total_pages = (len(countries) + COUNTRIES_PER_PAGE - 1) // COUNTRIES_PER_PAGE
    await safe_edit(q,
        f"💎 *اختر الدولة* (صفحة {page+1}/{total_pages})\n"
        f"الخدمة: *{PAID_SERVICES[service]}*",
        InlineKeyboardMarkup(buttons))


async def cb_ppick_country(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Paid: number selection within a country."""
    q = update.callback_query
    await q.answer()
    if not await gate_or_proceed(update, context): return
    parts = q.data.split(":")
    service, slug, page = parts[1], parts[2], int(parts[3])

    countries = _get_countries_cached()
    country_name = next((c["name"] for c in countries if c["slug"] == slug), slug)
    await safe_edit(q, f"⏳ جاري جلب أرقام {country_name}...")

    numbers = _get_numbers_cached(slug)
    if not numbers:
        await safe_edit(q, f"❌ لا توجد أرقام متاحة في {country_name}.",
            InlineKeyboardMarkup([
                [InlineKeyboardButton("🔄 إعادة المحاولة", callback_data=f"ppcountry:{service}:{slug}:0")],
                [InlineKeyboardButton("⬅️ دولة أخرى", callback_data=f"ppick:{service}:0")],
            ]))
        return

    start = page * NUMBERS_PER_PAGE
    end = start + NUMBERS_PER_PAGE
    buttons = [[InlineKeyboardButton(f"📱 {n['phone']}",
                callback_data=f"ppconfirm:{service}:{slug}:{n['phone_digits']}")]
               for n in numbers[start:end]]
    nav = []
    if page > 0: nav.append(InlineKeyboardButton("⬅️", callback_data=f"ppcountry:{service}:{slug}:{page-1}"))
    if end < len(numbers): nav.append(InlineKeyboardButton("➡️", callback_data=f"ppcountry:{service}:{slug}:{page+1}"))
    if nav: buttons.append(nav)
    buttons.append([InlineKeyboardButton("⬅️ دولة أخرى", callback_data=f"ppick:{service}:0")])
    total_pages = (len(numbers) + NUMBERS_PER_PAGE - 1) // NUMBERS_PER_PAGE
    await safe_edit(q,
        f"💎 *{country_name}* — {PAID_SERVICES[service]}\n"
        f"📱 اختر الرقم (صفحة {page+1}/{total_pages})\n"
        f"السعر: *{fmt_money(PAID_NUMBER_PRICE)}*",
        InlineKeyboardMarkup(buttons))


async def cb_ppick_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Paid: confirmation screen after picking a number."""
    q = update.callback_query
    await q.answer()
    if not await gate_or_proceed(update, context): return
    parts = q.data.split(":")
    service, slug, digits = parts[1], parts[2], parts[3]
    user_id = q.from_user.id

    if service not in PAID_SERVICES:
        await q.answer("خدمة غير صالحة", show_alert=True); return

    countries = _get_countries_cached()
    country_name = next((c["name"] for c in countries if c["slug"] == slug), slug)
    phone_display = f"+{digits}"
    bal = db.get_balance(user_id)

    if bal < PAID_NUMBER_PRICE:
        await safe_edit(q,
            f"❌ *رصيد غير كافٍ*\n\nرصيدك: {fmt_money(bal)}\nالسعر: {fmt_money(PAID_NUMBER_PRICE)}",
            InlineKeyboardMarkup([
                [InlineKeyboardButton("💰 شحن المحفظة", callback_data="wallet:deposit")],
                [InlineKeyboardButton("⬅️ رجوع", callback_data=f"ppick:{service}:0")],
            ]))
        return

    await safe_edit(q,
        f"🧾 *تأكيد شراء الرقم*\n\n"
        f"الخدمة: *{PAID_SERVICES[service]}*\n"
        f"الرقم: `{phone_display}`\n"
        f"الدولة: {country_name}\n"
        f"السعر: *{fmt_money(PAID_NUMBER_PRICE)}*\n"
        f"رصيدك بعد الشراء: *{fmt_money(bal - PAID_NUMBER_PRICE)}*\n\n"
        "اضغط *تأكيد* للمتابعة:",
        InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ تأكيد الشراء",
                callback_data=f"ppdo:{service}:{slug}:{digits}")],
            [InlineKeyboardButton("❌ إلغاء", callback_data=f"ppcountry:{service}:{slug}:0")],
        ]))


async def cb_ppick_do(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Paid: execute purchase — deduct balance, generate code, show admin contact."""
    import random as _random
    q = update.callback_query
    await q.answer()
    if not await gate_or_proceed(update, context): return
    parts = q.data.split(":")
    service, slug, digits = parts[1], parts[2], parts[3]
    user_id = q.from_user.id

    if service not in PAID_SERVICES:
        await q.answer("خدمة غير صالحة", show_alert=True); return

    bal = db.get_balance(user_id)
    if bal < PAID_NUMBER_PRICE:
        await q.answer("❌ رصيد غير كافٍ", show_alert=True); return

    countries = _get_countries_cached()
    country_name = next((c["name"] for c in countries if c["slug"] == slug), slug)
    phone_display = f"+{digits}"

    # Deduct & create order with unique purchase code
    purchase_code = _gen_purchase_code(service)
    db.add_tx(user_id, -PAID_NUMBER_PRICE, "purchase_paid_number",
              note=f"شراء رقم {PAID_SERVICES[service]} — {phone_display}")
    order_id = db.create_paid_order(user_id, service, PAID_NUMBER_PRICE)
    db.update_paid_order(order_id, phone=phone_display, country_slug=slug,
                         country_name=country_name, purchase_code=purchase_code, status="paid")

    await safe_edit(q,
        f"✅ *تم الشراء بنجاح!*\n\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🔖 *كود الشراء:* `{purchase_code}`\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📱 الرقم المختار: `{phone_display}`\n"
        f"🌍 الدولة: {country_name}\n"
        f"📲 الخدمة: *{PAID_SERVICES[service]}*\n"
        f"💰 المبلغ المدفوع: *{fmt_money(PAID_NUMBER_PRICE)}*\n\n"
        f"📌 *للحصول على الرقم المفعّل:*\n"
        f"1️⃣ تواصل مع فريق الدعم: {SUPPORT_USERNAME}\n"
        f"2️⃣ أرسل لهم كود الشراء: `{purchase_code}`\n"
        f"3️⃣ سيتم تفعيل الرقم فوراً.\n\n"
        f"📋 رقم الطلب: `#{order_id}`",
        InlineKeyboardMarkup([
            [InlineKeyboardButton("🆘 تواصل مع الدعم الآن", url=SUPPORT_URL)],
            [InlineKeyboardButton("🏠 الرئيسية", callback_data="main_menu")],
        ]))

    # Notify admins
    u = db.get_user(user_id) or {}
    uname = f"@{u['username']}" if u.get("username") else u.get("first_name") or "—"
    admin_text = (
        f"💰 *عملية شراء رقم مدفوع*\n\n"
        f"الطلب: `#{order_id}`\n"
        f"الكود: `{purchase_code}`\n"
        f"المستخدم: {uname} (`{user_id}`)\n"
        f"الخدمة: *{PAID_SERVICES[service]}*\n"
        f"الرقم: `{phone_display}`\n"
        f"الدولة: {country_name}\n"
        f"السعر: *{fmt_money(PAID_NUMBER_PRICE)}*"
    )
    for aid in ADMIN_IDS:
        try:
            await context.bot.send_message(aid, admin_text, parse_mode=ParseMode.MARKDOWN)
        except Exception:
            pass


# ╔══════════════════════════════════════════════════════════════════╗
# ║                       WALLET                                    ║
# ╚══════════════════════════════════════════════════════════════════╝

async def cb_wallet_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if not await gate_or_proceed(update, context): return
    parts = q.data.split(":")
    action = parts[1]
    user_id = q.from_user.id

    if action == "home":
        bal = db.get_balance(user_id)
        text = (
            "💰 *محفظتي*\n\n"
            f"الرصيد الحالي: *{fmt_money(bal)}*\n"
            f"الحد الأدنى للسحب: *{fmt_money(MIN_WITHDRAWAL)}*\n\n"
            "اختر العملية:"
        )
        await safe_edit(q, text, InlineKeyboardMarkup([
            [InlineKeyboardButton("⬇️ شحن المحفظة", callback_data="wallet:deposit")],
            [InlineKeyboardButton("⬆️ سحب الرصيد", callback_data="wallet:withdraw")],
            [InlineKeyboardButton("📜 السجل", callback_data="wallet:history")],
            [InlineKeyboardButton("🏠 الرئيسية", callback_data="main_menu")],
        ]))
        return

    if action == "history":
        txs = db.list_user_tx(user_id, limit=10)
        if not txs:
            text = "📜 *السجل*\n\nلا توجد عمليات بعد."
        else:
            lines = ["📜 *آخر 10 عمليات*\n"]
            for t in txs:
                amt = float(t["amount"])
                sign = "+" if amt >= 0 else ""
                kind_label = {
                    "deposit_approved":     "إيداع",
                    "withdraw_approved":    "سحب",
                    "purchase_paid_number": "شراء رقم",
                    "refund_paid_number":   "استرجاع رقم",
                    "spin_win":             "ربح عجلة",
                    "referral_bonus":       "مكافأة إحالة",
                    "admin_set":            "تعديل أدمن",
                    "admin_credit":         "إضافة أدمن",
                    "admin_debit":          "خصم أدمن",
                }.get(t["kind"], t["kind"])
                lines.append(f"• {kind_label}: *{sign}{amt:.2f}$*")
            text = "\n".join(lines)
        await safe_edit(q, text, InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅️ رجوع", callback_data="wallet:home")],
        ]))
        return

    if action == "deposit":
        # v3: فحص إذا كان الإيداع معطلاً
        if not _deposit_enabled() and not is_admin(user_id):
            await safe_edit(q,
                "⏸️ *الإيداع متوقف مؤقتاً*\n\n"
                "تم إيقاف خدمة الإيداع مؤقتاً من قبل الإدارة.\n"
                "سيتم تفعيلها قريباً.\n\n"
                f"للاستفسار: {SUPPORT_USERNAME}",
                InlineKeyboardMarkup([
                    [InlineKeyboardButton("🆘 الدعم", url=SUPPORT_URL)],
                    [InlineKeyboardButton("⬅️ رجوع", callback_data="wallet:home")],
                ]))
            return
        kb_rows = [[InlineKeyboardButton(f"💳 {label}", callback_data=f"wallet:dep_method:{key}")]
                   for key, label in DEPOSIT_METHODS.items()]
        kb_rows.append([InlineKeyboardButton("⬅️ رجوع", callback_data="wallet:home")])
        await safe_edit(q, "⬇️ *شحن المحفظة*\n\nاختر طريقة الشحن:", InlineKeyboardMarkup(kb_rows))
        return

    if action == "dep_method":
        method = parts[2]
        if method not in DEPOSIT_METHODS:
            await q.answer("طريقة غير صالحة", show_alert=True); return
        addr = DEPOSIT_ADDRESSES.get(method, "—")
        net  = DEPOSIT_NETWORKS.get(method, "")
        text = (
            f"⬇️ *الشحن عبر {DEPOSIT_METHODS[method]}*\n\n"
            f"🔗 الشبكة: *{net}*\n"
            f"📋 العنوان:\n`{addr}`\n\n"
            "─────────────────\n"
            "1️⃣ انسخ العنوان وأرسل المبلغ.\n"
            "2️⃣ اضغط *أرسلتُ المبلغ* لمتابعة الإيداع."
        )
        await safe_edit(q, text, InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ أرسلتُ المبلغ", callback_data=f"wallet:dep_start:{method}")],
            [InlineKeyboardButton("⬅️ رجوع", callback_data="wallet:deposit")],
        ]))
        return

    if action == "dep_start":
        method = parts[2]
        if method not in DEPOSIT_METHODS:
            await q.answer("طريقة غير صالحة", show_alert=True); return
        db.set_user_pending(user_id, "dep_amount", payload=method)
        await safe_edit(q,
            f"💬 *أرسل المبلغ الذي حوّلته بالدولار*\n\n"
            f"مثال: `5`  أو  `12.50`\n\n"
            "أرسل /cancel للإلغاء.",
            InlineKeyboardMarkup([[InlineKeyboardButton("❌ إلغاء", callback_data="wallet:home")]]))
        return

    if action == "withdraw":
        bal = db.get_balance(user_id)
        if bal < MIN_WITHDRAWAL:
            await safe_edit(q,
                f"❌ *لا يمكنك السحب الآن*\n\n"
                f"رصيدك: *{fmt_money(bal)}*\n"
                f"الحد الأدنى للسحب: *{fmt_money(MIN_WITHDRAWAL)}*",
                InlineKeyboardMarkup([
                    [InlineKeyboardButton("⬅️ رجوع", callback_data="wallet:home")],
                ]))
            return
        kb_rows = [[InlineKeyboardButton(label, callback_data=f"wallet:wd_method:{key}")]
                   for key, label in WITHDRAW_METHODS.items()]
        kb_rows.append([InlineKeyboardButton("⬅️ رجوع", callback_data="wallet:home")])
        await safe_edit(q,
            f"⬆️ *سحب الرصيد*\n\nرصيدك: *{fmt_money(bal)}*\n\nاختر طريقة السحب:",
            InlineKeyboardMarkup(kb_rows))
        return

    if action == "wd_method":
        method = parts[2]
        if method not in WITHDRAW_METHODS:
            await q.answer("طريقة غير صالحة", show_alert=True); return
        db.set_user_pending(user_id, "withdraw_submit", payload=method)
        await safe_edit(q,
            f"⬆️ *السحب عبر {WITHDRAW_METHODS[method]}*\n\n"
            f"أرسل في رسالة واحدة:\n"
            f"*المبلغ* ثم *العنوان/الحساب*.\n\n"
            f"_مثال:_ `7 - 0xABC...`\n\n"
            f"الحد الأدنى: *{fmt_money(MIN_WITHDRAWAL)}*\n"
            "أرسل /cancel للإلغاء.",
            InlineKeyboardMarkup([
                [InlineKeyboardButton("❌ إلغاء", callback_data="wallet:home")],
            ]))


# ╔══════════════════════════════════════════════════════════════════╗
# ║                       REFERRALS                                 ║
# ╚══════════════════════════════════════════════════════════════════╝

async def cb_ref_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if not await gate_or_proceed(update, context): return
    user_id = q.from_user.id
    user = db.get_user(user_id) or {}
    count = int(user.get("referrals_count") or 0)
    cards = int(user.get("wheel_cards") or 0)
    next_in = REFERRALS_PER_CARD - (count % REFERRALS_PER_CARD)
    bot_username = config.BOT_USERNAME or context.bot.username
    link = f"https://t.me/{bot_username}?start=ref_{user_id}"

    text = (
        "🎁 *نظام الإحالات*\n\n"
        f"إحالاتك الناجحة: *{count}*\n"
        f"بطاقات العجلة المتاحة: *{cards}*\n"
        f"باقي على البطاقة القادمة: *{next_in}* إحالة\n\n"
        f"📎 رابط الإحالة:\n`{link}`\n\n"
        f"💡 لكل *{REFERRALS_PER_CARD}* إحالات ناجحة → بطاقة عجلة حظ مجانية!"
    )
    await safe_edit(q, text, InlineKeyboardMarkup([
        [InlineKeyboardButton("🎰 عجلة الحظ", callback_data="wheel:home")],
        [InlineKeyboardButton("🏠 الرئيسية", callback_data="main_menu")],
    ]))


# ╔══════════════════════════════════════════════════════════════════╗
# ║                       WHEEL OF FORTUNE                          ║
# ╚══════════════════════════════════════════════════════════════════╝

def pick_prize() -> float:
    total_w = sum(p["weight"] for p in WHEEL_PRIZES)
    r = random.uniform(0, total_w)
    upto = 0
    for p in WHEEL_PRIZES:
        upto += p["weight"]
        if r <= upto:
            return p["amount"]
    return WHEEL_PRIZES[0]["amount"]


async def cb_wheel_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if not await gate_or_proceed(update, context): return
    parts = q.data.split(":")
    action = parts[1]
    user_id = q.from_user.id

    if action == "home":
        user = db.get_user(user_id) or {}
        cards = int(user.get("wheel_cards") or 0)
        prize_lines = "\n".join(
            f"  • {fmt_money(p['amount'])}" for p in WHEEL_PRIZES
        )
        text = (
            "🎰 *عجلة الحظ*\n\n"
            f"بطاقاتك: *{cards}*\n\n"
            f"🎁 *الجوائز:*\n{prize_lines}\n\n"
            f"💡 احصل على بطاقات إضافية بدعوة أصدقائك!\n"
            f"كل {REFERRALS_PER_CARD} إحالات = 🎫 بطاقة جديدة."
        )
        kb_rows = []
        if cards > 0:
            kb_rows.append([InlineKeyboardButton("🎰 تدوير العجلة", callback_data="wheel:spin")])
        else:
            kb_rows.append([InlineKeyboardButton("🎁 احصل على بطاقات (الإحالات)", callback_data="ref:home")])
        kb_rows.append([InlineKeyboardButton("🏠 الرئيسية", callback_data="main_menu")])
        await safe_edit(q, text, InlineKeyboardMarkup(kb_rows))
        return

    if action == "spin":
        if not db.use_wheel_card(user_id):
            await q.answer("❌ ليس لديك بطاقات", show_alert=True)
            return
        prize = pick_prize()

        # Spin animation
        frames = ["🎰 ⏳ ...", "🎰 🔄 يدور ...", "🎰 ✨ يدور ✨", "🎰 🎲 يدور 🎲"]
        for f in frames:
            try:
                await safe_edit(q, f)
                await asyncio.sleep(0.45)
            except Exception:
                break

        db.add_tx(user_id, prize, "spin_win", note="ربح عجلة الحظ")
        bal = db.get_balance(user_id)
        await safe_edit(q,
            f"🎉 *مبروك!*\n\n"
            f"ربحت: *{fmt_money(prize)}* 💰\n"
            f"رصيدك الجديد: *{fmt_money(bal)}*",
            InlineKeyboardMarkup([
                [InlineKeyboardButton("🎰 العجلة", callback_data="wheel:home"),
                 InlineKeyboardButton("💰 محفظتي", callback_data="wallet:home")],
                [InlineKeyboardButton("🏠 الرئيسية", callback_data="main_menu")],
            ]))


# ╔══════════════════════════════════════════════════════════════════╗
# ║                       ADMIN PANEL                               ║
# ╚══════════════════════════════════════════════════════════════════╝

def admin_home_keyboard() -> InlineKeyboardMarkup:
    p_paid = db.count_pending("paid_orders")
    p_dep  = db.count_pending("deposit_requests")
    p_wd   = db.count_pending("withdraw_requests")
    ch_count = len(list_force_channels())
    ba_count = len(list_broadcast_admins())
    # v3: قراءة حالة الأنظمة
    bot_on  = "✅" if _bot_enabled() else "🔴"
    dep_on  = "✅" if _deposit_enabled() else "🔴"
    paid_on = "✅" if _paid_numbers_enabled() else "🔴"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 إحصائيات", callback_data="admin:stats")],
        [InlineKeyboardButton(f"💎 طلبات الأرقام ({p_paid})",
            callback_data="admin:paid_list:0")],
        [InlineKeyboardButton(f"⬇️ طلبات الإيداع ({p_dep})",
            callback_data="admin:dep_list:0")],
        [InlineKeyboardButton(f"⬆️ طلبات السحب ({p_wd})",
            callback_data="admin:wd_list:0")],
        [InlineKeyboardButton("👥 المستخدمون", callback_data="admin:users:0:all")],
        [InlineKeyboardButton("💵 تعديل رصيد مستخدم", callback_data="admin:set_balance_prompt")],
        [InlineKeyboardButton("📢 رسالة جماعية", callback_data="admin:broadcast")],
        [InlineKeyboardButton("🚫 حظر / فك حظر", callback_data="admin:ban_prompt")],
        [InlineKeyboardButton(f"📡 قنوات الاشتراك ({ch_count})", callback_data="admin:channels")],
        [InlineKeyboardButton(f"👮 أدمن البث ({ba_count})", callback_data="admin:broadcast_admins")],
        # ── v3: أزرار التحكم ──────────────────────────────────────────
        [InlineKeyboardButton(f"{bot_on} البوت", callback_data="admin:toggle_bot"),
         InlineKeyboardButton(f"{dep_on} الإيداع", callback_data="admin:toggle_deposit"),
         InlineKeyboardButton(f"{paid_on} الأرقام المدفوعة", callback_data="admin:toggle_paid")],
        [InlineKeyboardButton("🏠 الرئيسية", callback_data="main_menu")],
    ])


def broadcast_admin_keyboard() -> InlineKeyboardMarkup:
    """Keyboard for broadcast-only admins (limited panel)."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📢 إرسال رسالة جماعية", callback_data="admin:broadcast")],
        [InlineKeyboardButton("🏠 الرئيسية", callback_data="main_menu")],
    ])


async def cmd_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _ensure_user(update): return
    uid = update.effective_user.id
    if is_admin(uid):
        await update.message.reply_text(
            "👑 *لوحة تحكم الأدمن*\n\nاختر الإجراء:",
            reply_markup=admin_home_keyboard(),
            parse_mode=ParseMode.MARKDOWN,
        )
    elif is_broadcast_admin(uid):
        await update.message.reply_text(
            "📢 *لوحة البث*\n\nيمكنك إرسال رسائل جماعية للمستخدمين.",
            reply_markup=broadcast_admin_keyboard(),
            parse_mode=ParseMode.MARKDOWN,
        )
    else:
        await update.message.reply_text("🚫 هذا الأمر للأدمن فقط.")


async def cb_admin_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    user_id = q.from_user.id
    _is_full_admin = is_admin(user_id)
    _is_bcast_admin = is_broadcast_admin(user_id)
    if not _is_full_admin and not _is_bcast_admin:
        await q.answer("🚫 للأدمن فقط", show_alert=True); return
    await q.answer()
    parts = q.data.split(":")
    action = parts[1]

    # Broadcast admins: only allow broadcast + cancel actions
    if _is_bcast_admin and not _is_full_admin:
        if action not in ("broadcast", "cancel"):
            await q.answer("🚫 ليس لديك صلاحية لهذا الإجراء", show_alert=True); return

    if action == "home":
        if _is_full_admin:
            await safe_edit(q, "👑 *لوحة تحكم الأدمن*\n\nاختر الإجراء:", admin_home_keyboard())
        else:
            await safe_edit(q, "📢 *لوحة البث*\n\nيمكنك إرسال رسائل جماعية.",
                            broadcast_admin_keyboard())
        return

    # ── v3: أزرار التحكم بالأنظمة ─────────────────────────────────
    if action == "toggle_bot":
        current = _bot_enabled()
        new_val  = "0" if current else "1"
        set_setting("bot_enabled", new_val)
        status = "✅ مفعّل" if new_val == "1" else "🔴 متوقف (صيانة)"
        await q.answer(f"البوت: {status}", show_alert=True)
        await safe_edit(q, "👑 *لوحة تحكم الأدمن*\n\nاختر الإجراء:", admin_home_keyboard())
        return

    if action == "toggle_deposit":
        current  = _deposit_enabled()
        new_val  = "0" if current else "1"
        set_setting("deposit_enabled", new_val)
        status = "✅ مفعّل" if new_val == "1" else "🔴 متوقف"
        await q.answer(f"الإيداع: {status}", show_alert=True)
        await safe_edit(q, "👑 *لوحة تحكم الأدمن*\n\nاختر الإجراء:", admin_home_keyboard())
        return

    if action == "toggle_paid":
        current  = _paid_numbers_enabled()
        new_val  = "0" if current else "1"
        set_setting("paid_numbers_enabled", new_val)
        status = "✅ مفعّل" if new_val == "1" else "🔴 متوقف"
        await q.answer(f"الأرقام المدفوعة: {status}", show_alert=True)
        await safe_edit(q, "👑 *لوحة تحكم الأدمن*\n\nاختر الإجراء:", admin_home_keyboard())
        return

    if action == "stats":
        top_text = ""
        try:
            with db._conn() as con:
                rows = con.execute("""
                    SELECT country_name, COUNT(*) AS c FROM user_numbers
                    GROUP BY country_name ORDER BY c DESC LIMIT 5
                """).fetchall()
            top_text = "\n".join(f"  • {r['country_name']}: {r['c']}" for r in rows) \
                       or "  _لا توجد بيانات_"
        except Exception:
            top_text = "—"
        text = (
            "📊 *إحصائيات البوت*\n\n"
            f"👥 إجمالي المستخدمين: *{db.count_users()}*\n"
            f"🚫 المحظورون: *{db.count_banned()}*\n"
            f"🟢 جلسات نشطة: *{db.count_active_sessions()}*\n"
            f"📞 إجمالي الجلسات: *{db.count_total_sessions()}*\n"
            f"💰 إجمالي الأرصدة: *{db.total_balance():.2f}$*\n\n"
            f"⏳ *في الانتظار:*\n"
            f"  • أرقام مدفوعة: {db.count_pending('paid_orders')}\n"
            f"  • إيداعات: {db.count_pending('deposit_requests')}\n"
            f"  • سحوبات: {db.count_pending('withdraw_requests')}\n\n"
            f"🌍 *أكثر الدول طلباً:*\n{top_text}"
        )
        await safe_edit(q, text, InlineKeyboardMarkup([
            [InlineKeyboardButton("🔄 تحديث", callback_data="admin:stats")],
            [InlineKeyboardButton("⬅️ رجوع", callback_data="admin:home")],
        ]))
        return

    if action == "users":
        # Format: admin:users:<page>:<filter>  filter=all|banned|active
        page       = int(parts[2]) if len(parts) > 2 else 0
        filt       = parts[3] if len(parts) > 3 else "all"
        page_size  = 8
        offset     = page * page_size

        # Fetch according to filter
        with db._conn() as _c:
            if filt == "banned":
                total = _c.execute("SELECT COUNT(*) AS c FROM users WHERE is_banned=1").fetchone()["c"]
                rows  = _c.execute(
                    "SELECT * FROM users WHERE is_banned=1 ORDER BY created_at DESC LIMIT ? OFFSET ?",
                    (page_size, offset)).fetchall()
            elif filt == "active":
                total = _c.execute("SELECT COUNT(*) AS c FROM users WHERE is_banned=0").fetchone()["c"]
                rows  = _c.execute(
                    "SELECT * FROM users WHERE is_banned=0 ORDER BY last_active DESC LIMIT ? OFFSET ?",
                    (page_size, offset)).fetchall()
            else:
                total = _c.execute("SELECT COUNT(*) AS c FROM users").fetchone()["c"]
                rows  = _c.execute(
                    "SELECT * FROM users ORDER BY created_at DESC LIMIT ? OFFSET ?",
                    (page_size, offset)).fetchall()
        users = [dict(r) for r in rows]

        if not users and page == 0:
            await safe_edit(q, "👥 لا يوجد مستخدمون.",
                InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ رجوع", callback_data="admin:home")]]))
            return

        total_pages = max(1, (total + page_size - 1) // page_size)
        filt_label  = {"all": "الكل", "banned": "المحظورون", "active": "النشطون"}.get(filt, "الكل")
        lines = [
            f"👥 *قائمة المستخدمين — {filt_label}*",
            f"📊 الإجمالي: *{total}* | الصفحة *{page+1}/{total_pages}*\n",
        ]
        for idx, u in enumerate(users, start=offset + 1):
            name = (u.get("first_name") or "").strip()
            if u.get("last_name"): name += f" {u['last_name']}"
            name = name or "بدون اسم"
            uname  = f"@{u['username']}" if u.get("username") else "—"
            ban    = " 🚫" if u.get("is_banned") else ""
            bal    = float(u.get("balance") or 0)
            refs   = int(u.get("referrals_count") or 0)
            cards  = int(u.get("wheel_cards") or 0)
            joined = "✅" if u.get("joined_channel") else "❌"
            last_active = str(u.get("last_active") or "")[:10]
            lines.append(
                f"*{idx}.* `{u['user_id']}`{ban}\n"
                f"   👤 {name}  {uname}\n"
                f"   💰 {bal:.2f}$  |  🎁 إحالات: {refs}  |  🎫 {cards}\n"
                f"   📡 مشترك: {joined}  |  🕐 آخر نشاط: {last_active}\n"
                f"   [📋 تفاصيل](tg://callback_data#admin:user_detail:{u['user_id']})"
            )

        # Navigation row
        nav = []
        if page > 0:
            nav.append(InlineKeyboardButton("⬅️ السابق", callback_data=f"admin:users:{page-1}:{filt}"))
        if offset + page_size < total:
            nav.append(InlineKeyboardButton("التالي ➡️", callback_data=f"admin:users:{page+1}:{filt}"))

        # Filter tabs
        filter_row = [
            InlineKeyboardButton("👥 الكل"       , callback_data="admin:users:0:all"),
            InlineKeyboardButton("✅ النشطون"     , callback_data="admin:users:0:active"),
            InlineKeyboardButton("🚫 المحظورون"   , callback_data="admin:users:0:banned"),
        ]
        kb = [filter_row]
        if nav: kb.append(nav)
        kb.append([
            InlineKeyboardButton("🔍 بحث بالآيدي", callback_data="admin:user_search_prompt"),
            InlineKeyboardButton("🏆 أفضل المحيلين", callback_data="admin:top_referrals"),
        ])
        kb.append([InlineKeyboardButton("⬅️ رجوع", callback_data="admin:home")])
        await safe_edit(q, "\n".join(lines), InlineKeyboardMarkup(kb))
        return

    if action == "user_search_prompt":
        db.set_admin_pending(user_id, "user_search")
        await safe_edit(q,
            "🔍 *بحث عن مستخدم*\n\n"
            "أرسل *آيدي المستخدم* (رقم) أو *اسم المستخدم* (@username):\n\n"
            "/cancel للإلغاء.",
            InlineKeyboardMarkup([[InlineKeyboardButton("❌ إلغاء", callback_data="admin:cancel")]]))
        return

    if action == "user_detail":
        tid = int(parts[2])
        u = db.get_user(tid)
        if not u:
            await q.answer("❌ مستخدم غير موجود", show_alert=True); return
        name = (u.get("first_name") or "").strip()
        if u.get("last_name"): name += f" {u['last_name']}"
        uname  = f"@{u['username']}" if u.get("username") else "—"
        ban    = "🚫 محظور" if u.get("is_banned") else "✅ نشط"
        bal    = float(u.get("balance") or 0)
        refs   = int(u.get("referrals_count") or 0)
        cards  = int(u.get("wheel_cards") or 0)
        joined = "✅ نعم" if u.get("joined_channel") else "❌ لا"
        tx_list = db.list_user_tx(tid, limit=5)
        tx_text = ""
        for tx in tx_list:
            sign = "+" if float(tx["amount"]) >= 0 else ""
            tx_text += f"\n  • {sign}{float(tx['amount']):.2f}$ — {tx.get('kind','')} ({tx.get('created_at','')[:10]})"
        text = (
            f"👤 *تفاصيل المستخدم*\n\n"
            f"🆔 الآيدي: `{tid}`\n"
            f"📛 الاسم: {name}\n"
            f"🔗 اليوزر: {uname}\n"
            f"📊 الحالة: {ban}\n"
            f"💰 الرصيد: *{bal:.2f}$*\n"
            f"🎁 الإحالات: *{refs}*\n"
            f"🎫 بطاقات العجلة: *{cards}*\n"
            f"📡 مشترك في القناة: {joined}\n"
            f"📅 الانضمام: {str(u.get('created_at',''))[:10]}\n"
            f"🕐 آخر نشاط: {str(u.get('last_active',''))[:10]}\n"
            f"\n💳 *آخر 5 معاملات:*{tx_text if tx_text else chr(10)+'  _لا توجد_'}"
        )
        ban_label = "فك الحظر ✅" if u.get("is_banned") else "حظر 🚫"
        await safe_edit(q, text, InlineKeyboardMarkup([
            [InlineKeyboardButton(ban_label, callback_data=f"admin:toggle_ban_direct:{tid}"),
             InlineKeyboardButton("💵 تعديل رصيده", callback_data=f"admin:set_bal_direct:{tid}")],
            [InlineKeyboardButton("⬅️ رجوع للقائمة", callback_data="admin:users:0:all")],
        ]))
        return

    if action == "toggle_ban_direct":
        tid = int(parts[2])
        u = db.get_user(tid)
        if not u:
            await q.answer("❌ مستخدم غير موجود", show_alert=True); return
        new_state = not bool(u.get("is_banned"))
        db.set_ban(tid, new_state)
        status = "🚫 محظور" if new_state else "✅ غير محظور"
        await q.answer(f"تم: {status}", show_alert=False)
        # Re-show detail
        context.drop_pending_updates = False
        await cb_admin_router(update, context)
        return

    if action == "set_bal_direct":
        tid = int(parts[2])
        db.set_admin_pending(user_id, "set_balance_direct", payload=str(tid))
        await safe_edit(q,
            f"💵 *تعديل رصيد المستخدم* `{tid}`\n\n"
            "أرسل الرصيد الجديد (رقم):\n"
            "مثال: `15.50`\n\n/cancel للإلغاء.",
            InlineKeyboardMarkup([[InlineKeyboardButton("❌ إلغاء", callback_data="admin:cancel")]]))
        return

    if action == "top_referrals":
        with db._conn() as _c:
            rows = _c.execute("""
                SELECT user_id, first_name, last_name, username, referrals_count, balance
                FROM users
                WHERE referrals_count >= 10
                ORDER BY referrals_count DESC
                LIMIT 10
            """).fetchall()
        if not rows:
            await safe_edit(q,
                "🏆 *أفضل المحيلين*\n\n_لا يوجد أحد بـ 10 إحالات أو أكثر بعد._",
                InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ رجوع", callback_data="admin:users:0:all")]]))
            return
        lines = ["🏆 *أفضل المحيلين* _(10 إحالات فأكثر)_\n"]
        medals = ["🥇", "🥈", "🥉"]
        for rank, r in enumerate(rows, 1):
            name = (r["first_name"] or "").strip()
            if r["last_name"]: name += f" {r['last_name']}"
            name = name or "بدون اسم"
            uname = f"@{r['username']}" if r["username"] else "—"
            medal = medals[rank - 1] if rank <= 3 else f"{rank}."
            lines.append(
                f"{medal} `{r['user_id']}` — {name} ({uname})\n"
                f"    🎁 إحالات: *{r['referrals_count']}*  |  💰 {float(r['balance']):.2f}$"
            )
        await safe_edit(q, "\n".join(lines), InlineKeyboardMarkup([
            [InlineKeyboardButton("🔄 تحديث", callback_data="admin:top_referrals")],
            [InlineKeyboardButton("⬅️ رجوع", callback_data="admin:users:0:all")],
        ]))
        return

    # ── Channels management ────────────────────────────────────────────
    if action == "channels":
        channels = list_force_channels()
        lines = ["📡 *إدارة قنوات الاشتراك الإجباري*\n"]
        lines.append(f"📌 *القناة الثابتة (config):*\n   `{FORCE_SUB_CHANNEL}` — {FORCE_SUB_CHANNEL_URL}\n")
        kb = []
        if channels:
            lines.append("📋 *القنوات المضافة من لوحة التحكم:*")
            for ch in channels:
                lines.append(f"  • `{ch['channel_id']}` — {ch.get('channel_name') or '—'}\n    {ch['channel_url']}")
                kb.append([
                    InlineKeyboardButton(
                        f"🗑️ حذف: {ch.get('channel_name') or ch['channel_id']}",
                        callback_data=f"admin:del_channel:{ch['id']}"
                    )
                ])
        else:
            lines.append("_لا توجد قنوات مضافة من لوحة التحكم بعد._")
        kb.append([InlineKeyboardButton("➕ إضافة قناة جديدة", callback_data="admin:add_channel_prompt")])
        kb.append([InlineKeyboardButton("⬅️ رجوع", callback_data="admin:home")])
        await safe_edit(q, "\n".join(lines), InlineKeyboardMarkup(kb))
        return

    if action == "add_channel_prompt":
        db.set_admin_pending(user_id, "add_channel")
        await safe_edit(q,
            "📡 *إضافة قناة اشتراك إجباري*\n\n"
            "أرسل في رسالة واحدة:\n"
            "`<معرف_القناة> <رابط_القناة> <اسم_القناة>`\n\n"
            "مثال:\n`@MyChannel https://t.me/MyChannel قناة الأخبار`\n\n"
            "ملاحظة: يمكن استخدام الآيدي الرقمي أيضاً مثل `-1001234567890`\n\n"
            "/cancel للإلغاء.",
            InlineKeyboardMarkup([[InlineKeyboardButton("❌ إلغاء", callback_data="admin:cancel")]]))
        return

    if action == "del_channel":
        ch_id = int(parts[2])
        ch = get_force_channel(ch_id)
        if not ch:
            await q.answer("❌ القناة غير موجودة", show_alert=True); return
        remove_force_channel(ch_id)
        await q.answer(f"✅ تم حذف القناة {ch.get('channel_name') or ch['channel_id']}", show_alert=False)
        # Refresh channels page
        q.data = "admin:channels"
        parts[1] = "channels"
        action = "channels"
        channels = list_force_channels()
        lines = ["📡 *إدارة قنوات الاشتراك الإجباري*\n"]
        lines.append(f"📌 *القناة الثابتة (config):*\n   `{FORCE_SUB_CHANNEL}` — {FORCE_SUB_CHANNEL_URL}\n")
        kb = []
        if channels:
            lines.append("📋 *القنوات المضافة من لوحة التحكم:*")
            for ch2 in channels:
                lines.append(f"  • `{ch2['channel_id']}` — {ch2.get('channel_name') or '—'}\n    {ch2['channel_url']}")
                kb.append([InlineKeyboardButton(
                    f"🗑️ حذف: {ch2.get('channel_name') or ch2['channel_id']}",
                    callback_data=f"admin:del_channel:{ch2['id']}"
                )])
        else:
            lines.append("_لا توجد قنوات مضافة._")
        kb.append([InlineKeyboardButton("➕ إضافة قناة جديدة", callback_data="admin:add_channel_prompt")])
        kb.append([InlineKeyboardButton("⬅️ رجوع", callback_data="admin:home")])
        await safe_edit(q, "\n".join(lines), InlineKeyboardMarkup(kb))
        return

    # ── Broadcast admins management ────────────────────────────────────
    if action == "broadcast_admins":
        admins = list_broadcast_admins()
        lines = ["👮 *إدارة أدمن البث*\n"]
        lines.append("أدمن البث يمكنهم إرسال رسائل جماعية فقط.\n")
        kb = []
        if admins:
            lines.append("📋 *أدمن البث الحاليون:*")
            for ba in admins:
                u = db.get_user(ba["user_id"]) or {}
                name = (u.get("first_name") or "").strip() or "—"
                uname = f"@{u['username']}" if u.get("username") else "—"
                note = ba.get("note") or ""
                lines.append(f"  • `{ba['user_id']}` — {name} ({uname})" + (f"\n    📝 {note}" if note else ""))
                kb.append([InlineKeyboardButton(
                    f"🗑️ إزالة: {name}",
                    callback_data=f"admin:del_broadcast_admin:{ba['user_id']}"
                )])
        else:
            lines.append("_لا يوجد أدمن بث حتى الآن._")
        kb.append([InlineKeyboardButton("➕ إضافة أدمن بث", callback_data="admin:add_broadcast_admin_prompt")])
        kb.append([InlineKeyboardButton("⬅️ رجوع", callback_data="admin:home")])
        await safe_edit(q, "\n".join(lines), InlineKeyboardMarkup(kb))
        return

    if action == "add_broadcast_admin_prompt":
        db.set_admin_pending(user_id, "add_broadcast_admin")
        await safe_edit(q,
            "👮 *إضافة أدمن بث جديد*\n\n"
            "أرسل في رسالة واحدة:\n"
            "`<آيدي_المستخدم> <ملاحظة اختيارية>`\n\n"
            "مثال:\n`123456789 مسؤول القناة`\n\n"
            "/cancel للإلغاء.",
            InlineKeyboardMarkup([[InlineKeyboardButton("❌ إلغاء", callback_data="admin:cancel")]]))
        return

    if action == "del_broadcast_admin":
        tid = int(parts[2])
        remove_broadcast_admin(tid)
        await q.answer("✅ تم إزالة أدمن البث", show_alert=False)
        q.data = "admin:broadcast_admins"
        admins = list_broadcast_admins()
        lines = ["👮 *إدارة أدمن البث*\n", "أدمن البث يمكنهم إرسال رسائل جماعية فقط.\n"]
        kb = []
        if admins:
            lines.append("📋 *أدمن البث الحاليون:*")
            for ba in admins:
                u = db.get_user(ba["user_id"]) or {}
                name = (u.get("first_name") or "").strip() or "—"
                uname = f"@{u['username']}" if u.get("username") else "—"
                lines.append(f"  • `{ba['user_id']}` — {name} ({uname})")
                kb.append([InlineKeyboardButton(f"🗑️ إزالة: {name}",
                    callback_data=f"admin:del_broadcast_admin:{ba['user_id']}")])
        else:
            lines.append("_لا يوجد أدمن بث._")
        kb.append([InlineKeyboardButton("➕ إضافة أدمن بث", callback_data="admin:add_broadcast_admin_prompt")])
        kb.append([InlineKeyboardButton("⬅️ رجوع", callback_data="admin:home")])
        await safe_edit(q, "\n".join(lines), InlineKeyboardMarkup(kb))
        return

    if action == "broadcast":
        db.set_admin_pending(user_id, "broadcast")
        await safe_edit(q,
            "📢 *إرسال رسالة جماعية*\n\n"
            "أرسل الآن نص الرسالة لبثها لجميع المستخدمين.\n"
            "/cancel للإلغاء.",
            InlineKeyboardMarkup([[InlineKeyboardButton("❌ إلغاء", callback_data="admin:cancel")]]))
        return

    if action == "ban_prompt":
        db.set_admin_pending(user_id, "ban_toggle")
        await safe_edit(q,
            "🚫 *حظر / فك حظر*\n\nأرسل آيدي المستخدم (رقم).\n/cancel للإلغاء.",
            InlineKeyboardMarkup([[InlineKeyboardButton("❌ إلغاء", callback_data="admin:cancel")]]))
        return

    if action == "set_balance_prompt":
        db.set_admin_pending(user_id, "set_balance")
        await safe_edit(q,
            "💵 *تعديل رصيد مستخدم*\n\n"
            "أرسل في رسالة واحدة:\n"
            "`<آيدي_المستخدم> <الرصيد_الجديد>`\n\n"
            "مثال: `123456789 12.50`\n\n"
            "/cancel للإلغاء.",
            InlineKeyboardMarkup([[InlineKeyboardButton("❌ إلغاء", callback_data="admin:cancel")]]))
        return

    if action == "cancel":
        db.clear_admin_pending(user_id)
        await safe_edit(q, "👑 *لوحة تحكم الأدمن*", admin_home_keyboard())
        return

    # ── Lists: paid orders / deposits / withdrawals ─────────────────
    if action in ("paid_list", "dep_list", "wd_list"):
        await _admin_list(q, action, int(parts[2]) if len(parts) > 2 else 0)
        return

    # ── Single record actions ───────────────────────────────────────
    if action == "paid_approve":
        order_id = int(parts[2])
        db.set_admin_pending(user_id, "paid_approve_input", payload=str(order_id))
        await safe_edit(q,
            f"💎 *تفعيل الطلب #{order_id}*\n\n"
            f"أرسل في رسالة واحدة:\n"
            f"`<أرقام_الهاتف_بدون_+> <slug_الدولة>`\n\n"
            f"مثال: `14386195836 united-states`\n\n"
            "(slug من قائمة الدول في موقع temp-number.com)\n"
            "/cancel للإلغاء.",
            InlineKeyboardMarkup([[InlineKeyboardButton("❌ إلغاء", callback_data="admin:cancel")]]))
        return

    if action == "paid_reject":
        order_id = int(parts[2])
        order = db.get_paid_order(order_id)
        if not order or order["status"] != "pending":
            await q.answer("الطلب غير موجود أو مُعالج", show_alert=True); return
        db.update_paid_order(order_id, status="rejected")
        # Refund
        db.add_tx(order["user_id"], float(order["price"]), "refund_paid_number",
                  note=f"رفض الطلب #{order_id}", ref_id=order_id)
        try:
            await context.bot.send_message(order["user_id"],
                f"❌ تم رفض طلب الرقم #{order_id} وإعادة المبلغ ({fmt_money(order['price'])}) لرصيدك.",
                parse_mode=ParseMode.MARKDOWN)
        except Exception: pass
        await safe_edit(q, f"✅ تم رفض الطلب #{order_id} وإعادة المبلغ.",
            InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ رجوع", callback_data="admin:home")]]))
        return

    if action == "dep_approve":
        req_id = int(parts[2])
        req = db.get_deposit(req_id)
        if not req or req["status"] != "pending":
            await q.answer("الطلب غير موجود أو مُعالج", show_alert=True); return
        db.update_deposit(req_id, status="approved")
        db.add_tx(req["user_id"], float(req["amount"]), "deposit_approved",
                  note=f"إيداع #{req_id}", ref_id=req_id)
        try:
            await context.bot.send_message(req["user_id"],
                f"✅ تمت الموافقة على إيداعك #{req_id} وإضافة *{fmt_money(req['amount'])}* لرصيدك.",
                parse_mode=ParseMode.MARKDOWN)
        except Exception: pass
        await safe_edit(q, f"✅ تمت الموافقة على الإيداع #{req_id}.",
            InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ رجوع", callback_data="admin:home")]]))
        return

    if action == "dep_reject":
        req_id = int(parts[2])
        req = db.get_deposit(req_id)
        if not req or req["status"] != "pending":
            await q.answer("الطلب غير موجود أو مُعالج", show_alert=True); return
        # Ask admin for rejection reason
        db.set_admin_pending(user_id, "dep_reject_reason",
                             payload=f"{req_id}:{req['user_id']}")
        await safe_edit(q,
            f"❌ *رفض طلب الإيداع #{req_id}*\n\n"
            f"أرسل *سبب الرفض* وسيُرسل للمستخدم:\n\n"
            "/cancel للإلغاء.",
            InlineKeyboardMarkup([[InlineKeyboardButton("❌ إلغاء", callback_data="admin:cancel")]]))
        return

    if action == "wd_approve":
        req_id = int(parts[2])
        req = db.get_withdraw(req_id)
        if not req or req["status"] != "pending":
            await q.answer("الطلب غير موجود أو مُعالج", show_alert=True); return
        db.update_withdraw(req_id, status="approved")
        # Already deducted at request time
        try:
            await context.bot.send_message(req["user_id"],
                f"✅ تمت الموافقة على سحبك #{req_id} ({fmt_money(req['amount'])}). "
                f"سيتم التحويل قريباً.",
                parse_mode=ParseMode.MARKDOWN)
        except Exception: pass
        await safe_edit(q, f"✅ تمت الموافقة على السحب #{req_id}.",
            InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ رجوع", callback_data="admin:home")]]))
        return

    if action == "wd_reject":
        req_id = int(parts[2])
        req = db.get_withdraw(req_id)
        if not req or req["status"] != "pending":
            await q.answer("الطلب غير موجود أو مُعالج", show_alert=True); return
        db.update_withdraw(req_id, status="rejected")
        # Refund balance
        db.add_tx(req["user_id"], float(req["amount"]), "withdraw_refund",
                  note=f"رفض السحب #{req_id}", ref_id=req_id)
        try:
            await context.bot.send_message(req["user_id"],
                f"❌ تم رفض طلب السحب #{req_id} وإعادة *{fmt_money(req['amount'])}* لرصيدك.",
                parse_mode=ParseMode.MARKDOWN)
        except Exception: pass
        await safe_edit(q, f"تم رفض السحب #{req_id} وإعادة المبلغ.",
            InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ رجوع", callback_data="admin:home")]]))
        return


async def _admin_list(q, kind: str, page: int):
    page_size = 5
    offset = page * page_size
    table_map = {
        "paid_list": ("paid_orders", db.list_paid_orders, "💎 طلبات الأرقام المدفوعة"),
        "dep_list":  ("deposit_requests", db.list_deposits, "⬇️ طلبات الإيداع"),
        "wd_list":   ("withdraw_requests", db.list_withdrawals, "⬆️ طلبات السحب"),
    }
    table, fetcher, title = table_map[kind]
    items = fetcher(status="pending", limit=50)
    total = len(items)
    page_items = items[offset:offset + page_size]

    if not items:
        await safe_edit(q, f"{title}\n\n_لا توجد طلبات معلقة._",
            InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ رجوع", callback_data="admin:home")]]))
        return

    lines = [f"{title}\n_عدد المعلقة: {total}_\n"]
    kb_rows = []

    for it in page_items:
        u = db.get_user(it["user_id"]) or {}
        uname = f"@{u['username']}" if u.get("username") else (u.get("first_name") or "—")
        if kind == "paid_list":
            svc = PAID_SERVICES.get(it["service"], it["service"])
            lines.append(
                f"\n*#{it['id']}* — {svc} — `{it['user_id']}` ({uname})\n"
                f"السعر: {fmt_money(it['price'])}  |  {it['created_at']}"
            )
            kb_rows.append([
                InlineKeyboardButton(f"✅ #{it['id']}", callback_data=f"admin:paid_approve:{it['id']}"),
                InlineKeyboardButton(f"❌ #{it['id']}", callback_data=f"admin:paid_reject:{it['id']}"),
            ])
        elif kind == "dep_list":
            method = DEPOSIT_METHODS.get(it["method"], it["method"])
            lines.append(
                f"\n*#{it['id']}* — {method} — `{it['user_id']}` ({uname})\n"
                f"المبلغ: {fmt_money(it['amount'])}\n"
                f"التفاصيل: `{it.get('tx_info','')}`"
            )
            kb_rows.append([
                InlineKeyboardButton(f"✅ #{it['id']}", callback_data=f"admin:dep_approve:{it['id']}"),
                InlineKeyboardButton(f"❌ #{it['id']}", callback_data=f"admin:dep_reject:{it['id']}"),
            ])
        else:  # wd_list
            method = WITHDRAW_METHODS.get(it["method"], it["method"])
            lines.append(
                f"\n*#{it['id']}* — {method} — `{it['user_id']}` ({uname})\n"
                f"المبلغ: {fmt_money(it['amount'])}\n"
                f"العنوان: `{it['address']}`"
            )
            kb_rows.append([
                InlineKeyboardButton(f"✅ #{it['id']}", callback_data=f"admin:wd_approve:{it['id']}"),
                InlineKeyboardButton(f"❌ #{it['id']}", callback_data=f"admin:wd_reject:{it['id']}"),
            ])

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("⬅️", callback_data=f"admin:{kind}:{page-1}"))
    if offset + page_size < total:
        nav.append(InlineKeyboardButton("➡️", callback_data=f"admin:{kind}:{page+1}"))
    if nav: kb_rows.append(nav)
    kb_rows.append([InlineKeyboardButton("⬅️ رجوع", callback_data="admin:home")])

    await safe_edit(q, "\n".join(lines), InlineKeyboardMarkup(kb_rows))


# ╔══════════════════════════════════════════════════════════════════╗
# ║                  TEXT INPUT HANDLER (admin + user pending)       ║
# ╚══════════════════════════════════════════════════════════════════╝

async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return
    if not await _ensure_user(update): return
    user_id = update.effective_user.id
    pending = db.get_user_pending(user_id)
    if not pending:
        return
    action = pending["action"]
    payload = pending.get("payload") or ""
    text = update.message.text.strip()

    # ── User pending actions ────────────────────────────────────────

    if action == "dep_amount":
        # User sent the amount — now ask for screenshot photo
        method = payload
        try:
            amount = float(text.replace("$", "").replace(",", ".").split()[0])
        except Exception:
            await update.message.reply_text(
                "❌ صيغة خاطئة. أرسل المبلغ بالأرقام فقط.\nمثال: `5` أو `12.50`\n\n"
                "أرسل /cancel للإلغاء.", parse_mode=ParseMode.MARKDOWN)
            return
        if amount <= 0:
            await update.message.reply_text("❌ المبلغ يجب أن يكون أكبر من صفر."); return
        # Move to dep_photo step
        db.set_user_pending(user_id, "dep_photo", payload=f"{method}:{amount}")
        await update.message.reply_text(
            f"📸 *الآن أرسل صورة إشعار الحوالة*\n\n"
            f"المبلغ المُسجّل: *{fmt_money(amount)}*\n"
            f"الطريقة: *{DEPOSIT_METHODS.get(method, method)}*\n\n"
            "أرسل الصورة كصورة عادية (ليس ملفاً).\n"
            "أرسل /cancel للإلغاء.",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("❌ إلغاء", callback_data="wallet:home")],
            ]))
        return

    if action == "withdraw_submit":
        method = payload
        db.clear_user_pending(user_id)
        parts = text.split(maxsplit=1)
        try:
            amount = float(parts[0].replace("$", "").replace(",", "."))
        except Exception:
            await update.message.reply_text("❌ صيغة خاطئة. /cancel للإلغاء."); return
        if amount < MIN_WITHDRAWAL:
            await update.message.reply_text(
                f"❌ الحد الأدنى للسحب: *{fmt_money(MIN_WITHDRAWAL)}*",
                parse_mode=ParseMode.MARKDOWN); return
        bal = db.get_balance(user_id)
        if amount > bal:
            await update.message.reply_text(
                f"❌ المبلغ يتجاوز رصيدك ({fmt_money(bal)})",
                parse_mode=ParseMode.MARKDOWN); return
        if len(parts) < 2 or not parts[1].strip():
            await update.message.reply_text("❌ يجب إرسال العنوان أيضاً."); return
        address = parts[1].strip()
        # Hold balance now
        db.add_tx(user_id, -amount, "withdraw_request", note=f"طلب سحب — {method}")
        req_id = db.create_withdraw_request(user_id, method, address, amount)
        await update.message.reply_text(
            f"✅ تم استلام طلب السحب *#{req_id}*\n"
            f"المبلغ: *{fmt_money(amount)}*\n"
            f"الطريقة: {WITHDRAW_METHODS.get(method, method)}\n"
            f"⏳ بانتظار التحويل.",
            reply_markup=main_menu_keyboard(user_id),
            parse_mode=ParseMode.MARKDOWN,
        )
        u = db.get_user(user_id) or {}
        uname = f"@{u['username']}" if u.get("username") else u.get("first_name") or "—"
        admin_text = (
            f"⬆️ *طلب سحب جديد*\n\n"
            f"رقم الطلب: `#{req_id}`\n"
            f"المستخدم: {uname} (`{user_id}`)\n"
            f"الطريقة: {WITHDRAW_METHODS.get(method, method)}\n"
            f"المبلغ: *{fmt_money(amount)}*\n"
            f"العنوان: `{address}`"
        )
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ تم التحويل", callback_data=f"admin:wd_approve:{req_id}"),
             InlineKeyboardButton("❌ رفض", callback_data=f"admin:wd_reject:{req_id}")],
        ])
        for aid in ADMIN_IDS:
            try:
                await context.bot.send_message(aid, admin_text,
                    reply_markup=kb, parse_mode=ParseMode.MARKDOWN)
            except Exception: pass
        return

    # ── Admin pending actions ───────────────────────────────────────
    _user_is_full_admin    = is_admin(user_id)
    _user_is_bcast_admin   = is_broadcast_admin(user_id)
    if not _user_is_full_admin and not _user_is_bcast_admin:
        return

    if action == "broadcast":
        db.clear_admin_pending(user_id)
        ids = db.all_user_ids(include_banned=False)
        await update.message.reply_text(f"📤 الإرسال إلى {len(ids)} مستخدم...")
        sent, failed = 0, 0
        for uid in ids:
            try:
                await context.bot.send_message(uid,
                    f"📢 *رسالة من الإدارة*\n\n{text}", parse_mode=ParseMode.MARKDOWN)
                sent += 1
            except Exception:
                failed += 1
            await asyncio.sleep(0.05)
        reply_kb = broadcast_admin_keyboard() if (_user_is_bcast_admin and not _user_is_full_admin) \
                   else admin_home_keyboard()
        await update.message.reply_text(
            f"✅ *اكتمل البث*\nتم: {sent} | فشل: {failed}",
            reply_markup=reply_kb, parse_mode=ParseMode.MARKDOWN)
        return

    # Below actions: full admins only
    if not _user_is_full_admin:
        return

    if action == "ban_toggle":
        db.clear_admin_pending(user_id)
        try:
            tid = int(text.strip())
        except ValueError:
            await update.message.reply_text("❌ آيدي غير صالح."); return
        u = db.get_user(tid)
        if not u:
            await update.message.reply_text(f"❌ لا يوجد مستخدم بالآيدي `{tid}`",
                parse_mode=ParseMode.MARKDOWN); return
        new_state = not bool(u.get("is_banned"))
        db.set_ban(tid, new_state)
        status = "🚫 محظور" if new_state else "✅ غير محظور"
        await update.message.reply_text(
            f"تم تحديث `{tid}` إلى: *{status}*",
            reply_markup=admin_home_keyboard(), parse_mode=ParseMode.MARKDOWN)
        return

    if action == "set_balance":
        db.clear_admin_pending(user_id)
        parts = text.split()
        if len(parts) < 2:
            await update.message.reply_text("❌ صيغة خاطئة. مثال: `123 12.50`",
                parse_mode=ParseMode.MARKDOWN); return
        try:
            tid = int(parts[0]); new_bal = float(parts[1])
        except ValueError:
            await update.message.reply_text("❌ صيغة خاطئة."); return
        u = db.get_user(tid)
        if not u:
            await update.message.reply_text(f"❌ لا يوجد مستخدم `{tid}`",
                parse_mode=ParseMode.MARKDOWN); return
        db.set_balance(tid, new_bal, note=f"admin {user_id}")
        await update.message.reply_text(
            f"✅ تم ضبط رصيد `{tid}` إلى *{fmt_money(new_bal)}*",
            reply_markup=admin_home_keyboard(), parse_mode=ParseMode.MARKDOWN)
        try:
            await context.bot.send_message(tid,
                f"💰 تم تعديل رصيدك من قبل الأدمن.\nالرصيد الجديد: *{fmt_money(new_bal)}*",
                parse_mode=ParseMode.MARKDOWN)
        except Exception: pass
        return

    if action == "dep_reject_reason":
        pparts = payload.split(":")
        req_id, target_uid = int(pparts[0]), int(pparts[1])
        db.clear_admin_pending(user_id)
        req = db.get_deposit(req_id)
        if not req or req["status"] != "pending":
            await update.message.reply_text("❌ الطلب غير موجود أو مُعالج بالفعل."); return
        db.update_deposit(req_id, status="rejected", rejection_reason=text)
        try:
            await context.bot.send_message(target_uid,
                f"❌ *تم رفض طلب الإيداع #{req_id}*\n\n"
                f"السبب: _{text}_\n\n"
                f"للاستفسار: {SUPPORT_USERNAME}",
                parse_mode=ParseMode.MARKDOWN)
        except Exception: pass
        await update.message.reply_text(
            f"✅ تم رفض الإيداع #{req_id} وإرسال السبب للمستخدم.",
            reply_markup=admin_home_keyboard())
        return

    if action == "paid_approve_input":
        order_id = int(payload)
        order = db.get_paid_order(order_id)
        if not order or order["status"] != "pending":
            await update.message.reply_text("❌ الطلب غير صالح أو مُعالج.")
            db.clear_admin_pending(user_id); return
        parts = text.split()
        if len(parts) < 2:
            await update.message.reply_text("❌ أرسل: `<أرقام> <slug>`",
                parse_mode=ParseMode.MARKDOWN); return
        digits = "".join(c for c in parts[0] if c.isdigit())
        slug = parts[1].strip().lower()
        if not digits or not slug:
            await update.message.reply_text("❌ بيانات ناقصة."); return
        db.clear_admin_pending(user_id)

        # Find country name
        countries = _get_countries_cached()
        country_name = next((c["name"] for c in countries if c["slug"] == slug), slug)
        phone_display = f"+{digits}"

        # Snapshot existing messages
        try:
            existing = get_messages_by_number(slug, digits, limit=20)
        except Exception:
            existing = []
        seen_csv = snapshot_seen(existing)

        expires_at = (datetime.now() + timedelta(seconds=PAID_SESSION_DURATION_SEC)).isoformat()
        record_id = db.set_active_number(
            order["user_id"], phone_display, slug, country_name,
            expires_at, seen_csv=seen_csv, kind="paid"
        )
        db.update_paid_order(order_id, status="active", phone=phone_display,
                             country_slug=slug, country_name=country_name)

        # Note: No polling job started here — cron endpoint handles active session polling
        target_user = order["user_id"]

        try:
            await context.bot.send_message(target_user,
                f"✅ *تم تفعيل رقمك المدفوع #{order_id}*\n\n"
                f"الخدمة: *{PAID_SERVICES.get(order['service'], order['service'])}*\n"
                f"📱 الرقم: `{phone_display}`\n"
                f"🇺🇳 الدولة: {country_name}\n"
                f"⏱️ نشط لمدة: 30 دقيقة\n"
                f"🔄 سيتم فحص الرسائل تلقائياً.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("📥 صندوق الوارد", callback_data="inbox")],
                    [InlineKeyboardButton("⏹️ إيقاف", callback_data="stop")],
                ]),
                parse_mode=ParseMode.MARKDOWN)
        except Exception: pass

        await update.message.reply_text(
            f"✅ تم تفعيل الطلب #{order_id} وإرسال الرقم للمستخدم.",
            reply_markup=admin_home_keyboard())
        return

    if action == "user_search":
        db.clear_admin_pending(user_id)
        query = text.strip().lstrip("@")
        # Try by numeric ID first
        found = None
        try:
            found = db.get_user(int(query))
        except ValueError:
            pass
        # Fallback: search by username
        if not found:
            with db._conn() as _c:
                row = _c.execute(
                    "SELECT * FROM users WHERE LOWER(username)=LOWER(?)", (query,)
                ).fetchone()
                if row:
                    found = dict(row)
        if not found:
            await update.message.reply_text(
                f"❌ لم يُعثر على مستخدم بالآيدي/اليوزر: `{text.strip()}`",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔍 بحث مرة أخرى", callback_data="admin:user_search_prompt")],
                    [InlineKeyboardButton("⬅️ رجوع", callback_data="admin:users:0:all")],
                ]))
            return
        uid2 = found["user_id"]
        name = (found.get("first_name") or "").strip()
        if found.get("last_name"): name += f" {found['last_name']}"
        name = name or "بدون اسم"
        uname  = f"@{found['username']}" if found.get("username") else "—"
        ban    = "🚫 محظور" if found.get("is_banned") else "✅ نشط"
        bal    = float(found.get("balance") or 0)
        refs   = int(found.get("referrals_count") or 0)
        cards  = int(found.get("wheel_cards") or 0)
        joined = "✅ نعم" if found.get("joined_channel") else "❌ لا"
        tx_list = db.list_user_tx(uid2, limit=5)
        tx_text = ""
        for tx in tx_list:
            sign = "+" if float(tx["amount"]) >= 0 else ""
            tx_text += f"\n  • {sign}{float(tx['amount']):.2f}$ — {tx.get('kind','')} ({str(tx.get('created_at',''))[:10]})"
        await update.message.reply_text(
            f"🔍 *نتيجة البحث*\n\n"
            f"🆔 الآيدي: `{uid2}`\n"
            f"📛 الاسم: {name}\n"
            f"🔗 اليوزر: {uname}\n"
            f"📊 الحالة: {ban}\n"
            f"💰 الرصيد: *{bal:.2f}$*\n"
            f"🎁 الإحالات: *{refs}*\n"
            f"🎫 بطاقات العجلة: *{cards}*\n"
            f"📡 مشترك: {joined}\n"
            f"📅 الانضمام: {str(found.get('created_at',''))[:10]}\n"
            f"\n💳 *آخر 5 معاملات:*{tx_text if tx_text else chr(10)+'  _لا توجد_'}",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔍 بحث آخر", callback_data="admin:user_search_prompt"),
                 InlineKeyboardButton("📋 قائمة المستخدمين", callback_data="admin:users:0:all")],
            ]))
        return

    if action == "set_balance_direct":
        tid = int(payload)
        db.clear_admin_pending(user_id)
        try:
            new_bal = float(text.strip().replace("$", "").replace(",", "."))
        except ValueError:
            await update.message.reply_text("❌ رقم غير صالح.", reply_markup=admin_home_keyboard()); return
        u = db.get_user(tid)
        if not u:
            await update.message.reply_text(f"❌ لا يوجد مستخدم `{tid}`",
                parse_mode=ParseMode.MARKDOWN, reply_markup=admin_home_keyboard()); return
        db.set_balance(tid, new_bal, note=f"admin {user_id}")
        await update.message.reply_text(
            f"✅ تم ضبط رصيد `{tid}` إلى *{fmt_money(new_bal)}*",
            reply_markup=admin_home_keyboard(), parse_mode=ParseMode.MARKDOWN)
        try:
            await context.bot.send_message(tid,
                f"💰 تم تعديل رصيدك من قبل الأدمن.\nالرصيد الجديد: *{fmt_money(new_bal)}*",
                parse_mode=ParseMode.MARKDOWN)
        except Exception: pass
        return

    if action == "add_channel":
        db.clear_admin_pending(user_id)
        ch_parts = text.strip().split(maxsplit=2)
        if len(ch_parts) < 2:
            await update.message.reply_text(
                "❌ صيغة خاطئة. مثال:\n`@MyChannel https://t.me/MyChannel اسم القناة`",
                parse_mode=ParseMode.MARKDOWN, reply_markup=admin_home_keyboard()); return
        ch_id   = ch_parts[0]
        ch_url  = ch_parts[1]
        ch_name = ch_parts[2] if len(ch_parts) > 2 else ch_id
        added = add_force_channel(ch_id, ch_url, ch_name)
        if added:
            await update.message.reply_text(
                f"✅ تمت إضافة القناة بنجاح:\n"
                f"📡 المعرف: `{ch_id}`\n"
                f"🔗 الرابط: {ch_url}\n"
                f"📛 الاسم: {ch_name}",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("📡 إدارة القنوات", callback_data="admin:channels")],
                    [InlineKeyboardButton("⬅️ لوحة الأدمن", callback_data="admin:home")],
                ]))
        else:
            await update.message.reply_text(
                f"⚠️ القناة `{ch_id}` موجودة مسبقاً.",
                parse_mode=ParseMode.MARKDOWN, reply_markup=admin_home_keyboard())
        return

    if action == "add_broadcast_admin":
        db.clear_admin_pending(user_id)
        ba_parts = text.strip().split(maxsplit=1)
        try:
            tid = int(ba_parts[0])
        except ValueError:
            await update.message.reply_text("❌ آيدي غير صالح.", reply_markup=admin_home_keyboard()); return
        note = ba_parts[1] if len(ba_parts) > 1 else ""
        if is_admin(tid):
            await update.message.reply_text("⚠️ هذا المستخدم أدمن رئيسي مسبقاً.",
                reply_markup=admin_home_keyboard()); return
        added = add_broadcast_admin(tid, user_id, note)
        if added:
            u = db.get_user(tid)
            name = (u.get("first_name") or str(tid)) if u else str(tid)
            await update.message.reply_text(
                f"✅ تمت إضافة أدمن البث بنجاح:\n"
                f"🆔 الآيدي: `{tid}`\n"
                f"👤 الاسم: {name}\n"
                f"📝 ملاحظة: {note or '—'}",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("👮 إدارة أدمن البث", callback_data="admin:broadcast_admins")],
                    [InlineKeyboardButton("⬅️ لوحة الأدمن", callback_data="admin:home")],
                ]))
            try:
                await context.bot.send_message(tid,
                    "✅ *تم منحك صلاحية أدمن البث*\n\n"
                    "يمكنك الآن إرسال رسائل جماعية لجميع مستخدمي البوت.\n"
                    "استخدم الأمر /admin للوصول للوحة البث.",
                    parse_mode=ParseMode.MARKDOWN)
            except Exception: pass
        else:
            await update.message.reply_text(
                f"⚠️ هذا المستخدم (`{tid}`) مضاف كأدمن بث مسبقاً.",
                parse_mode=ParseMode.MARKDOWN, reply_markup=admin_home_keyboard())
        return


# ╔══════════════════════════════════════════════════════════════════╗
# ║                      PHOTO HANDLER (deposit)                    ║
# ╚══════════════════════════════════════════════════════════════════╝

async def photo_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles deposit screenshot photos sent by users."""
    if not update.message or not update.message.photo:
        return
    if not await _ensure_user(update): return
    user_id = update.effective_user.id
    pending = db.get_user_pending(user_id)
    if not pending or pending["action"] != "dep_photo":
        return

    payload = pending.get("payload") or ""
    pparts = payload.split(":")
    if len(pparts) < 2:
        return
    method = pparts[0]
    try:
        amount = float(pparts[1])
    except ValueError:
        return

    db.clear_user_pending(user_id)
    # Best quality photo
    photo_file_id = update.message.photo[-1].file_id
    req_id = db.create_deposit_request(user_id, method, amount, tx_info="", )
    db.update_deposit(req_id, photo_file_id=photo_file_id)

    await update.message.reply_text(
        f"✅ *تم استلام طلب الإيداع #{req_id}*\n\n"
        f"المبلغ: *{fmt_money(amount)}*\n"
        f"الطريقة: *{DEPOSIT_METHODS.get(method, method)}*\n\n"
        f"⏳ بانتظار مراجعة الأدمن.",
        reply_markup=main_menu_keyboard(user_id),
        parse_mode=ParseMode.MARKDOWN,
    )

    # Notify admins with photo
    u = db.get_user(user_id) or {}
    uname = f"@{u['username']}" if u.get("username") else (u.get("first_name") or "—")
    caption = (
        f"📥 *طلب إيداع جديد #{req_id}*\n\n"
        f"المستخدم: {uname} (`{user_id}`)\n"
        f"الطريقة: *{DEPOSIT_METHODS.get(method, method)}*\n"
        f"المبلغ: *{fmt_money(amount)}*"
    )
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ موافقة", callback_data=f"admin:dep_approve:{req_id}"),
         InlineKeyboardButton("❌ رفض (مع سبب)", callback_data=f"admin:dep_reject:{req_id}")],
    ])
    for aid in ADMIN_IDS:
        try:
            await context.bot.send_photo(aid, photo_file_id,
                caption=caption, reply_markup=kb, parse_mode=ParseMode.MARKDOWN)
        except Exception:
            try:
                await context.bot.send_message(aid, caption,
                    reply_markup=kb, parse_mode=ParseMode.MARKDOWN)
            except Exception:
                pass


# ╔══════════════════════════════════════════════════════════════════╗
# ║                WEBHOOK APPLICATION SETUP                         ║
# ╚══════════════════════════════════════════════════════════════════╝

def build_application() -> Application:
    """Build and return a PTB Application with all handlers registered."""
    app = Application.builder().token(TOKEN).build()

    # Commands
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("inbox", cmd_inbox))
    app.add_handler(CommandHandler("stop", cmd_stop))
    app.add_handler(CommandHandler("cancel", cmd_cancel))
    app.add_handler(CommandHandler("admin", cmd_admin))

    # Callbacks
    app.add_handler(CallbackQueryHandler(cb_main_menu, pattern="^main_menu$"))
    app.add_handler(CallbackQueryHandler(cb_help, pattern="^help$"))
    app.add_handler(CallbackQueryHandler(cb_verify_sub, pattern="^verify_sub$"))
    app.add_handler(CallbackQueryHandler(cb_countries, pattern=r"^countries:\d+$"))
    app.add_handler(CallbackQueryHandler(cb_country, pattern=r"^country:[^:]+:\d+$"))
    app.add_handler(CallbackQueryHandler(cb_pick, pattern=r"^pick:[^:]+:\d+$"))
    app.add_handler(CallbackQueryHandler(cb_inbox, pattern="^inbox$"))
    app.add_handler(CallbackQueryHandler(cb_stop, pattern="^stop$"))
    app.add_handler(CallbackQueryHandler(cb_paid_router, pattern=r"^paid:"))
    # Paid number country/number selection
    app.add_handler(CallbackQueryHandler(cb_ppick_countries, pattern=r"^ppick:[^:]+:\d+$"))
    app.add_handler(CallbackQueryHandler(cb_ppick_country, pattern=r"^ppcountry:[^:]+:[^:]+:\d+$"))
    app.add_handler(CallbackQueryHandler(cb_ppick_confirm, pattern=r"^ppconfirm:[^:]+:[^:]+:\d+$"))
    app.add_handler(CallbackQueryHandler(cb_ppick_do, pattern=r"^ppdo:[^:]+:[^:]+:\d+$"))
    app.add_handler(CallbackQueryHandler(cb_wallet_router, pattern=r"^wallet:"))
    app.add_handler(CallbackQueryHandler(cb_ref_router, pattern=r"^ref:"))
    app.add_handler(CallbackQueryHandler(cb_wheel_router, pattern=r"^wheel:"))
    # Admin panel — handles all admin: callbacks (full admins + broadcast admins)
    app.add_handler(CallbackQueryHandler(cb_admin_router, pattern=r"^admin:"))

    # Photo handler (deposit screenshots)
    app.add_handler(MessageHandler(filters.PHOTO, photo_handler))
    # Free-text handler for pending input flows (deposit/withdraw/admin)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))

    return app


# Module-level singleton for warm serverless reuse
_APP: Application | None = None


async def get_application() -> Application:
    """Lazily build, initialize, and cache the PTB Application singleton."""
    global _APP
    if _APP is None:
        app = build_application()
        await app.initialize()
        _APP = app
    return _APP


async def process_update(update_dict: dict) -> None:
    """Deserialize and dispatch a single Telegram update dict."""
    app = await get_application()
    update = Update.de_json(update_dict, app.bot)
    await app.process_update(update)
