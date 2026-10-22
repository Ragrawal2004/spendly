import os
import sqlite3
from contextlib import closing
from datetime import date, datetime, timezone

from werkzeug.security import generate_password_hash

_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    name          TEXT NOT NULL
                  CHECK (length(trim(name, ' ' || char(9) || char(10) || char(13))) > 0),
    email         TEXT NOT NULL UNIQUE COLLATE NOCASE,
    password_hash TEXT NOT NULL,
    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS expenses (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    amount      REAL NOT NULL CHECK (amount > 0),
    category    TEXT NOT NULL CHECK (category IN
                  ('Food','Transport','Bills','Health','Entertainment','Shopping','Other')),
    date        TEXT NOT NULL CHECK (date(date) IS NOT NULL AND date(date) = date),
    description TEXT,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_expenses_user_date ON expenses(user_id, date);
"""


_MISSING_URL_MESSAGE = (
    "DATABASE_URL must be set, "
    "e.g. DATABASE_URL=postgresql://USER:PASSWORD@HOST:5432/spendly"
)


def resolve_database_url(env) -> str:
    url = env.get("DATABASE_URL")
    if url:
        return url
    raise RuntimeError(_MISSING_URL_MESSAGE)


def _resolve_db_path() -> str:
    return os.environ.get("SPENDLY_DB") or os.path.join(
        os.path.dirname(__file__), "..", "spendly.db"
    )


def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(_resolve_db_path())
    conn.row_factory = sqlite3.Row
    conn.isolation_level = None
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    with closing(get_db()) as conn:
        with conn:
            conn.executescript(_SCHEMA)


def create_user(name: str, email: str, password_hash: str) -> int:
    with closing(get_db()) as conn:
        row = conn.execute(
            "INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?) "
            "RETURNING id",
            (name, email, password_hash),
        ).fetchone()
        return row["id"]


def get_user_by_email(email: str) -> sqlite3.Row | None:
    with closing(get_db()) as conn:
        return conn.execute(
            "SELECT id, name, email, password_hash FROM users WHERE email = ?",
            (email,),
        ).fetchone()


def get_user_by_id(user_id: int) -> sqlite3.Row | None:
    with closing(get_db()) as conn:
        return conn.execute(
            "SELECT id, name, email FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()


def get_user_profile(user_id: int) -> sqlite3.Row | None:
    with closing(get_db()) as conn:
        return conn.execute(
            "SELECT id, name, email, created_at FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()


def get_expense_summary(
    user_id: int, month_start: str, next_month_start: str
) -> sqlite3.Row:
    with closing(get_db()) as conn:
        return conn.execute(
            "SELECT COALESCE(SUM(amount), 0) AS total, "
            "COUNT(*) AS count, "
            "COALESCE(SUM(CASE WHEN date >= ? AND date < ? THEN amount END), 0) "
            "AS month_total "
            "FROM expenses WHERE user_id = ?",
            (month_start, next_month_start, user_id),
        ).fetchone()


def get_category_totals(user_id: int) -> list[sqlite3.Row]:
    with closing(get_db()) as conn:
        return conn.execute(
            "SELECT category, SUM(amount) AS total, COUNT(*) AS count "
            "FROM expenses WHERE user_id = ? "
            "GROUP BY category ORDER BY total DESC, category ASC",
            (user_id,),
        ).fetchall()


def get_recent_expenses(user_id: int, limit: int = 5) -> list[sqlite3.Row]:
    with closing(get_db()) as conn:
        return conn.execute(
            "SELECT id, amount, category, date, description "
            "FROM expenses WHERE user_id = ? "
            "ORDER BY date DESC, id DESC LIMIT ?",
            (user_id, limit),
        ).fetchall()


_DEMO_EXPENSES_TABLE = (
    (1, "Food", 450.00, "Weekly groceries"),
    (3, "Transport", 120.00, "Metro card recharge"),
    (5, "Bills", 1800.00, "Electricity bill"),
    (8, "Health", 650.00, "Pharmacy"),
    (12, "Entertainment", 499.00, "Streaming subscription"),
    (15, "Shopping", 2299.00, "Headphones"),
    (18, "Other", 300.00, "Gift"),
    (22, "Food", 380.00, "Dinner with friends"),
)


def _demo_expenses(today: date) -> list[tuple[str, float, str, str]]:
    return [
        (category, amount, today.replace(day=day).isoformat(), description)
        for day, category, amount, description in _DEMO_EXPENSES_TABLE
    ]


def seed_db(today: date | None = None) -> None:
    today = today or datetime.now(timezone.utc).date()
    conn = get_db()
    try:
        conn.execute("BEGIN IMMEDIATE")
        exists = conn.execute(
            "SELECT 1 FROM users WHERE email = ?", ("demo@spendly.com",)
        ).fetchone()
        if exists:
            conn.commit()
            return

        password_hash = generate_password_hash("demo123")
        user_id = conn.execute(
            "INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?) "
            "RETURNING id",
            ("Demo User", "demo@spendly.com", password_hash),
        ).fetchone()["id"]

        for category, amount, date_str, description in _demo_expenses(today):
            conn.execute(
                "INSERT INTO expenses (user_id, amount, category, date, description) "
                "VALUES (?, ?, ?, ?, ?)",
                (user_id, round(amount, 2), category, date_str, description),
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
