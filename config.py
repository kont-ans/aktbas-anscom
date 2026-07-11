import os

# ╔══════════════════════════════════════════════════════════════════╗
# ║                    إعدادات البوت                                ║
# ╚══════════════════════════════════════════════════════════════════╝

# ── بيانات البوت ─────────────────────────────────────────────────────
TOKEN = "8870889009:AAFJe_OFAdMM14U7kCH7UHEvz-AE0aBXFHs"
ADMIN_IDS = [8630643080]
BOT_USERNAME = ""  # سيُملأ تلقائياً عند بدء التشغيل

# ── قناة الاشتراك الإجباري والدعم ────────────────────────────────────
FORCE_SUB_CHANNEL = "@MekoOnBsc"
FORCE_SUB_CHANNEL_URL = "https://t.me/MekoOnBsc"
SUPPORT_USERNAME = "@upportsmsbot"
SUPPORT_URL = "https://t.me/upportsmsbot"

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
POLL_INTERVAL_SEC = 15
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

# عناوين الإيداع
DEPOSIT_ADDRESSES = {
    "sham":  "dd2449951603facf3eae5f5490b55133",
    "usdt":  "TBUd9kJWzuzSrf9BfDziJm3GjyS5yVWg5K",
    "bep20": "0xd76bd78cdec01b131f1c19edf38d0d31a6639607",
}

DEPOSIT_NETWORKS = {
    "sham":  "شام كاش",
    "usdt":  "شبكة TRC20",
    "bep20": "شبكة BEP20",
}

# ── نظام الإحالات وعجلة الحظ ─────────────────────────────────────────
REFERRALS_PER_CARD = 3   # كل 3 إحالات ناجحة = بطاقة عجلة

# الجوائز ونسب الحصول عليها (المجموع 100)
# الأصغر = نسبة أعلى
WHEEL_PRIZES = [
    {"amount": 0.01, "weight": 55},
    {"amount": 0.25, "weight": 22},
    {"amount": 0.50, "weight": 12},
    {"amount": 0.75, "weight": 6},
    {"amount": 1.00, "weight": 4},
    {"amount": 2.00, "weight": 1},
]

# ── قاعدة البيانات ───────────────────────────────────────────────────
_HERE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get("DB_PATH", os.path.join(_HERE, "temp_number_bot.sqlite3"))

# ── لوحة الإدارة الخارجية (v3) ───────────────────────────────────────
ADMIN_PANEL_TOKEN = os.environ.get("ADMIN_PANEL_TOKEN", "admin_panel_secret_v3_2025")
ADMIN_PANEL_PORT  = int(os.environ.get("ADMIN_PANEL_PORT", "8080"))


def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS
