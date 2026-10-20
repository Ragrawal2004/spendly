import os
import sqlite3
from contextlib import closing
from datetime import date
from pathlib import Path

import pytest
from werkzeug.security import check_password_hash

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


def test_demo_expenses_shape():
    rows = db._demo_expenses(date(2026, 10, 20))

    assert len(rows) == 8

    dates = [row[2] for row in rows]
    assert dates == [
        "2026-10-01",
        "2026-10-03",
        "2026-10-05",
        "2026-10-08",
        "2026-10-12",
        "2026-10-15",
        "2026-10-18",
        "2026-10-22",
    ]

    categories = [row[0] for row in rows]
    assert set(categories) == {
        "Food",
        "Transport",
        "Bills",
        "Health",
        "Entertainment",
        "Shopping",
        "Other",
    }
    assert categories.count("Food") == 2

    amounts = [row[1] for row in rows]
    assert amounts == [450.0, 120.0, 1800.0, 650.0, 499.0, 2299.0, 300.0, 380.0]

    descriptions = [row[3] for row in rows]
    assert descriptions == [
        "Weekly groceries",
        "Metro card recharge",
        "Electricity bill",
        "Pharmacy",
        "Streaming subscription",
        "Headphones",
        "Gift",
        "Dinner with friends",
    ]


def _counts(conn):
    users = conn.execute("SELECT COUNT(*) AS n FROM users").fetchone()["n"]
    expenses = conn.execute("SELECT COUNT(*) AS n FROM expenses").fetchone()["n"]
    return users, expenses


def test_seed_db_is_idempotent():
    today = date(2026, 10, 20)

    db.init_db()
    db.seed_db(today)
    db.init_db()
    db.seed_db(today)
    db.init_db()
    db.seed_db(today)

    with closing(db.get_db()) as conn:
        assert _counts(conn) == (1, 8)


def test_seed_db_dates_and_categories():
    today = date(2026, 10, 20)

    db.init_db()
    db.seed_db(today)

    with closing(db.get_db()) as conn:
        rows = conn.execute("SELECT category, date FROM expenses").fetchall()

    dates = {row["date"] for row in rows}
    assert dates == {
        "2026-10-01",
        "2026-10-03",
        "2026-10-05",
        "2026-10-08",
        "2026-10-12",
        "2026-10-15",
        "2026-10-18",
        "2026-10-22",
    }

    categories = {row["category"] for row in rows}
    assert categories == {
        "Food",
        "Transport",
        "Bills",
        "Health",
        "Entertainment",
        "Shopping",
        "Other",
    }


def test_demo_password_is_hashed_and_verifiable():
    db.init_db()
    db.seed_db(date(2026, 10, 20))

    with closing(db.get_db()) as conn:
        password_hash = conn.execute(
            "SELECT password_hash FROM users WHERE email = ?",
            ("demo@spendly.com",),
        ).fetchone()["password_hash"]

    assert password_hash != "demo123"
    assert check_password_hash(password_hash, "demo123")


def test_duplicate_email_case_insensitive_raises():
    db.init_db()
    db.seed_db(date(2026, 10, 20))

    with closing(db.get_db()) as conn:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
                ("Someone Else", "DEMO@SPENDLY.COM", "hash"),
            )


def test_seed_db_rolls_back_on_bad_row(monkeypatch):
    today = date(2026, 10, 20)
    db.init_db()

    good_rows = db._demo_expenses(today)
    bad_rows = list(good_rows)
    category, _, date_str, description = bad_rows[4]
    bad_rows[4] = (category, 0, date_str, description)

    monkeypatch.setattr(db, "_demo_expenses", lambda today: bad_rows)

    with pytest.raises(sqlite3.IntegrityError):
        db.seed_db(today)

    with closing(db.get_db()) as conn:
        assert _counts(conn) == (0, 0)


def test_seed_db_noop_when_demo_user_exists_from_other_connection():
    today = date(2026, 10, 20)
    db.init_db()

    with closing(db.get_db()) as conn:
        with conn:
            conn.execute(
                "INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
                ("Demo User", "demo@spendly.com", "preexisting-hash"),
            )

    db.seed_db(today)

    with closing(db.get_db()) as conn:
        assert _counts(conn) == (1, 0)
