import os
from contextlib import closing
from datetime import date, datetime, timezone

import psycopg
from psycopg.rows import dict_row
from werkzeug.security import generate_password_hash

_SCHEMA = (
    r"""
CREATE TABLE IF NOT EXISTS users (
    id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name          TEXT NOT NULL CHECK (btrim(name, E' \t\n\r') <> ''),
    email         TEXT NOT NULL
                  CONSTRAINT users_email_lowercase CHECK (email = lower(email)),
    password_hash TEXT NOT NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
)
""",
    """
CREATE TABLE IF NOT EXISTS expenses (
    id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id     BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    amount      NUMERIC(12,2) NOT NULL CHECK (amount > 0),
    category    TEXT NOT NULL CHECK (category IN
                  ('Food','Transport','Bills','Health','Entertainment','Shopping','Other')),
    date        DATE NOT NULL,
    description TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
)
""",
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_users_email ON users (email)",
    "CREATE INDEX IF NOT EXISTS idx_expenses_user_date ON expenses (user_id, date)",
)


_MISSING_URL_MESSAGE = (
    "DATABASE_URL must be set, "
    "e.g. DATABASE_URL=postgresql://USER:PASSWORD@HOST:5432/spendly"
)


def resolve_database_url(env) -> str:
    url = env.get("DATABASE_URL")
    if url:
        return url
    raise RuntimeError(_MISSING_URL_MESSAGE)


def get_db() -> psycopg.Connection:
    return psycopg.connect(
        resolve_database_url(os.environ), row_factory=dict_row, autocommit=True
    )


def init_db() -> None:
    with closing(get_db()) as conn, conn.transaction():
        for statement in _SCHEMA:
            conn.execute(statement)


def create_user(name: str, email: str, password_hash: str) -> int:
    with closing(get_db()) as conn:
        row = conn.execute(
            "INSERT INTO users (name, email, password_hash) VALUES (%s, %s, %s) "
            "RETURNING id",
            (name, email, password_hash),
        ).fetchone()
        return row["id"]


def get_user_by_email(email: str) -> dict | None:
    with closing(get_db()) as conn:
        return conn.execute(
            "SELECT id, name, email, password_hash FROM users WHERE email = %s",
            (email,),
        ).fetchone()


def get_user_by_id(user_id: int) -> dict | None:
    with closing(get_db()) as conn:
        return conn.execute(
            "SELECT id, name, email FROM users WHERE id = %s",
            (user_id,),
        ).fetchone()


def get_user_profile(user_id: int) -> dict | None:
    with closing(get_db()) as conn:
        return conn.execute(
            "SELECT id, name, email, created_at FROM users WHERE id = %s",
            (user_id,),
        ).fetchone()


def get_expense_summary(
    user_id: int, month_start: str, next_month_start: str
) -> dict:
    with closing(get_db()) as conn:
        return conn.execute(
            "SELECT COALESCE(SUM(amount), 0) AS total, "
            "COUNT(*) AS count, "
            "COALESCE(SUM(CASE WHEN date >= %s::date AND date < %s::date "
            "THEN amount END), 0) AS month_total "
            "FROM expenses WHERE user_id = %s",
            (month_start, next_month_start, user_id),
        ).fetchone()


def get_category_totals(user_id: int) -> list[dict]:
    with closing(get_db()) as conn:
        return conn.execute(
            "SELECT category, SUM(amount) AS total, COUNT(*) AS count "
            "FROM expenses WHERE user_id = %s "
            "GROUP BY category ORDER BY total DESC, category ASC",
            (user_id,),
        ).fetchall()


def get_recent_expenses(user_id: int, limit: int = 5) -> list[dict]:
    with closing(get_db()) as conn:
        return conn.execute(
            "SELECT id, amount, category, date, description "
            "FROM expenses WHERE user_id = %s "
            "ORDER BY date DESC, id DESC LIMIT %s",
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
    password_hash = generate_password_hash("demo123")

    with closing(get_db()) as conn, conn.transaction():
        row = conn.execute(
            "INSERT INTO users (name, email, password_hash) VALUES (%s, %s, %s) "
            "ON CONFLICT (email) DO NOTHING RETURNING id",
            ("Demo User", "demo@spendly.com", password_hash),
        ).fetchone()
        if row is None:
            return

        for category, amount, date_str, description in _demo_expenses(today):
            conn.execute(
                "INSERT INTO expenses (user_id, amount, category, date, description) "
                "VALUES (%s, %s, %s, %s, %s)",
                (row["id"], round(amount, 2), category, date_str, description),
            )
