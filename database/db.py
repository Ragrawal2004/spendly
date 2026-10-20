import os
import sqlite3
from contextlib import closing

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


# seed_db()  — inserts sample data for development
