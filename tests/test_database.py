import os
from contextlib import closing
from datetime import date
from decimal import Decimal
from pathlib import Path

import psycopg
import pytest
from psycopg.conninfo import conninfo_to_dict
from werkzeug.security import check_password_hash

from database import db

_REAL_DB_PATH = Path(__file__).resolve().parent.parent / "spendly.db"
_REAL_DB_EXISTED_BEFORE = _REAL_DB_PATH.exists()
_REAL_DB_MTIME_BEFORE = (
    _REAL_DB_PATH.stat().st_mtime if _REAL_DB_EXISTED_BEFORE else None
)


def _insert_user(conn, name="Test User", email="user@example.com"):
    row = conn.execute(
        "INSERT INTO users (name, email, password_hash) VALUES (%s, %s, %s) "
        "RETURNING id",
        (name, email, "hash"),
    ).fetchone()
    return row["id"]


def test_tests_use_spendly_test_and_real_db_untouched_ac1():
    dbname = conninfo_to_dict(os.environ["DATABASE_URL"]).get("dbname")
    assert dbname == "spendly_test"

    exists_after = _REAL_DB_PATH.exists()
    assert exists_after == _REAL_DB_EXISTED_BEFORE
    if _REAL_DB_EXISTED_BEFORE:
        assert _REAL_DB_PATH.stat().st_mtime == _REAL_DB_MTIME_BEFORE


def test_get_db_returns_dict_rows_in_autocommit_ac5():
    with closing(db.get_db()) as conn:
        assert conn.autocommit is True

        conn.execute("CREATE TEMP TABLE t (col TEXT)")
        conn.execute("INSERT INTO t (col) VALUES (%s)", ("value",))
        row = conn.execute("SELECT col FROM t").fetchone()
        assert isinstance(row, dict)
        assert row["col"] == "value"

        with pytest.raises(psycopg.errors.DivisionByZero):
            conn.execute("SELECT 1/0")
        assert conn.execute("SELECT 1 AS one").fetchone()["one"] == 1


def test_init_db_creates_tables_and_indexes_ac6():
    db.init_db()
    db.init_db()

    with closing(db.get_db()) as conn:
        for name in ("users", "expenses", "idx_expenses_user_date", "idx_users_email"):
            found = conn.execute(
                "SELECT to_regclass(%s) IS NOT NULL AS found", (name,)
            ).fetchone()["found"]
            assert found, name

        unique = conn.execute(
            "SELECT indisunique FROM pg_index "
            "WHERE indexrelid = 'idx_users_email'::regclass"
        ).fetchone()["indisunique"]

    assert unique is True


def test_expense_with_missing_user_id_raises_ac7():
    db.init_db()

    with closing(db.get_db()) as conn:
        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            conn.execute(
                "INSERT INTO expenses (user_id, amount, category, date) "
                "VALUES (%s, %s, %s, %s)",
                (999, 10.0, "Food", "2026-10-01"),
            )


def test_expense_amount_and_category_constraints_ac8():
    db.init_db()

    with closing(db.get_db()) as conn:
        user_id = _insert_user(conn)

        with pytest.raises(psycopg.errors.CheckViolation):
            conn.execute(
                "INSERT INTO expenses (user_id, amount, category, date) "
                "VALUES (%s, %s, %s, %s)",
                (user_id, 0, "Food", "2026-10-01"),
            )

        with pytest.raises(psycopg.errors.CheckViolation):
            conn.execute(
                "INSERT INTO expenses (user_id, amount, category, date) "
                "VALUES (%s, %s, %s, %s)",
                (user_id, -5, "Food", "2026-10-01"),
            )

        with pytest.raises(psycopg.errors.CheckViolation):
            conn.execute(
                "INSERT INTO expenses (user_id, amount, category, date) "
                "VALUES (%s, %s, %s, %s)",
                (user_id, 10.0, "Groceries", "2026-10-01"),
            )


