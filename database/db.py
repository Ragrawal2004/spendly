import os
import sqlite3


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


# init_db()  — creates all tables using CREATE TABLE IF NOT EXISTS
# seed_db()  — inserts sample data for development
