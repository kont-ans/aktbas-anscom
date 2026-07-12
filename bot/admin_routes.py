"""
لوحة إدارة البوت — Flask Blueprint (Vercel/Postgres edition)
يُوصَّل هذا البلوبرينت بالتطبيق الرئيسي في api/index.py
"""
import time
import random
import secrets
import logging
from functools import wraps

from flask import Blueprint, jsonify, request

from . import database as db
from . import config
from .config import (
    ADMIN_PANEL_TOKEN,
    DEPOSIT_METHODS,
    WITHDRAW_METHODS,
    PAID_SERVICES,
    ADMIN_IDS,
)

admin_bp = Blueprint("admin", __name__)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("admin_panel")


# ── Auth middleware ─────────────────────────────────────────────────

def require_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = (
            request.headers.get("X-Admin-Token")
            or request.args.get("token")
            or (request.json.get("token") if request.is_json else None)
        )
        if token == ADMIN_PANEL_TOKEN:
            return f(*args, **kwargs)
        # التحقق من رموز الجلسة المؤقتة المخزّنة في قاعدة البيانات
        expires = db.get_admin_session(token)
        if expires and time.time() < expires:
            return f(*args, **kwargs)
        return jsonify({"error": "Unauthorized"}), 401
    return decorated


# ── Telegram helper ─────────────────────────────────────────────────

def _send_tg_message(chat_id: int, text: str) -> bool:
    """إرسال رسالة مباشرة عبر Telegram Bot API"""
    import requests as _req
    from .config import TOKEN as BOT_TOKEN
    try:
        r = _req.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            json={"chat_id": chat_id, "text": text, "parse_mode": "Markdown"},
            timeout=10,
        )
        return r.ok
    except Exception as e:
        logger.error("TG send error: %s", e)
        return False


# ── Login via OTP ────────────────────────────────────────────────────

@admin_bp.route("/api/request_login_code", methods=["POST"])
def api_request_login_code():
    """توليد كود OTP وإرساله للأدمن عبر تيليجرام (لا تحتاج مصادقة)"""
    if not ADMIN_IDS:
        return jsonify({"error": "لا يوجد أدمن مُعرَّف في الإعدادات"}), 400

    admin_id = ADMIN_IDS[0]

    # منع الطلبات المتكررة خلال 60 ثانية (OTP صالح 5 دقائق، كولداون = 5-1 = 4 دقيقة مرّت)
    existing = db.get_admin_otp(admin_id)
    if existing and time.time() < existing["expires_at"] - 240:
        remaining = int(existing["expires_at"] - 240 - time.time())
        return jsonify({"error": f"انتظر {remaining} ثانية قبل الطلب مجدداً"}), 429

    code = str(random.randint(100000, 999999))
    expires_at = time.time() + 300  # 5 minutes
    db.create_admin_otp(admin_id, code, expires_at)

    msg = (
        "🔐 *كود دخول لوحة الإدارة*\n\n"
        f"`{code}`\n\n"
        "⏰ صالح لمدة *5 دقائق* فقط\n"
        "⚠️ لا تشارك هذا الكود مع أحد"
    )
    ok = _send_tg_message(admin_id, msg)
    if ok:
        return jsonify({"success": True, "message": "تم إرسال الكود إلى تيليجرام ✅"})
    else:
        return jsonify({"error": "فشل إرسال الرسالة — تأكد من تشغيل البوت"}), 500


