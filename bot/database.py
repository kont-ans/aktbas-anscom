"""
PostgreSQL port of the original SQLite database module.
Uses psycopg (psycopg3) + psycopg_pool for connection pooling.
Connection pool is created lazily on first use.
"""

import psycopg
import psycopg_pool
from psycopg.rows import dict_row
from psycopg import errors as pg_errors
from contextlib import contextmanager
from typing import Optional

from .config import DATABASE_URL, REFERRALS_PER_CARD

# ---------------------------------------------------------------------------
# Connection pool — created lazily on first _conn() call
# ---------------------------------------------------------------------------
_pool: Optional[psycopg_pool.ConnectionPool] = None

_KNOWN_PAID_ORDER_COLS = {
    "user_id", "service", "price", "status", "phone",
    "country_slug", "country_name", "purchase_code", "processed_at",
}
_KNOWN_DEPOSIT_COLS = {
    "user_id", "method", "amount", "tx_info", "photo_file_id",
    "rejection_reason", "status", "processed_at",
}
_KNOWN_WITHDRAW_COLS = {
    "user_id", "method", "address", "amount", "status", "processed_at",
}


def _get_pool() -> psycopg_pool.ConnectionPool:
    global _pool
    if _pool is None:
        _pool = psycopg_pool.ConnectionPool(
            DATABASE_URL,
            kwargs={"row_factory": dict_row},
            min_size=1,
            max_size=10,
            open=True,
        )
    return _pool


@contextmanager
def _conn():
    pool = _get_pool()
    with pool.connection() as conn:
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise


# ╔══════════════════════════════════════════════════════════════════╗
# ║                      INIT DATABASE                             ║
# ╚══════════════════════════════════════════════════════════════════╝