def test_delete_user_cascades_to_expenses():
    db.init_db()

    with closing(db.get_db()) as conn:
        user_id = _insert_user(conn)
        conn.execute(
            "INSERT INTO expenses (user_id, amount, category, date) "
            "VALUES (%s, %s, %s, %s)",
            (user_id, 10.0, "Food", "2026-10-01"),
        )

        conn.execute("DELETE FROM users WHERE id = %s", (user_id,))

        remaining = conn.execute(
            "SELECT COUNT(*) AS n FROM expenses WHERE user_id = %s", (user_id,)
        ).fetchone()["n"]

    assert remaining == 0


@pytest.mark.parametrize("name", ["", "   ", "\t\n"])
def test_blank_name_variants_raise_ac9(name):
    db.init_db()

    with closing(db.get_db()) as conn:
        with pytest.raises(psycopg.errors.CheckViolation):
            conn.execute(
                "INSERT INTO users (name, email, password_hash) VALUES (%s, %s, %s)",
                (name, f"blank-{len(name)}@example.com", "hash"),
            )


def test_date_column_rejects_impossible_dates_ac10():
    db.init_db()

    invalid_dates = ["2026-02-30", "2026-04-31", "2026-13-01"]
    valid_dates = ["2026-02-28", "2028-02-29"]

    with closing(db.get_db()) as conn:
        user_id = _insert_user(conn)

        for bad_date in invalid_dates:
            with pytest.raises(psycopg.DataError):
                conn.execute(
                    "INSERT INTO expenses (user_id, amount, category, date) "
                    "VALUES (%s, %s, %s, %s)",
                    (user_id, 10.0, "Food", bad_date),
                )

        for good_date in valid_dates:
            conn.execute(
                "INSERT INTO expenses (user_id, amount, category, date) "
                "VALUES (%s, %s, %s, %s)",
                (user_id, 10.0, "Food", good_date),
            )

        count = conn.execute(
            "SELECT COUNT(*) AS n FROM expenses WHERE user_id = %s", (user_id,)
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


def test_seed_db_dates_and_categories_ac11():
    today = date(2026, 10, 20)

    db.init_db()
    db.seed_db(today)

    with closing(db.get_db()) as conn:
        rows = conn.execute("SELECT category, date FROM expenses").fetchall()

    dates = {row["date"] for row in rows}
    assert dates == {
        date(2026, 10, day) for day in (1, 3, 5, 8, 12, 15, 18, 22)
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
            "SELECT password_hash FROM users WHERE email = %s",
            ("demo@spendly.com",),
        ).fetchone()["password_hash"]

    assert password_hash != "demo123"
    assert check_password_hash(password_hash, "demo123")


def test_email_lowercase_and_unique_ac12():
    db.init_db()
    db.seed_db(date(2026, 10, 20))

    with closing(db.get_db()) as conn:
        with pytest.raises(psycopg.errors.CheckViolation):
            conn.execute(
                "INSERT INTO users (name, email, password_hash) VALUES (%s, %s, %s)",
                ("Someone Else", "DEMO@SPENDLY.COM", "hash"),
            )

        with pytest.raises(psycopg.errors.UniqueViolation):
            conn.execute(
                "INSERT INTO users (name, email, password_hash) VALUES (%s, %s, %s)",
                ("Someone Else", "demo@spendly.com", "hash"),
            )


def test_seed_db_rolls_back_on_bad_row_ac13(monkeypatch):
    today = date(2026, 10, 20)
    db.init_db()

    good_rows = db._demo_expenses(today)
    bad_rows = list(good_rows)
    category, _, date_str, description = bad_rows[4]
    bad_rows[4] = (category, 0, date_str, description)

    monkeypatch.setattr(db, "_demo_expenses", lambda today: bad_rows)

    with pytest.raises(psycopg.errors.CheckViolation):
        db.seed_db(today)

    with closing(db.get_db()) as conn:
        assert _counts(conn) == (0, 0)


def test_seed_db_noop_when_demo_user_exists_from_other_connection():
    today = date(2026, 10, 20)
    db.init_db()

    with closing(db.get_db()) as conn:
        conn.execute(
            "INSERT INTO users (name, email, password_hash) VALUES (%s, %s, %s)",
            ("Demo User", "demo@spendly.com", "preexisting-hash"),
        )

    db.seed_db(today)

    with closing(db.get_db()) as conn:
        assert _counts(conn) == (1, 0)


def test_startup_skips_seed_in_production_ac14(monkeypatch):
    import app

    monkeypatch.setenv("SPENDLY_ENV", "production")

    app.startup()

    with closing(db.get_db()) as conn:
        for name in ("users", "expenses"):
            found = conn.execute(
                "SELECT to_regclass(%s) IS NOT NULL AS found", (name,)
            ).fetchone()["found"]
            assert found, name
        demo_user = conn.execute(
            "SELECT 1 FROM users WHERE email = %s", ("demo@spendly.com",)
        ).fetchone()

    assert demo_user is None


def test_resolve_database_url_returns_set_value_ac2():
    env = {"DATABASE_URL": "postgresql://u@h/db"}

    assert db.resolve_database_url(env) == "postgresql://u@h/db"


@pytest.mark.parametrize(
    "env",
    [
        {"SPENDLY_ENV": "production"},
        {"SPENDLY_ENV": "production", "DATABASE_URL": ""},
    ],
)
def test_resolve_database_url_production_requires_url_ac3(env):
    with pytest.raises(RuntimeError, match="DATABASE_URL"):
        db.resolve_database_url(env)


@pytest.mark.parametrize(
    "env",
    [
        {},
        {"SPENDLY_ENV": "development"},
        {"SPENDLY_ENV": "development", "DATABASE_URL": ""},
    ],
)
def test_resolve_database_url_development_requires_url_ac4(env):
    with pytest.raises(RuntimeError, match="DATABASE_URL"):
        db.resolve_database_url(env)


def test_resolve_database_url_message_is_fixed_ac33():
    env = {"SPENDLY_TEST_DATABASE_URL": "postgresql://u:s3cret@h/spendly_test"}

    with pytest.raises(RuntimeError) as excinfo:
        db.resolve_database_url(env)

    assert str(excinfo.value) == db._MISSING_URL_MESSAGE
    assert str(excinfo.value) == (
        "DATABASE_URL must be set, "
        "e.g. DATABASE_URL=postgresql://USER:PASSWORD@HOST:5432/spendly"
    )
    assert "s3cret" not in str(excinfo.value)


def test_garbage_created_at_rejected_ac22():
    db.init_db()
    with closing(db.get_db()) as conn:
        uid = _insert_user(conn)

        with pytest.raises(psycopg.errors.InvalidDatetimeFormat):
            conn.execute(
                "UPDATE users SET created_at = %s WHERE id = %s", ("garbage", uid)
            )


def test_amount_precision_and_range_ac23():
    db.init_db()
    with closing(db.get_db()) as conn:
        uid = _insert_user(conn)
        insert = (
            "INSERT INTO expenses (user_id, amount, category, date) "
            "VALUES (%s, %s, 'Food', '2026-10-01')"
        )

        with pytest.raises(psycopg.errors.CheckViolation):
            conn.execute(insert, (uid, Decimal("0.004")))

        conn.execute(insert, (uid, Decimal("12.345")))
        stored = conn.execute("SELECT amount FROM expenses").fetchone()["amount"]
        assert stored == Decimal("12.35")
        assert isinstance(stored, Decimal)

        with pytest.raises(psycopg.errors.NumericValueOutOfRange):
            conn.execute(insert, (uid, Decimal("10000000000")))


def test_seed_db_twice_exact_totals_ac32():
    today = date(2026, 10, 20)

    db.init_db()
    db.seed_db(today)
    db.seed_db(today)

    with closing(db.get_db()) as conn:
        assert _counts(conn) == (1, 8)
        total = conn.execute("SELECT SUM(amount) AS s FROM expenses").fetchone()["s"]
        assert total == Decimal("6498.00")