@admin_bp.route("/api/verify_login_code", methods=["POST"])
def api_verify_login_code():
    """التحقق من الكود وإنشاء رمز جلسة (لا تحتاج مصادقة)"""
    if not ADMIN_IDS:
        return jsonify({"error": "لا يوجد أدمن"}), 400

    data     = request.json or {}
    code     = str(data.get("code", "")).strip()
    admin_id = ADMIN_IDS[0]
    otp      = db.get_admin_otp(admin_id)

    if not otp:
        return jsonify({"error": "لم يتم طلب كود بعد — اضغط «أرسل الكود» أولاً"}), 400
    if time.time() > otp["expires_at"]:
        db.clear_admin_otp(admin_id)
        return jsonify({"error": "انتهت صلاحية الكود — اطلب كوداً جديداً"}), 400
    if otp["code"] != code:
        return jsonify({"error": "الكود غير صحيح"}), 401

    # الكود صحيح → إنشاء رمز جلسة لمدة 24 ساعة
    db.clear_admin_otp(admin_id)
    session_token = secrets.token_hex(32)
    db.create_admin_session(session_token, time.time() + 86400)
    return jsonify({"success": True, "token": session_token})


# ── Stats ───────────────────────────────────────────────────────────

@admin_bp.route("/api/stats")
@require_auth
def api_stats():
    try:
        with db._conn() as con:
            top_countries = con.execute("""
                SELECT country_name, COUNT(*) AS c FROM user_numbers
                GROUP BY country_name ORDER BY c DESC LIMIT 5
            """).fetchall()
            top_c = [{"country": r["country_name"], "count": r["c"]} for r in top_countries]

            today_users = con.execute("""
                SELECT COUNT(*) AS c FROM users
                WHERE DATE(created_at) = CURRENT_DATE
            """).fetchone()["c"]

            today_sessions = con.execute("""
                SELECT COUNT(*) AS c FROM user_numbers
                WHERE DATE(started_at) = CURRENT_DATE
            """).fetchone()["c"]

        return jsonify({
            "total_users":        db.count_users(),
            "banned_users":       db.count_banned(),
            "active_sessions":    db.count_active_sessions(),
            "total_sessions":     db.count_total_sessions(),
            "total_balance":      round(db.total_balance(), 2),
            "pending_deposits":   db.count_pending("deposit_requests"),
            "pending_withdrawals": db.count_pending("withdraw_requests"),
            "pending_orders":     db.count_pending("paid_orders"),
            "top_countries":      top_c,
            "today_users":        today_users,
            "today_sessions":     today_sessions,
        })
    except Exception as e:
        logger.error("Stats error: %s", e)
        return jsonify({"error": str(e)}), 500


# ── Settings ────────────────────────────────────────────────────────

@admin_bp.route("/api/settings", methods=["GET"])
@require_auth
def api_get_settings():
    return jsonify(db.get_all_settings())


@admin_bp.route("/api/settings", methods=["POST"])
@require_auth
def api_set_settings():
    data = request.json or {}
    allowed = {"bot_enabled", "deposit_enabled", "paid_numbers_enabled"}
    updated = {}
    for key, val in data.items():
        if key in allowed:
            db.set_setting(key, "1" if val else "0")
            updated[key] = "1" if val else "0"
    return jsonify({"updated": updated, "settings": db.get_all_settings()})


# ── Users ────────────────────────────────────────────────────────────

@admin_bp.route("/api/users")
@require_auth
def api_users():
    page     = int(request.args.get("page", 0))
    filt     = request.args.get("filter", "all")
    search   = request.args.get("search", "").strip()
    per_page = 15
    offset   = page * per_page

    try:
        with db._conn() as con:
            if search:
                # بحث بالآيدي أو اليوزرنيم
                try:
                    uid = int(search)
                    rows = con.execute(
                        "SELECT * FROM users WHERE user_id=%s LIMIT %s",
                        (uid, per_page)
                    ).fetchall()
                    total = len(rows)
                except ValueError:
                    q = f"%{search.lstrip('@')}%"
                    total = con.execute(
                        "SELECT COUNT(*) FROM users WHERE username LIKE %s OR first_name LIKE %s",
                        (q, q)
                    ).fetchone()[0]
                    rows = con.execute(
                        "SELECT * FROM users WHERE username LIKE %s OR first_name LIKE %s LIMIT %s OFFSET %s",
                        (q, q, per_page, offset)
                    ).fetchall()
            elif filt == "banned":
                total = con.execute("SELECT COUNT(*) FROM users WHERE is_banned=1").fetchone()[0]
                rows  = con.execute(
                    "SELECT * FROM users WHERE is_banned=1 ORDER BY created_at DESC LIMIT %s OFFSET %s",
                    (per_page, offset)
                ).fetchall()
            elif filt == "active":
                total = con.execute("SELECT COUNT(*) FROM users WHERE is_banned=0").fetchone()[0]
                rows  = con.execute(
                    "SELECT * FROM users WHERE is_banned=0 ORDER BY last_active DESC LIMIT %s OFFSET %s",
                    (per_page, offset)
                ).fetchall()
            else:
                total = con.execute("SELECT COUNT(*) FROM users").fetchone()[0]
                rows  = con.execute(
                    "SELECT * FROM users ORDER BY created_at DESC LIMIT %s OFFSET %s",
                    (per_page, offset)
                ).fetchall()

        users = [dict(r) for r in rows]
        return jsonify({
            "users":       users,
            "total":       total,
            "page":        page,
            "per_page":    per_page,
            "total_pages": max(1, (total + per_page - 1) // per_page),
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@admin_bp.route("/api/users/<int:user_id>")
@require_auth
def api_user_detail(user_id):
    u = db.get_user(user_id)
    if not u:
        return jsonify({"error": "User not found"}), 404
    u["transactions"] = db.list_user_tx(user_id, limit=10)
    active = db.get_active_number(user_id)
    u["active_number"] = dict(active) if active else None
    return jsonify(u)


@admin_bp.route("/api/users/<int:user_id>/ban", methods=["POST"])
@require_auth
def api_ban_user(user_id):
    data   = request.json or {}
    banned = bool(data.get("banned", True))
    u = db.get_user(user_id)
    if not u:
        return jsonify({"error": "User not found"}), 404
    db.set_ban(user_id, banned)
    return jsonify({"user_id": user_id, "is_banned": banned})


@admin_bp.route("/api/users/<int:user_id>/balance", methods=["POST"])
@require_auth
def api_set_balance(user_id):
    data = request.json or {}
    try:
        amount = float(data["amount"])
    except (KeyError, ValueError):
        return jsonify({"error": "Invalid amount"}), 400
    u = db.get_user(user_id)
    if not u:
        return jsonify({"error": "User not found"}), 404
    db.set_balance(user_id, amount, note="admin_panel_set")
    return jsonify({"user_id": user_id, "new_balance": amount})


# ── Deposits ────────────────────────────────────────────────────────

@admin_bp.route("/api/deposits")
@require_auth
def api_deposits():
    status = request.args.get("status", "pending")
    limit  = int(request.args.get("limit", 30))
    items  = db.list_deposits(status=status if status != "all" else None, limit=limit)
    for it in items:
        u = db.get_user(it["user_id"]) or {}
        it["user_name"]    = (u.get("first_name") or "") + (" " + u.get("last_name", "") if u.get("last_name") else "")
        it["username"]     = u.get("username") or ""
        it["method_label"] = DEPOSIT_METHODS.get(it["method"], it["method"])
    return jsonify(items)


@admin_bp.route("/api/deposits/<int:req_id>/approve", methods=["POST"])
@require_auth
def api_approve_deposit(req_id):
    req = db.get_deposit(req_id)
    if not req:
        return jsonify({"error": "Not found"}), 404
    if req["status"] != "pending":
        return jsonify({"error": "Already processed"}), 400
    db.update_deposit(req_id, status="approved")
    db.add_tx(req["user_id"], float(req["amount"]), "deposit_approved",
              note=f"إيداع #{req_id} (لوحة التحكم)", ref_id=req_id)
    return jsonify({"success": True, "req_id": req_id})


@admin_bp.route("/api/deposits/<int:req_id>/reject", methods=["POST"])
@require_auth
def api_reject_deposit(req_id):
    req = db.get_deposit(req_id)
    if not req:
        return jsonify({"error": "Not found"}), 404
    if req["status"] != "pending":
        return jsonify({"error": "Already processed"}), 400
    data   = request.json or {}
    reason = data.get("reason", "رُفض من لوحة التحكم")
    db.update_deposit(req_id, status="rejected", rejection_reason=reason)
    return jsonify({"success": True, "req_id": req_id})


# ── Withdrawals ─────────────────────────────────────────────────────

@admin_bp.route("/api/withdrawals")
@require_auth
def api_withdrawals():
    status = request.args.get("status", "pending")
    limit  = int(request.args.get("limit", 30))
    items  = db.list_withdrawals(status=status if status != "all" else None, limit=limit)
    for it in items:
        u = db.get_user(it["user_id"]) or {}
        it["user_name"]    = (u.get("first_name") or "") + (" " + u.get("last_name", "") if u.get("last_name") else "")
        it["username"]     = u.get("username") or ""
        it["method_label"] = WITHDRAW_METHODS.get(it["method"], it["method"])
    return jsonify(items)


@admin_bp.route("/api/withdrawals/<int:req_id>/approve", methods=["POST"])
@require_auth
def api_approve_withdrawal(req_id):
    req = db.get_withdraw(req_id)
    if not req:
        return jsonify({"error": "Not found"}), 404
    if req["status"] != "pending":
        return jsonify({"error": "Already processed"}), 400
    db.update_withdraw(req_id, status="approved")
    return jsonify({"success": True, "req_id": req_id})


@admin_bp.route("/api/withdrawals/<int:req_id>/reject", methods=["POST"])
@require_auth
def api_reject_withdrawal(req_id):
    req = db.get_withdraw(req_id)
    if not req:
        return jsonify({"error": "Not found"}), 404
    if req["status"] != "pending":
        return jsonify({"error": "Already processed"}), 400
    db.update_withdraw(req_id, status="rejected")
    # Refund balance
    db.add_tx(req["user_id"], float(req["amount"]), "withdraw_refund",
              note=f"رفض السحب #{req_id} (لوحة التحكم)", ref_id=req_id)
    return jsonify({"success": True, "req_id": req_id})


# ── Paid Orders ──────────────────────────────────────────────────────

@admin_bp.route("/api/orders")
@require_auth
def api_orders():
    status = request.args.get("status", "pending")
    limit  = int(request.args.get("limit", 30))
    items  = db.list_paid_orders(status=status if status != "all" else None, limit=limit)
    for it in items:
        u = db.get_user(it["user_id"]) or {}
        it["user_name"]     = (u.get("first_name") or "") + (" " + u.get("last_name", "") if u.get("last_name") else "")
        it["username"]      = u.get("username") or ""
        it["service_label"] = PAID_SERVICES.get(it["service"], it["service"])
    return jsonify(items)


@admin_bp.route("/api/orders/<int:order_id>/reject", methods=["POST"])
@require_auth
def api_reject_order(order_id):
    order = db.get_paid_order(order_id)
    if not order:
        return jsonify({"error": "Not found"}), 404
    if order["status"] not in ("pending", "paid"):
        return jsonify({"error": "Cannot reject this order"}), 400
    db.update_paid_order(order_id, status="rejected")
    db.add_tx(order["user_id"], float(order["price"]), "refund_paid_number",
              note=f"رفض الطلب #{order_id} (لوحة التحكم)", ref_id=order_id)
    return jsonify({"success": True, "order_id": order_id})


# ── Broadcast ────────────────────────────────────────────────────────

@admin_bp.route("/api/broadcast_count")
@require_auth
def api_broadcast_count():
    ids = db.all_user_ids(include_banned=False)
    return jsonify({"count": len(ids)})


# ── Health check ────────────────────────────────────────────────────

@admin_bp.route("/api/health")
def api_health():
    return jsonify({"status": "ok"})