def init_db():
    with _conn() as con:
        cur = con.cursor()

        cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id BIGINT PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                last_name TEXT,
                language_code TEXT,
                is_banned INTEGER DEFAULT 0,
                balance REAL DEFAULT 0,
                referrer_id BIGINT,
                referrals_count INTEGER DEFAULT 0,
                wheel_cards INTEGER DEFAULT 0,
                joined_channel INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT now(),
                last_active TIMESTAMP DEFAULT now()
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS user_numbers (
                id SERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL,
                phone TEXT NOT NULL,
                country_slug TEXT NOT NULL,
                country_name TEXT NOT NULL,
                kind TEXT DEFAULT 'free',
                started_at TIMESTAMP DEFAULT now(),
                expires_at TIMESTAMP,
                is_active INTEGER DEFAULT 1,
                seen_messages TEXT DEFAULT ''
            )
        """)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_user_active ON user_numbers(user_id, is_active)")

        cur.execute("""
            CREATE TABLE IF NOT EXISTS referrals (
                id SERIAL PRIMARY KEY,
                referrer_id BIGINT NOT NULL,
                referred_id BIGINT NOT NULL UNIQUE,
                counted INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT now()
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS wallet_tx (
                id SERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL,
                amount REAL NOT NULL,
                kind TEXT NOT NULL,
                note TEXT,
                ref_id BIGINT,
                created_at TIMESTAMP DEFAULT now()
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS paid_orders (
                id SERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL,
                service TEXT NOT NULL,
                price REAL NOT NULL,
                status TEXT DEFAULT 'pending',
                phone TEXT,
                country_slug TEXT,
                country_name TEXT,
                purchase_code TEXT,
                created_at TIMESTAMP DEFAULT now(),
                processed_at TIMESTAMP
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS deposit_requests (
                id SERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL,
                method TEXT NOT NULL,
                amount REAL NOT NULL,
                tx_info TEXT,
                photo_file_id TEXT,
                rejection_reason TEXT,
                status TEXT DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT now(),
                processed_at TIMESTAMP
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS withdraw_requests (
                id SERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL,
                method TEXT NOT NULL,
                address TEXT NOT NULL,
                amount REAL NOT NULL,
                status TEXT DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT now(),
                processed_at TIMESTAMP
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS admin_pending (
                admin_id BIGINT PRIMARY KEY,
                action TEXT NOT NULL,
                payload TEXT,
                created_at TIMESTAMP DEFAULT now()
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS force_sub_channels (
                id SERIAL PRIMARY KEY,
                channel_id TEXT NOT NULL UNIQUE,
                channel_url TEXT NOT NULL,
                channel_name TEXT NOT NULL DEFAULT '',
                added_at TIMESTAMP DEFAULT now()
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS broadcast_admins (
                user_id BIGINT PRIMARY KEY,
                added_by BIGINT NOT NULL,
                note TEXT DEFAULT '',
                added_at TIMESTAMP DEFAULT now()
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS bot_settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL DEFAULT '1',
                updated_at TIMESTAMP DEFAULT now()
            )
        """)

        # Initialize default settings
        for k, v in [
            ("bot_enabled",          "1"),
            ("deposit_enabled",      "1"),
            ("paid_numbers_enabled", "1"),
        ]:
            cur.execute(
                "INSERT INTO bot_settings (key, value) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                (k, v)
            )

        # New tables for Vercel port
        cur.execute("""
            CREATE TABLE IF NOT EXISTS admin_otp (
                admin_id BIGINT PRIMARY KEY,
                code TEXT NOT NULL,
                expires_at TIMESTAMPTZ NOT NULL
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS admin_sessions (
                token TEXT PRIMARY KEY,
                expires_at TIMESTAMPTZ NOT NULL
            )
        """)


# ╔══════════════════════════════════════════════════════════════════╗
# ║                      USERS                                      ║
# ╚══════════════════════════════════════════════════════════════════╝

def upsert_user(user_id: int, username: Optional[str], first_name: Optional[str],
                last_name: Optional[str] = None, language_code: Optional[str] = None):
    with _conn() as con:
        con.execute("""
            INSERT INTO users (user_id, username, first_name, last_name, language_code, last_active)
            VALUES (%s, %s, %s, %s, %s, now())
            ON CONFLICT(user_id) DO UPDATE SET
                username=excluded.username,
                first_name=excluded.first_name,
                last_name=excluded.last_name,
                language_code=excluded.language_code,
                last_active=now()
        """, (user_id, username, first_name, last_name, language_code))


def get_user(user_id: int):
    with _conn() as con:
        row = con.execute("SELECT * FROM users WHERE user_id=%s", (user_id,)).fetchone()
        return dict(row) if row else None


def is_banned(user_id: int) -> bool:
    with _conn() as con:
        row = con.execute("SELECT is_banned FROM users WHERE user_id=%s", (user_id,)).fetchone()
        return bool(row and row["is_banned"])


def set_ban(user_id: int, banned: bool):
    with _conn() as con:
        con.execute("UPDATE users SET is_banned=%s WHERE user_id=%s",
                    (1 if banned else 0, user_id))


def list_users(limit: int = 10, offset: int = 0) -> list:
    with _conn() as con:
        rows = con.execute(
            "SELECT * FROM users ORDER BY created_at DESC LIMIT %s OFFSET %s",
            (limit, offset)
        ).fetchall()
        return [dict(r) for r in rows]


def all_user_ids(include_banned: bool = False) -> list:
    with _conn() as con:
        if include_banned:
            rows = con.execute("SELECT user_id FROM users").fetchall()
        else:
            rows = con.execute("SELECT user_id FROM users WHERE is_banned=0").fetchall()
        return [r["user_id"] for r in rows]


def set_joined_channel(user_id: int, joined: bool):
    with _conn() as con:
        con.execute("UPDATE users SET joined_channel=%s WHERE user_id=%s",
                    (1 if joined else 0, user_id))


# ╔══════════════════════════════════════════════════════════════════╗
# ║                 BALANCE / WALLET                                ║
# ╚══════════════════════════════════════════════════════════════════╝

def get_balance(user_id: int) -> float:
    with _conn() as con:
        row = con.execute("SELECT balance FROM users WHERE user_id=%s", (user_id,)).fetchone()
        return float(row["balance"]) if row else 0.0


def add_tx(user_id: int, amount: float, kind: str, note: str = "", ref_id: Optional[int] = None):
    """Atomically update balance and log a transaction."""
    with _conn() as con:
        con.execute("UPDATE users SET balance = COALESCE(balance, 0) + %s WHERE user_id = %s",
                    (amount, user_id))
        con.execute("""
            INSERT INTO wallet_tx (user_id, amount, kind, note, ref_id)
            VALUES (%s, %s, %s, %s, %s)
        """, (user_id, amount, kind, note, ref_id))


def set_balance(user_id: int, new_balance: float, note: str = "admin_set"):
    with _conn() as con:
        cur = con.execute("SELECT balance FROM users WHERE user_id=%s", (user_id,)).fetchone()
        old = float(cur["balance"]) if cur else 0.0
        diff = new_balance - old
        con.execute("UPDATE users SET balance=%s WHERE user_id=%s", (new_balance, user_id))
        con.execute("""
            INSERT INTO wallet_tx (user_id, amount, kind, note)
            VALUES (%s, %s, 'admin_set', %s)
        """, (user_id, diff, note))


def list_user_tx(user_id: int, limit: int = 10) -> list:
    with _conn() as con:
        rows = con.execute("""
            SELECT * FROM wallet_tx WHERE user_id=%s
            ORDER BY created_at DESC LIMIT %s
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
        row = con.execute("SELECT referrer_id FROM users WHERE user_id=%s", (user_id,)).fetchone()
        if row and row["referrer_id"]:
            return False
        con.execute("UPDATE users SET referrer_id=%s WHERE user_id=%s", (referrer_id, user_id))
        try:
            con.execute("""
                INSERT INTO referrals (referrer_id, referred_id, counted)
                VALUES (%s, %s, 0)
            """, (referrer_id, user_id))
            return True
        except pg_errors.UniqueViolation:
            con.rollback()
            return False


def credit_referral(referred_id: int) -> Optional[dict]:
    """
    Mark referral as counted (when the user joins the channel).
    Returns dict with referrer_id and 'awarded_card' bool, or None.
    """
    with _conn() as con:
        row = con.execute("""
            SELECT * FROM referrals WHERE referred_id=%s AND counted=0
        """, (referred_id,)).fetchone()
        if not row:
            return None
        ref = row["referrer_id"]
        con.execute("UPDATE referrals SET counted=1 WHERE id=%s", (row["id"],))
        con.execute(
            "UPDATE users SET referrals_count = COALESCE(referrals_count,0) + 1 WHERE user_id=%s",
            (ref,)
        )
        cur = con.execute("SELECT referrals_count FROM users WHERE user_id=%s", (ref,)).fetchone()
        count = int(cur["referrals_count"]) if cur else 0
        awarded = (count > 0 and count % REFERRALS_PER_CARD == 0)
        if awarded:
            con.execute(
                "UPDATE users SET wheel_cards = COALESCE(wheel_cards,0) + 1 WHERE user_id=%s",
                (ref,)
            )
        return {"referrer_id": ref, "awarded_card": awarded, "total": count}


def use_wheel_card(user_id: int) -> bool:
    with _conn() as con:
        row = con.execute("SELECT wheel_cards FROM users WHERE user_id=%s", (user_id,)).fetchone()
        if not row or int(row["wheel_cards"] or 0) <= 0:
            return False
        con.execute("UPDATE users SET wheel_cards = wheel_cards - 1 WHERE user_id=%s", (user_id,))
        return True


# ╔══════════════════════════════════════════════════════════════════╗
# ║                    NUMBERS                                      ║
# ╚══════════════════════════════════════════════════════════════════╝

def deactivate_all_for_user(user_id: int):
    with _conn() as con:
        con.execute(
            "UPDATE user_numbers SET is_active=0 WHERE user_id=%s AND is_active=1",
            (user_id,)
        )


def set_active_number(user_id: int, phone: str, country_slug: str,
                      country_name: str, expires_at, seen_csv: str = "",
                      kind: str = "free") -> int:
    deactivate_all_for_user(user_id)
    with _conn() as con:
        row = con.execute("""
            INSERT INTO user_numbers
                (user_id, phone, country_slug, country_name, expires_at, seen_messages, kind)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        """, (user_id, phone, country_slug, country_name, expires_at, seen_csv, kind)).fetchone()
        return row["id"]


def get_active_number(user_id: int):
    with _conn() as con:
        row = con.execute("""
            SELECT * FROM user_numbers
            WHERE user_id=%s AND is_active=1
            ORDER BY started_at DESC LIMIT 1
        """, (user_id,)).fetchone()
        return dict(row) if row else None


def stop_active_number(user_id: int):
    with _conn() as con:
        con.execute(
            "UPDATE user_numbers SET is_active=0 WHERE user_id=%s AND is_active=1",
            (user_id,)
        )


def update_seen_messages(record_id: int, seen_csv: str):
    with _conn() as con:
        con.execute(
            "UPDATE user_numbers SET seen_messages=%s WHERE id=%s",
            (seen_csv, record_id)
        )


def list_active_numbers() -> list:
    """Return ALL rows from user_numbers where is_active=1, across every user, ordered by started_at."""
    with _conn() as con:
        rows = con.execute("""
            SELECT * FROM user_numbers WHERE is_active=1 ORDER BY started_at
        """).fetchall()
        return [dict(r) for r in rows]


# ╔══════════════════════════════════════════════════════════════════╗
# ║                    PAID ORDERS                                  ║
# ╚══════════════════════════════════════════════════════════════════╝

def create_paid_order(user_id: int, service: str, price: float) -> int:
    with _conn() as con:
        row = con.execute("""
            INSERT INTO paid_orders (user_id, service, price, status)
            VALUES (%s, %s, %s, 'pending')
            RETURNING id
        """, (user_id, service, price)).fetchone()
        return row["id"]


def get_paid_order(order_id: int):
    with _conn() as con:
        row = con.execute("SELECT * FROM paid_orders WHERE id=%s", (order_id,)).fetchone()
        return dict(row) if row else None


def update_paid_order(order_id: int, **fields):
    if not fields:
        return
    # Validate column names against whitelist to prevent SQL injection
    invalid = set(fields.keys()) - _KNOWN_PAID_ORDER_COLS
    if invalid:
        raise ValueError(f"Unknown paid_orders columns: {invalid}")
    cols = ", ".join(f"{k}=%s" for k in fields.keys())
    with _conn() as con:
        con.execute(
            f"UPDATE paid_orders SET {cols}, processed_at=now() WHERE id=%s",
            (*fields.values(), order_id)
        )


def list_paid_orders(status: Optional[str] = None, limit: int = 20) -> list:
    with _conn() as con:
        if status:
            rows = con.execute("""
                SELECT * FROM paid_orders WHERE status=%s
                ORDER BY created_at DESC LIMIT %s
            """, (status, limit)).fetchall()
        else:
            rows = con.execute("""
                SELECT * FROM paid_orders ORDER BY created_at DESC LIMIT %s
            """, (limit,)).fetchall()
        return [dict(r) for r in rows]


# ╔══════════════════════════════════════════════════════════════════╗
# ║                  DEPOSIT REQUESTS                               ║
# ╚══════════════════════════════════════════════════════════════════╝

def create_deposit_request(user_id: int, method: str, amount: float, tx_info: str) -> int:
    with _conn() as con:
        row = con.execute("""
            INSERT INTO deposit_requests (user_id, method, amount, tx_info, status)
            VALUES (%s, %s, %s, %s, 'pending')
            RETURNING id
        """, (user_id, method, amount, tx_info)).fetchone()
        return row["id"]


def get_deposit(req_id: int):
    with _conn() as con:
        row = con.execute("SELECT * FROM deposit_requests WHERE id=%s", (req_id,)).fetchone()
        return dict(row) if row else None


def update_deposit(req_id: int, **fields):
    if not fields:
        return
    invalid = set(fields.keys()) - _KNOWN_DEPOSIT_COLS
    if invalid:
        raise ValueError(f"Unknown deposit_requests columns: {invalid}")
    cols = ", ".join(f"{k}=%s" for k in fields.keys())
    with _conn() as con:
        con.execute(
            f"UPDATE deposit_requests SET {cols}, processed_at=now() WHERE id=%s",
            (*fields.values(), req_id)
        )


def list_deposits(status: Optional[str] = None, limit: int = 20) -> list:
    with _conn() as con:
        if status:
            rows = con.execute("""
                SELECT * FROM deposit_requests WHERE status=%s
                ORDER BY created_at DESC LIMIT %s
            """, (status, limit)).fetchall()
        else:
            rows = con.execute("""
                SELECT * FROM deposit_requests ORDER BY created_at DESC LIMIT %s
            """, (limit,)).fetchall()
        return [dict(r) for r in rows]


# ╔══════════════════════════════════════════════════════════════════╗
# ║                 WITHDRAW REQUESTS                               ║
# ╚══════════════════════════════════════════════════════════════════╝

def create_withdraw_request(user_id: int, method: str, address: str, amount: float) -> int:
    with _conn() as con:
        row = con.execute("""
            INSERT INTO withdraw_requests (user_id, method, address, amount, status)
            VALUES (%s, %s, %s, %s, 'pending')
            RETURNING id
        """, (user_id, method, address, amount)).fetchone()
        return row["id"]


def get_withdraw(req_id: int):
    with _conn() as con:
        row = con.execute("SELECT * FROM withdraw_requests WHERE id=%s", (req_id,)).fetchone()
        return dict(row) if row else None


def update_withdraw(req_id: int, **fields):
    if not fields:
        return
    invalid = set(fields.keys()) - _KNOWN_WITHDRAW_COLS
    if invalid:
        raise ValueError(f"Unknown withdraw_requests columns: {invalid}")
    cols = ", ".join(f"{k}=%s" for k in fields.keys())
    with _conn() as con:
        con.execute(
            f"UPDATE withdraw_requests SET {cols}, processed_at=now() WHERE id=%s",
            (*fields.values(), req_id)
        )


def list_withdrawals(status: Optional[str] = None, limit: int = 20) -> list:
    with _conn() as con:
        if status:
            rows = con.execute("""
                SELECT * FROM withdraw_requests WHERE status=%s
                ORDER BY created_at DESC LIMIT %s
            """, (status, limit)).fetchall()
        else:
            rows = con.execute("""
                SELECT * FROM withdraw_requests ORDER BY created_at DESC LIMIT %s
            """, (limit,)).fetchall()
        return [dict(r) for r in rows]


# ╔══════════════════════════════════════════════════════════════════╗
# ║                 ADMIN PENDING (FREE-TEXT INPUT)                 ║
# ╚══════════════════════════════════════════════════════════════════╝

def set_admin_pending(admin_id: int, action: str, payload: str = ""):
    with _conn() as con:
        con.execute("""
            INSERT INTO admin_pending (admin_id, action, payload, created_at)
            VALUES (%s, %s, %s, now())
            ON CONFLICT(admin_id) DO UPDATE SET
                action=excluded.action,
                payload=excluded.payload,
                created_at=now()
        """, (admin_id, action, payload))


def get_admin_pending(admin_id: int):
    with _conn() as con:
        row = con.execute(
            "SELECT * FROM admin_pending WHERE admin_id=%s", (admin_id,)
        ).fetchone()
        return dict(row) if row else None


def clear_admin_pending(admin_id: int):
    with _conn() as con:
        con.execute("DELETE FROM admin_pending WHERE admin_id=%s", (admin_id,))


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
        row = con.execute("SELECT COUNT(*) AS cnt FROM users").fetchone()
        return int(row["cnt"])


def count_banned() -> int:
    with _conn() as con:
        row = con.execute("SELECT COUNT(*) AS cnt FROM users WHERE is_banned=1").fetchone()
        return int(row["cnt"])


def count_active_sessions() -> int:
    with _conn() as con:
        row = con.execute("SELECT COUNT(*) AS cnt FROM user_numbers WHERE is_active=1").fetchone()
        return int(row["cnt"])


def count_total_sessions() -> int:
    with _conn() as con:
        row = con.execute("SELECT COUNT(*) AS cnt FROM user_numbers").fetchone()
        return int(row["cnt"])


def total_balance() -> float:
    with _conn() as con:
        row = con.execute("SELECT COALESCE(SUM(balance),0) AS s FROM users").fetchone()
        return float(row["s"])


def count_pending(table: str) -> int:
    allowed = {"paid_orders", "deposit_requests", "withdraw_requests"}
    if table not in allowed:
        return 0
    with _conn() as con:
        row = con.execute(
            f"SELECT COUNT(*) AS cnt FROM {table} WHERE status='pending'"
        ).fetchone()
        return int(row["cnt"])


# ╔══════════════════════════════════════════════════════════════════╗
# ║                 FORCE SUB CHANNELS                              ║
# ╚══════════════════════════════════════════════════════════════════╝

def add_force_channel(channel_id: str, channel_url: str, channel_name: str = "") -> bool:
    try:
        with _conn() as con:
            con.execute("""
                INSERT INTO force_sub_channels (channel_id, channel_url, channel_name)
                VALUES (%s, %s, %s)
            """, (channel_id, channel_url, channel_name))
        return True
    except pg_errors.UniqueViolation:
        return False


def remove_force_channel(row_id: int):
    with _conn() as con:
        con.execute("DELETE FROM force_sub_channels WHERE id=%s", (row_id,))


def list_force_channels() -> list:
    with _conn() as con:
        rows = con.execute(
            "SELECT * FROM force_sub_channels ORDER BY added_at"
        ).fetchall()
        return [dict(r) for r in rows]


def get_force_channel(row_id: int):
    with _conn() as con:
        row = con.execute(
            "SELECT * FROM force_sub_channels WHERE id=%s", (row_id,)
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
                VALUES (%s, %s, %s)
            """, (user_id, added_by, note))
        return True
    except pg_errors.UniqueViolation:
        return False


def remove_broadcast_admin(user_id: int):
    with _conn() as con:
        con.execute("DELETE FROM broadcast_admins WHERE user_id=%s", (user_id,))


def is_broadcast_admin(user_id: int) -> bool:
    with _conn() as con:
        row = con.execute(
            "SELECT 1 AS exists FROM broadcast_admins WHERE user_id=%s", (user_id,)
        ).fetchone()
        return bool(row)


def list_broadcast_admins() -> list:
    with _conn() as con:
        rows = con.execute(
            "SELECT * FROM broadcast_admins ORDER BY added_at"
        ).fetchall()
        return [dict(r) for r in rows]


# ╔══════════════════════════════════════════════════════════════════╗
# ║              BOT SETTINGS                                       ║
# ╚══════════════════════════════════════════════════════════════════╝

def get_setting(key: str, default: str = "1") -> str:
    with _conn() as con:
        row = con.execute(
            "SELECT value FROM bot_settings WHERE key=%s", (key,)
        ).fetchone()
        return row["value"] if row else default


def set_setting(key: str, value: str):
    with _conn() as con:
        con.execute("""
            INSERT INTO bot_settings (key, value, updated_at)
            VALUES (%s, %s, now())
            ON CONFLICT(key) DO UPDATE SET
                value=excluded.value,
                updated_at=now()
        """, (key, value))


def get_all_settings() -> dict:
    with _conn() as con:
        rows = con.execute("SELECT key, value FROM bot_settings").fetchall()
        return {r["key"]: r["value"] for r in rows}


# ╔══════════════════════════════════════════════════════════════════╗
# ║              ADMIN OTP  (replaces in-memory dict)               ║
# ╚══════════════════════════════════════════════════════════════════╝

def create_admin_otp(admin_id: int, code: str, expires_at) -> None:
    """Upsert an OTP code for an admin."""
    with _conn() as con:
        con.execute("""
            INSERT INTO admin_otp (admin_id, code, expires_at)
            VALUES (%s, %s, %s)
            ON CONFLICT(admin_id) DO UPDATE SET
                code=excluded.code,
                expires_at=excluded.expires_at
        """, (admin_id, code, expires_at))


def get_admin_otp(admin_id: int) -> Optional[dict]:
    """Return the OTP row for admin_id, or None if not found."""
    with _conn() as con:
        row = con.execute(
            "SELECT * FROM admin_otp WHERE admin_id=%s", (admin_id,)
        ).fetchone()
        return dict(row) if row else None


def clear_admin_otp(admin_id: int) -> None:
    """Delete the OTP row for admin_id."""
    with _conn() as con:
        con.execute("DELETE FROM admin_otp WHERE admin_id=%s", (admin_id,))


# ╔══════════════════════════════════════════════════════════════════╗
# ║           ADMIN SESSIONS  (replaces in-memory dict)             ║
# ╚══════════════════════════════════════════════════════════════════╝

def create_admin_session(token: str, expires_at) -> None:
    """Store an admin session token with its expiry."""
    with _conn() as con:
        con.execute("""
            INSERT INTO admin_sessions (token, expires_at)
            VALUES (%s, %s)
            ON CONFLICT(token) DO UPDATE SET
                expires_at=excluded.expires_at
        """, (token, expires_at))


def get_admin_session(token: str) -> Optional[float]:
    """
    Return expires_at as a unix timestamp float, or None if missing/expired.
    Deletes the row if it is already expired.
    """
    with _conn() as con:
        row = con.execute(
            "SELECT expires_at FROM admin_sessions WHERE token=%s", (token,)
        ).fetchone()
        if row is None:
            return None
        exp = row["expires_at"]
        # exp is a datetime/timestamptz object from psycopg
        import datetime as _dt
        if hasattr(exp, "timestamp"):
            ts = exp.timestamp()
        else:
            ts = float(exp)
        # Check if expired
        import time as _time
        if ts < _time.time():
            con.execute("DELETE FROM admin_sessions WHERE token=%s", (token,))
            return None
        return ts


def delete_admin_session(token: str) -> None:
    """Delete an admin session by token."""
    with _conn() as con:
        con.execute("DELETE FROM admin_sessions WHERE token=%s", (token,))
