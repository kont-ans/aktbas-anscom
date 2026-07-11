import sqlite3
from contextlib import contextmanager
from typing import Optional
from config import DB_PATH


@contextmanager
def _conn():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    try:
        yield con
        con.commit()
    finally:
        con.close()


def init_db():
    with _conn() as con:
        cur = con.cursor()

        cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                last_name TEXT,
                language_code TEXT,
                is_banned INTEGER DEFAULT 0,
                balance REAL DEFAULT 0,
                referrer_id INTEGER,
                referrals_count INTEGER DEFAULT 0,
                wheel_cards INTEGER DEFAULT 0,
                joined_channel INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_active TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS user_numbers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                phone TEXT NOT NULL,
                country_slug TEXT NOT NULL,
                country_name TEXT NOT NULL,
                kind TEXT DEFAULT 'free',
                started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                expires_at TIMESTAMP,
                is_active INTEGER DEFAULT 1,
                seen_messages TEXT DEFAULT ''
            )
        """)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_user_active ON user_numbers(user_id, is_active)")

        cur.execute("""
            CREATE TABLE IF NOT EXISTS referrals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                referrer_id INTEGER NOT NULL,
                referred_id INTEGER NOT NULL UNIQUE,
                counted INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS wallet_tx (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                amount REAL NOT NULL,
                kind TEXT NOT NULL,
                note TEXT,
                ref_id INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS paid_orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                service TEXT NOT NULL,
                price REAL NOT NULL,
                status TEXT DEFAULT 'pending',
                phone TEXT,
                country_slug TEXT,
                country_name TEXT,
                purchase_code TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                processed_at TIMESTAMP
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS deposit_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                method TEXT NOT NULL,
                amount REAL NOT NULL,
                tx_info TEXT,
                photo_file_id TEXT,
                rejection_reason TEXT,
                status TEXT DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                processed_at TIMESTAMP
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS withdraw_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                method TEXT NOT NULL,
                address TEXT NOT NULL,
                amount REAL NOT NULL,
                status TEXT DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                processed_at TIMESTAMP
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS admin_pending (
                admin_id INTEGER PRIMARY KEY,
                action TEXT NOT NULL,
                payload TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS force_sub_channels (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                channel_id TEXT NOT NULL UNIQUE,
                channel_url TEXT NOT NULL,
                channel_name TEXT NOT NULL DEFAULT '',
                added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS broadcast_admins (
                user_id INTEGER PRIMARY KEY,
                added_by INTEGER NOT NULL,
                note TEXT DEFAULT '',
                added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # ── v3: إعدادات البوت ──────────────────────────────────────────
        cur.execute("""
            CREATE TABLE IF NOT EXISTS bot_settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL DEFAULT '1',
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        # تهيئة القيم الافتراضية
        for k, v in [
            ("bot_enabled",          "1"),
            ("deposit_enabled",      "1"),
            ("paid_numbers_enabled", "1"),
        ]:
            cur.execute(
                "INSERT OR IGNORE INTO bot_settings (key, value) VALUES (?, ?)",
                (k, v)
            )

        # Lightweight migrations for older DBs
        cols = {r["name"] for r in cur.execute("PRAGMA table_info(users)")}
        for col, ddl in [
            ("last_name",       "ALTER TABLE users ADD COLUMN last_name TEXT"),
            ("language_code",   "ALTER TABLE users ADD COLUMN language_code TEXT"),
            ("is_banned",       "ALTER TABLE users ADD COLUMN is_banned INTEGER DEFAULT 0"),
            ("balance",         "ALTER TABLE users ADD COLUMN balance REAL DEFAULT 0"),
            ("referrer_id",     "ALTER TABLE users ADD COLUMN referrer_id INTEGER"),
            ("referrals_count", "ALTER TABLE users ADD COLUMN referrals_count INTEGER DEFAULT 0"),
            ("wheel_cards",     "ALTER TABLE users ADD COLUMN wheel_cards INTEGER DEFAULT 0"),
            ("joined_channel",  "ALTER TABLE users ADD COLUMN joined_channel INTEGER DEFAULT 0"),
            ("last_active",     "ALTER TABLE users ADD COLUMN last_active TIMESTAMP"),
        ]:
            if col not in cols:
                try: cur.execute(ddl)
                except sqlite3.OperationalError: pass

        un_cols = {r["name"] for r in cur.execute("PRAGMA table_info(user_numbers)")}
        if "kind" not in un_cols:
            try: cur.execute("ALTER TABLE user_numbers ADD COLUMN kind TEXT DEFAULT 'free'")
            except sqlite3.OperationalError: pass

        ap_cols = {r["name"] for r in cur.execute("PRAGMA table_info(admin_pending)")}
        if "payload" not in ap_cols:
            try: cur.execute("ALTER TABLE admin_pending ADD COLUMN payload TEXT")
            except sqlite3.OperationalError: pass

        po_cols = {r["name"] for r in cur.execute("PRAGMA table_info(paid_orders)")}
        if "purchase_code" not in po_cols:
            try: cur.execute("ALTER TABLE paid_orders ADD COLUMN purchase_code TEXT")
            except sqlite3.OperationalError: pass

        dr_cols = {r["name"] for r in cur.execute("PRAGMA table_info(deposit_requests)")}
        for dc, ddl in [
            ("photo_file_id", "ALTER TABLE deposit_requests ADD COLUMN photo_file_id TEXT"),
            ("rejection_reason", "ALTER TABLE deposit_requests ADD COLUMN rejection_reason TEXT"),
        ]:
            if dc not in dr_cols:
                try: cur.execute(ddl)
                except sqlite3.OperationalError: pass


# ╔══════════════════════════════════════════════════════════════════╗
# ║                      USERS                                      ║
# ╚══════════════════════════════════════════════════════════════════╝

def upsert_user(user_id: int, username: Optional[str], first_name: Optional[str],
                last_name: Optional[str] = None, language_code: Optional[str] = None):
    with _conn() as con:
        con.execute("""
            INSERT INTO users (user_id, username, first_name, last_name, language_code, last_active)
            VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(user_id) DO UPDATE SET
                username=excluded.username,
                first_name=excluded.first_name,
                last_name=excluded.last_name,
                language_code=excluded.language_code,
                last_active=CURRENT_TIMESTAMP
        """, (user_id, username, first_name, last_name, language_code))


def get_user(user_id: int):
    with _conn() as con:
        row = con.execute("SELECT * FROM users WHERE user_id=?", (user_id,)).fetchone()
        return dict(row) if row else None


def is_banned(user_id: int) -> bool:
    with _conn() as con:
        row = con.execute("SELECT is_banned FROM users WHERE user_id=?", (user_id,)).fetchone()
        return bool(row and row["is_banned"])


def set_ban(user_id: int, banned: bool):
    with _conn() as con:
        con.execute("UPDATE users SET is_banned=? WHERE user_id=?",
                    (1 if banned else 0, user_id))


def list_users(limit: int = 10, offset: int = 0) -> list[dict]:
    with _conn() as con:
        rows = con.execute(
            "SELECT * FROM users ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (limit, offset)
        ).fetchall()
        return [dict(r) for r in rows]


def all_user_ids(include_banned: bool = False) -> list[int]:
    with _conn() as con:
        if include_banned:
            rows = con.execute("SELECT user_id FROM users").fetchall()
        else:
            rows = con.execute("SELECT user_id FROM users WHERE is_banned=0").fetchall()
        return [r["user_id"] for r in rows]


def set_joined_channel(user_id: int, joined: bool):
    with _conn() as con:
        con.execute("UPDATE users SET joined_channel=? WHERE user_id=?",
                    (1 if joined else 0, user_id))


# ╔══════════════════════════════════════════════════════════════════╗
# ║                 BALANCE / WALLET                                ║
# ╚══════════════════════════════════════════════════════════════════╝

def get_balance(user_id: int) -> float:
    with _conn() as con:
        row = con.execute("SELECT balance FROM users WHERE user_id=?", (user_id,)).fetchone()
        return float(row["balance"]) if row else 0.0


def add_tx(user_id: int, amount: float, kind: str, note: str = "", ref_id: Optional[int] = None):
    """Atomically update balance and log a transaction."""
    with _conn() as con:
        con.execute("UPDATE users SET balance = COALESCE(balance, 0) + ? WHERE user_id = ?",
                    (amount, user_id))
        con.execute("""
            INSERT INTO wallet_tx (user_id, amount, kind, note, ref_id)
            VALUES (?, ?, ?, ?, ?)
        """, (user_id, amount, kind, note, ref_id))


def set_balance(user_id: int, new_balance: float, note: str = "admin_set"):
    with _conn() as con:
        cur = con.execute("SELECT balance FROM users WHERE user_id=?", (user_id,)).fetchone()
        old = float(cur["balance"]) if cur else 0.0
        diff = new_balance - old
        con.execute("UPDATE users SET balance=? WHERE user_id=?", (new_balance, user_id))
        con.execute("""
            INSERT INTO wallet_tx (user_id, amount, kind, note)
            VALUES (?, ?, 'admin_set', ?)
        """, (user_id, diff, note))


def list_user_tx(user_id: int, limit: int = 10) -> list[dict]:
    with _conn() as con:
        rows = con.execute("""
            SELECT * FROM wallet_tx WHERE user_id=?
            ORDER BY created_at DESC LIMIT ?
        """, (user_id, limit)).fetchall()
        return [dict(r) for r in rows]


# ╔══════════════════════════════════════════════════════════════════╗
# ║                    REFERRALS                                    ║
# ╚══════════════════════════════════════════════════════════════════╝

def set_referrer(user_id: int, referrer_id: int) -> bool:
    """Returns True if a new referral row was created."""
    if user_id == referrer_id:
        return False
    with _conn() as con:
        # Don't override existing referrer
        row = con.execute("SELECT referrer_id FROM users WHERE user_id=?", (user_id,)).fetchone()
        if row and row["referrer_id"]:
            return False
        con.execute("UPDATE users SET referrer_id=? WHERE user_id=?", (referrer_id, user_id))
        try:
            con.execute("""
                INSERT INTO referrals (referrer_id, referred_id, counted)
                VALUES (?, ?, 0)
            """, (referrer_id, user_id))
            return True
        except sqlite3.IntegrityError:
            return False


def credit_referral(referred_id: int) -> Optional[dict]:
    """
    Mark referral as counted (when the user joins the channel).
    Returns dict with referrer_id and 'awarded_card' bool, or None.
    """
    with _conn() as con:
        row = con.execute("""
            SELECT * FROM referrals WHERE referred_id=? AND counted=0
        """, (referred_id,)).fetchone()
        if not row:
            return None
        ref = row["referrer_id"]
        con.execute("UPDATE referrals SET counted=1 WHERE id=?", (row["id"],))
        con.execute(
            "UPDATE users SET referrals_count = COALESCE(referrals_count,0) + 1 WHERE user_id=?",
            (ref,)
        )
        # Check if a new card should be awarded
        from config import REFERRALS_PER_CARD
        cur = con.execute("SELECT referrals_count FROM users WHERE user_id=?", (ref,)).fetchone()
        count = int(cur["referrals_count"]) if cur else 0
        awarded = (count > 0 and count % REFERRALS_PER_CARD == 0)
        if awarded:
            con.execute(
                "UPDATE users SET wheel_cards = COALESCE(wheel_cards,0) + 1 WHERE user_id=?",
                (ref,)
            )
        return {"referrer_id": ref, "awarded_card": awarded, "total": count}


def use_wheel_card(user_id: int) -> bool:
    with _conn() as con:
        row = con.execute("SELECT wheel_cards FROM users WHERE user_id=?", (user_id,)).fetchone()
        if not row or int(row["wheel_cards"] or 0) <= 0:
            return False
        con.execute("UPDATE users SET wheel_cards = wheel_cards - 1 WHERE user_id=?", (user_id,))
        return True


# ╔══════════════════════════════════════════════════════════════════╗
# ║                    NUMBERS                                      ║
# ╚══════════════════════════════════════════════════════════════════╝

def deactivate_all_for_user(user_id: int):
    with _conn() as con:
        con.execute(
            "UPDATE user_numbers SET is_active=0 WHERE user_id=? AND is_active=1",
            (user_id,)
        )


def set_active_number(user_id: int, phone: str, country_slug: str,
                      country_name: str, expires_at, seen_csv: str = "",
                      kind: str = "free") -> int:
    deactivate_all_for_user(user_id)
    with _conn() as con:
        cur = con.execute("""
            INSERT INTO user_numbers
                (user_id, phone, country_slug, country_name, expires_at, seen_messages, kind)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (user_id, phone, country_slug, country_name, expires_at, seen_csv, kind))
        return cur.lastrowid


def get_active_number(user_id: int):
    with _conn() as con:
        row = con.execute("""
            SELECT * FROM user_numbers
            WHERE user_id=? AND is_active=1
            ORDER BY started_at DESC LIMIT 1
        """, (user_id,)).fetchone()
        return dict(row) if row else None


def stop_active_number(user_id: int):
    with _conn() as con:
        con.execute(
            "UPDATE user_numbers SET is_active=0 WHERE user_id=? AND is_active=1",
            (user_id,)
        )


def update_seen_messages(record_id: int, seen_csv: str):
    with _conn() as con:
        con.execute(
            "UPDATE user_numbers SET seen_messages=? WHERE id=?",
            (seen_csv, record_id)
        )


# ╔══════════════════════════════════════════════════════════════════╗
# ║                    PAID ORDERS                                  ║
# ╚══════════════════════════════════════════════════════════════════╝

def create_paid_order(user_id: int, service: str, price: float) -> int:
    with _conn() as con:
        cur = con.execute("""
            INSERT INTO paid_orders (user_id, service, price, status)
            VALUES (?, ?, ?, 'pending')
        """, (user_id, service, price))
        return cur.lastrowid


def get_paid_order(order_id: int):
    with _conn() as con:
        row = con.execute("SELECT * FROM paid_orders WHERE id=?", (order_id,)).fetchone()
        return dict(row) if row else None


def update_paid_order(order_id: int, **fields):
    if not fields:
        return
    cols = ", ".join(f"{k}=?" for k in fields.keys())
    with _conn() as con:
        con.execute(
            f"UPDATE paid_orders SET {cols}, processed_at=CURRENT_TIMESTAMP WHERE id=?",
            (*fields.values(), order_id)
        )


def list_paid_orders(status: Optional[str] = None, limit: int = 20) -> list[dict]:
    with _conn() as con:
        if status:
            rows = con.execute("""
                SELECT * FROM paid_orders WHERE status=?
                ORDER BY created_at DESC LIMIT ?
            """, (status, limit)).fetchall()
        else:
            rows = con.execute("""
                SELECT * FROM paid_orders ORDER BY created_at DESC LIMIT ?
            """, (limit,)).fetchall()
        return [dict(r) for r in rows]


# ╔══════════════════════════════════════════════════════════════════╗
# ║                  DEPOSIT REQUESTS                               ║
# ╚══════════════════════════════════════════════════════════════════╝

def create_deposit_request(user_id: int, method: str, amount: float, tx_info: str) -> int:
    with _conn() as con:
        cur = con.execute("""
            INSERT INTO deposit_requests (user_id, method, amount, tx_info, status)
            VALUES (?, ?, ?, ?, 'pending')
        """, (user_id, method, amount, tx_info))
        return cur.lastrowid


def get_deposit(req_id: int):
    with _conn() as con:
        row = con.execute("SELECT * FROM deposit_requests WHERE id=?", (req_id,)).fetchone()
        return dict(row) if row else None


def update_deposit(req_id: int, **fields):
    if not fields: return
    cols = ", ".join(f"{k}=?" for k in fields.keys())
    with _conn() as con:
        con.execute(
            f"UPDATE deposit_requests SET {cols}, processed_at=CURRENT_TIMESTAMP WHERE id=?",
            (*fields.values(), req_id)
        )


def list_deposits(status: Optional[str] = None, limit: int = 20) -> list[dict]:
    with _conn() as con:
        if status:
            rows = con.execute("""
                SELECT * FROM deposit_requests WHERE status=?
                ORDER BY created_at DESC LIMIT ?
            """, (status, limit)).fetchall()
        else:
            rows = con.execute("""
                SELECT * FROM deposit_requests ORDER BY created_at DESC LIMIT ?
            """, (limit,)).fetchall()
        return [dict(r) for r in rows]


# ╔══════════════════════════════════════════════════════════════════╗
# ║                 WITHDRAW REQUESTS                               ║
# ╚══════════════════════════════════════════════════════════════════╝

def create_withdraw_request(user_id: int, method: str, address: str, amount: float) -> int:
    with _conn() as con:
        cur = con.execute("""
            INSERT INTO withdraw_requests (user_id, method, address, amount, status)
            VALUES (?, ?, ?, ?, 'pending')
        """, (user_id, method, address, amount))
        return cur.lastrowid


def get_withdraw(req_id: int):
    with _conn() as con:
        row = con.execute("SELECT * FROM withdraw_requests WHERE id=?", (req_id,)).fetchone()
        return dict(row) if row else None


def update_withdraw(req_id: int, **fields):
    if not fields: return
    cols = ", ".join(f"{k}=?" for k in fields.keys())
    with _conn() as con:
        con.execute(
            f"UPDATE withdraw_requests SET {cols}, processed_at=CURRENT_TIMESTAMP WHERE id=?",
            (*fields.values(), req_id)
        )


def list_withdrawals(status: Optional[str] = None, limit: int = 20) -> list[dict]:
    with _conn() as con:
        if status:
            rows = con.execute("""
                SELECT * FROM withdraw_requests WHERE status=?
                ORDER BY created_at DESC LIMIT ?
            """, (status, limit)).fetchall()
        else:
            rows = con.execute("""
                SELECT * FROM withdraw_requests ORDER BY created_at DESC LIMIT ?
            """, (limit,)).fetchall()
        return [dict(r) for r in rows]


# ╔══════════════════════════════════════════════════════════════════╗
# ║                 ADMIN PENDING (FREE-TEXT INPUT)                 ║
# ╚══════════════════════════════════════════════════════════════════╝

def set_admin_pending(admin_id: int, action: str, payload: str = ""):
    with _conn() as con:
        con.execute("""
            INSERT INTO admin_pending (admin_id, action, payload)
            VALUES (?, ?, ?)
            ON CONFLICT(admin_id) DO UPDATE SET
                action=excluded.action,
                payload=excluded.payload,
                created_at=CURRENT_TIMESTAMP
        """, (admin_id, action, payload))


def get_admin_pending(admin_id: int):
    with _conn() as con:
        row = con.execute(
            "SELECT * FROM admin_pending WHERE admin_id=?", (admin_id,)
        ).fetchone()
        return dict(row) if row else None


def clear_admin_pending(admin_id: int):
    with _conn() as con:
        con.execute("DELETE FROM admin_pending WHERE admin_id=?", (admin_id,))


# ── User pending (same table, keyed by user_id as admin_id) ─────────

def set_user_pending(user_id: int, action: str, payload: str = ""):
    set_admin_pending(user_id, action, payload)


def get_user_pending(user_id: int):
    return get_admin_pending(user_id)


def clear_user_pending(user_id: int):
    clear_admin_pending(user_id)


# ╔══════════════════════════════════════════════════════════════════╗
# ║                    STATISTICS                                   ║
# ╚══════════════════════════════════════════════════════════════════╝

def count_users() -> int:
    with _conn() as con:
        return con.execute("SELECT COUNT(*) FROM users").fetchone()[0]


def count_banned() -> int:
    with _conn() as con:
        return con.execute("SELECT COUNT(*) FROM users WHERE is_banned=1").fetchone()[0]


def count_active_sessions() -> int:
    with _conn() as con:
        return con.execute("SELECT COUNT(*) FROM user_numbers WHERE is_active=1").fetchone()[0]


def count_total_sessions() -> int:
    with _conn() as con:
        return con.execute("SELECT COUNT(*) FROM user_numbers").fetchone()[0]


def total_balance() -> float:
    with _conn() as con:
        row = con.execute("SELECT COALESCE(SUM(balance),0) FROM users").fetchone()
        return float(row[0])


def count_pending(table: str) -> int:
    allowed = {"paid_orders", "deposit_requests", "withdraw_requests"}
    if table not in allowed:
        return 0
    with _conn() as con:
        return con.execute(f"SELECT COUNT(*) FROM {table} WHERE status='pending'").fetchone()[0]


# ╔══════════════════════════════════════════════════════════════════╗
# ║                 FORCE SUB CHANNELS                              ║
# ╚══════════════════════════════════════════════════════════════════╝

def add_force_channel(channel_id: str, channel_url: str, channel_name: str = "") -> bool:
    try:
        with _conn() as con:
            con.execute("""
                INSERT INTO force_sub_channels (channel_id, channel_url, channel_name)
                VALUES (?, ?, ?)
            """, (channel_id, channel_url, channel_name))
        return True
    except sqlite3.IntegrityError:
        return False


def remove_force_channel(row_id: int):
    with _conn() as con:
        con.execute("DELETE FROM force_sub_channels WHERE id=?", (row_id,))


def list_force_channels() -> list[dict]:
    with _conn() as con:
        rows = con.execute(
            "SELECT * FROM force_sub_channels ORDER BY added_at"
        ).fetchall()
        return [dict(r) for r in rows]


def get_force_channel(row_id: int):
    with _conn() as con:
        row = con.execute(
            "SELECT * FROM force_sub_channels WHERE id=?", (row_id,)
        ).fetchone()
        return dict(row) if row else None


# ╔══════════════════════════════════════════════════════════════════╗
# ║                 BROADCAST ADMINS                                ║
# ╚══════════════════════════════════════════════════════════════════╝

def add_broadcast_admin(user_id: int, added_by: int, note: str = "") -> bool:
    try:
        with _conn() as con:
            con.execute("""
                INSERT INTO broadcast_admins (user_id, added_by, note)
                VALUES (?, ?, ?)
            """, (user_id, added_by, note))
        return True
    except sqlite3.IntegrityError:
        return False


def remove_broadcast_admin(user_id: int):
    with _conn() as con:
        con.execute("DELETE FROM broadcast_admins WHERE user_id=?", (user_id,))


def is_broadcast_admin(user_id: int) -> bool:
    with _conn() as con:
        row = con.execute(
            "SELECT 1 FROM broadcast_admins WHERE user_id=?", (user_id,)
        ).fetchone()
        return bool(row)


def list_broadcast_admins() -> list[dict]:
    with _conn() as con:
        rows = con.execute(
            "SELECT * FROM broadcast_admins ORDER BY added_at"
        ).fetchall()
        return [dict(r) for r in rows]


# ╔══════════════════════════════════════════════════════════════════╗
# ║              v3: BOT SETTINGS (إعدادات البوت)                   ║
# ╚══════════════════════════════════════════════════════════════════╝

def get_setting(key: str, default: str = "1") -> str:
    """قراءة إعداد بوت."""
    with _conn() as con:
        row = con.execute(
            "SELECT value FROM bot_settings WHERE key=?", (key,)
        ).fetchone()
        return row["value"] if row else default


def set_setting(key: str, value: str):
    """تعيين إعداد بوت."""
    with _conn() as con:
        con.execute("""
            INSERT INTO bot_settings (key, value, updated_at)
            VALUES (?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(key) DO UPDATE SET
                value=excluded.value,
                updated_at=CURRENT_TIMESTAMP
        """, (key, value))


def get_all_settings() -> dict:
    """إرجاع جميع الإعدادات كـ dict."""
    with _conn() as con:
        rows = con.execute("SELECT key, value FROM bot_settings").fetchall()
        return {r["key"]: r["value"] for r in rows}
