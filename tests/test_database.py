import os
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from database import db


def _insert_user(conn, name="Test User", email="user@example.com"):
    cur = conn.execute(
        "INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
        (name, email, "hash"),
    )
    return cur.lastrowid


def test_database_isolation_env_var_set_and_real_db_untouched():
    assert "SPENDLY_DB" in os.environ

    real_db_path = Path(__file__).resolve().parent.parent / "spendly.db"
    assert os.environ["SPENDLY_DB"] != str(real_db_path)
    assert not real_db_path.exists()


def test_get_db_returns_row_with_foreign_keys_on():
    conn = db.get_db()
    try:
        fk_status = conn.execute("PRAGMA foreign_keys").fetchone()[0]
        assert fk_status == 1

        conn.execute("CREATE TABLE t (col TEXT)")
        conn.execute("INSERT INTO t (col) VALUES (?)", ("value",))
        row = conn.execute("SELECT col FROM t").fetchone()
        assert row["col"] == "value"
    finally:
        conn.close()


def test_init_db_creates_tables_and_index():
    db.init_db()

    with closing(db.get_db()) as conn:
        names = {
            row["name"]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type IN ('table', 'index')"
            )
        }

    assert "users" in names
    assert "expenses" in names
    assert "idx_expenses_user_date" in names


def test_expense_with_missing_user_id_raises():
    db.init_db()

    with closing(db.get_db()) as conn:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO expenses (user_id, amount, category, date) "
                "VALUES (?, ?, ?, ?)",
                (999, 10.0, "Food", "2026-10-01"),
            )


def test_expense_amount_and_category_constraints():
    db.init_db()

    with closing(db.get_db()) as conn:
        user_id = _insert_user(conn)

        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO expenses (user_id, amount, category, date) "
                "VALUES (?, ?, ?, ?)",
                (user_id, 0, "Food", "2026-10-01"),
            )

        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO expenses (user_id, amount, category, date) "
                "VALUES (?, ?, ?, ?)",
                (user_id, -5, "Food", "2026-10-01"),
            )

        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO expenses (user_id, amount, category, date) "
                "VALUES (?, ?, ?, ?)",
                (user_id, 10.0, "Groceries", "2026-10-01"),
            )


def test_delete_user_cascades_to_expenses():
    db.init_db()

    with closing(db.get_db()) as conn:
        user_id = _insert_user(conn)
        conn.execute(
            "INSERT INTO expenses (user_id, amount, category, date) "
            "VALUES (?, ?, ?, ?)",
            (user_id, 10.0, "Food", "2026-10-01"),
        )

        conn.execute("DELETE FROM users WHERE id = ?", (user_id,))

        remaining = conn.execute(
            "SELECT COUNT(*) AS n FROM expenses WHERE user_id = ?", (user_id,)
        ).fetchone()["n"]

    assert remaining == 0


@pytest.mark.parametrize("name", ["", "   ", "\t\n"])
def test_blank_name_variants_raise(name):
    db.init_db()

    with closing(db.get_db()) as conn:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
                (name, f"blank-{len(name)}@example.com", "hash"),
            )


def test_date_constraint_rejects_invalid_accepts_valid():
    db.init_db()

    invalid_dates = [
        "2026-02-30",
        "2026-04-31",
        "2026-13-01",
        "20-10-2026",
        "2026-1-5",
        "2026-02-28 10:00",
    ]
    valid_dates = ["2026-02-28", "2028-02-29"]

    with closing(db.get_db()) as conn:
        user_id = _insert_user(conn)

        for bad_date in invalid_dates:
            with pytest.raises(sqlite3.IntegrityError):
                conn.execute(
                    "INSERT INTO expenses (user_id, amount, category, date) "
                    "VALUES (?, ?, ?, ?)",
                    (user_id, 10.0, "Food", bad_date),
                )

        for good_date in valid_dates:
            conn.execute(
                "INSERT INTO expenses (user_id, amount, category, date) "
                "VALUES (?, ?, ?, ?)",
                (user_id, 10.0, "Food", good_date),
            )

        count = conn.execute(
            "SELECT COUNT(*) AS n FROM expenses WHERE user_id = ?", (user_id,)
        ).fetchone()["n"]

    assert count == len(valid_dates)
