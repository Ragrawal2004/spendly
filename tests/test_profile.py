import re
from contextlib import closing
from datetime import date

import pytest

from werkzeug.security import generate_password_hash

from app import category_share, format_amount, member_since, month_bounds
from database.db import (
    create_user,
    get_category_totals,
    get_db,
    get_expense_summary,
    get_recent_expenses,
    get_user_profile,
    init_db,
)


def _make_user(name="Rahul Sharma", email="rahul@example.com"):
    init_db()
    return create_user(name, email, generate_password_hash("password123"))


def login_as(client, uid):
    with client.session_transaction() as sess:
        sess["user_id"] = uid


def _add_expense(uid, amount, category, date, description=None):
    with closing(get_db()) as conn:
        with conn:
            cur = conn.execute(
                "INSERT INTO expenses (user_id, amount, category, date, description) "
                "VALUES (?, ?, ?, ?, ?)",
                (uid, amount, category, date, description),
            )
    return cur.lastrowid


def _set_created_at(uid, value):
    with closing(get_db()) as conn:
        with conn:
            conn.execute("UPDATE users SET created_at = ? WHERE id = ?", (value, uid))


NAV_PROFILE_LINK = re.compile(
    r'<a\b(?=[^>]*\bhref="/profile")(?=[^>]*\bclass="nav-user")[^>]*>'
)


# --- nav (Task 1; AC-20 nav half) ---


def test_nav_user_name_links_to_profile(client):
    uid = _make_user()
    login_as(client, uid)

    body = client.get("/").get_data(as_text=True)

    assert NAV_PROFILE_LINK.search(body)


# --- db read functions (Task 2) ---


def test_summary_month_bounds_ac8(client):
    uid = _make_user()
    for d in ("2026-10-01", "2026-10-31", "2026-11-01", "2026-09-30"):
        _add_expense(uid, 10, "Food", d)

    row = get_expense_summary(uid, "2026-10-01", "2026-11-01")

    assert row["month_total"] == pytest.approx(20)
    assert row["total"] == pytest.approx(40)
    assert row["count"] == 4


def test_category_totals_order_ac10(client):
    uid = _make_user()
    _add_expense(uid, 300, "Food", "2026-10-01")
    _add_expense(uid, 100, "Food", "2026-10-02")
    _add_expense(uid, 100, "Transport", "2026-10-03")
    _add_expense(uid, 100, "Bills", "2026-10-04")

    rows = get_category_totals(uid)

    assert [(r["category"], r["total"], r["count"]) for r in rows] == [
        ("Food", 400, 2),
        ("Bills", 100, 1),
        ("Transport", 100, 1),
    ]


def test_recent_expenses_limit_and_order_ac11(client):
    uid = _make_user()
    for day in range(1, 8):
        _add_expense(uid, day, "Food", f"2026-10-0{day}")

    rows = get_recent_expenses(uid)

    assert [r["date"] for r in rows] == [f"2026-10-0{d}" for d in range(7, 2, -1)]


def test_recent_expenses_same_date_higher_id_first(client):
    uid = _make_user()
    first = _add_expense(uid, 1, "Food", "2026-10-01")
    second = _add_expense(uid, 2, "Food", "2026-10-01")

    assert [r["id"] for r in get_recent_expenses(uid)] == [second, first]


def test_get_user_profile_hit_and_miss(client):
    uid = _make_user()

    row = get_user_profile(uid)

    assert row["created_at"]
    assert "password_hash" not in row.keys()
    assert get_user_profile(uid + 99) is None


def test_summary_empty_user(client):
    uid = _make_user()

    row = get_expense_summary(uid, "2026-10-01", "2026-11-01")

    assert (row["total"], row["count"], row["month_total"]) == (0, 0, 0)


def test_queries_do_not_leak_other_users(client):
    a = _make_user()
    b = _make_user("Other", "other@example.com")
    _add_expense(b, 50, "Food", "2026-10-05", "secret")

    assert get_category_totals(a) == []
    assert get_recent_expenses(a) == []
    assert get_expense_summary(a, "2026-10-01", "2026-11-01")["count"] == 0


# --- pure helpers (Task 3) ---


def test_month_bounds_ac7():
    assert month_bounds(date(2026, 10, 21)) == ("2026-10-01", "2026-11-01")
    assert month_bounds(date(2026, 12, 15)) == ("2026-12-01", "2027-01-01")


def test_member_since_valid():
    assert member_since("2026-03-05 10:20:30") == "March 2026"


@pytest.mark.parametrize("value", [None, "", "garbage"])
def test_member_since_invalid_returns_none(value):
    assert member_since(value) is None


def test_format_amount():
    assert format_amount(12345678.9) == "₹12,345,678.90"
    assert format_amount(0.1 + 0.2) == "₹0.30"
    assert format_amount(0) == "₹0.00"


def test_category_share():
    assert category_share(400, 600) == 67
    assert category_share(12.5, 100) == 13
    assert category_share(0, 0) == 0
