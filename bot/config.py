import os

# ╔══════════════════════════════════════════════════════════════════╗
# ║                    إعدادات البوت (نسخة Vercel)                  ║
# ║  كل القيم الحساسة تُقرأ من متغيرات البيئة — لا تكتب أي سر هنا.   ║
# ╚══════════════════════════════════════════════════════════════════╝

# ── بيانات البوت ─────────────────────────────────────────────────────
TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]  # يجب ضبطه في متغيرات بيئة Vercel
ADMIN_IDS = [int(x) for x in os.environ.get("ADMIN_IDS", "8630643080").split(",") if x.strip()]
BOT_USERNAME = os.environ.get("BOT_USERNAME", "")

# سر مسار الـ webhook (اختياري لكنه موصى به) — يُستخدم كـ secret_token عند setWebhook
WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "")

# سر يحمي مسار الكرون /api/cron/check-messages من الاستدعاء العشوائي
CRON_SECRET = os.environ.get("CRON_SECRET", "")

# ── قناة الاشتراك الإجباري والدعم ────────────────────────────────────
FORCE_SUB_CHANNEL = os.environ.get("FORCE_SUB_CHANNEL", "@MekoOnBsc")
FORCE_SUB_CHANNEL_URL = os.environ.get("FORCE_SUB_CHANNEL_URL", "https://t.me/MekoOnBsc")
SUPPORT_USERNAME = os.environ.get("SUPPORT_USERNAME", "@upportsmsbot")
SUPPORT_URL = os.environ.get("SUPPORT_URL", "https://t.me/upportsmsbot")

# ── سكرابر temp-number.com ───────────────────────────────────────────
BASE_URL = "https://temp-number.com"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)
HTTP_TIMEOUT = 15
REQUEST_DELAY = 0.6

# ── الجلسة والفحص ────────────────────────────────────────────────────
# ملاحظة مهمة: على Vercel لا يوجد job_queue يفحص كل 15 ثانية باستمرار.
# الفحص يتم عبر استدعاء خارجي (cron-job.org أو Vercel Cron على خطة Pro)
# لمسار /api/cron/check-messages كل دقيقة تقريباً. راجع DEPLOY.md.
POLL_INTERVAL_SEC = 60
SESSION_DURATION_SEC = 600           # مدة الرقم المجاني (10 دقائق)
PAID_SESSION_DURATION_SEC = 1800     # مدة الرقم المدفوع (30 دقيقة)
NUMBERS_PER_PAGE = 6
COUNTRIES_PER_PAGE = 18
USERS_PER_PAGE = 10

# ── الأرقام المدفوعة ─────────────────────────────────────────────────
PAID_NUMBER_PRICE = 0.50
PAID_SERVICES = {
    "telegram": "تيليجرام",
    "whatsapp": "واتساب",
}

# ── المحفظة والسحب ───────────────────────────────────────────────────
MIN_WITHDRAWAL = 6.0
WITHDRAW_METHODS = {
    "sham":    "شام كاش",
    "binance": "Binance ID",
    "usdt":    "USDT (TRC20)",
}
DEPOSIT_METHODS = {
    "sham":  "شام كاش",
    "usdt":  "USDT (TRC20)",
    "bep20": "USDT (BEP20)",
}

# عناوين الإيداع — يمكن تغييرها عبر متغيرات بيئة بدون تعديل الكود
DEPOSIT_ADDRESSES = {
    "sham":  os.environ.get("DEPOSIT_ADDR_SHAM", ""),
    "usdt":  os.environ.get("DEPOSIT_ADDR_USDT_TRC20", ""),
    "bep20": os.environ.get("DEPOSIT_ADDR_USDT_BEP20", ""),
}

DEPOSIT_NETWORKS = {
    "sham":  "شام كاش",
    "usdt":  "شبكة TRC20",
    "bep20": "شبكة BEP20",
}

# ── نظام الإحالات وعجلة الحظ ─────────────────────────────────────────
REFERRALS_PER_CARD = 3

WHEEL_PRIZES = [
    {"amount": 0.01, "weight": 55},
    {"amount": 0.25, "weight": 22},
    {"amount": 0.50, "weight": 12},
    {"amount": 0.75, "weight": 6},
    {"amount": 1.00, "weight": 4},
    {"amount": 2.00, "weight": 1},
]

# ── قاعدة البيانات ───────────────────────────────────────────────────
# يجب أن تكون قاعدة بيانات Postgres سحابية (Neon / Vercel Postgres / Supabase...)
# لأن نظام ملفات Vercel مؤقت ولا يصلح لـ SQLite.
DATABASE_URL = os.environ.get("DATABASE_URL", "")

# ── لوحة الإدارة ──────────────────────────────────────────────────────
ADMIN_PANEL_TOKEN = os.environ.get("ADMIN_PANEL_TOKEN", "")


def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS
