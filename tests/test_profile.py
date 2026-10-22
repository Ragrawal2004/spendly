import re
from contextlib import closing
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from werkzeug.security import generate_password_hash

from flask import g

from app import (
    app,
    category_share,
    format_amount,
    login_required,
    member_since,
    month_bounds,
)
from database.db import (
    create_user,
    get_category_totals,
    get_db,
    get_expense_summary,
    get_recent_expenses,
    get_user_profile,
    init_db,
)
from helpers import csrf_token, post_form


def _make_user(name="Rahul Sharma", email="rahul@example.com"):
    init_db()
    return create_user(name, email, generate_password_hash("password123"))


def login_as(client, uid):
    with client.session_transaction() as sess:
        sess["user_id"] = uid
    csrf_token(client)


def _add_expense(uid, amount, category, date, description=None):
    with closing(get_db()) as conn:
        row = conn.execute(
            "INSERT INTO expenses (user_id, amount, category, date, description) "
            "VALUES (%s, %s, %s, %s, %s) RETURNING id",
            (uid, amount, category, date, description),
        ).fetchone()
        return row["id"]


def _set_created_at(uid, value):
    with closing(get_db()) as conn:
        conn.execute("UPDATE users SET created_at = %s WHERE id = %s", (value, uid))


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

    assert row["month_total"] == Decimal("20.00")
    assert row["total"] == Decimal("40.00")
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

    assert [r["date"] for r in rows] == [date(2026, 10, d) for d in range(7, 2, -1)]


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


def test_format_amount_decimal_ac26():
    assert format_amount(Decimal("12345678.90")) == "₹12,345,678.90"
    assert format_amount(Decimal("0")) == "₹0.00"
    assert format_amount(Decimal("0.30")) == "₹0.30"
    assert format_amount(Decimal("400.00")) == "₹400.00"


def test_category_share_decimal_ac27():
    cases = [
        ((Decimal("400.00"), Decimal("600.00")), 67),
        ((Decimal("12.50"), Decimal("100.00")), 13),
        ((Decimal("0"), Decimal("0")), 0),
        ((Decimal("1.00"), Decimal("3.00")), 33),
        ((Decimal("5.00"), 10), 50),
    ]
    for args, expected in cases:
        result = category_share(*args)
        assert result == expected
        assert isinstance(result, int)


def test_member_since_datetime_ac28():
    aware_utc = datetime(2026, 3, 5, 10, 20, 30, tzinfo=timezone.utc)
    naive = datetime(2026, 3, 5, 10, 20, 30)
    # 2026-04-01 04:00 at +05:30 is 2026-03-31 22:30 UTC
    offset = datetime(
        2026, 4, 1, 4, 0, tzinfo=timezone(timedelta(hours=5, minutes=30))
    )
    for value in (aware_utc, naive, offset):
        assert member_since(value) == "March 2026"


@pytest.mark.parametrize("value", [date(2026, 3, 5), 12345])
def test_member_since_other_types_ac29(value):
    assert member_since(value) is None


# --- login_required (Task 4; AC-1, 3, 4, 5, 22, 23) ---


def test_profile_signed_out_redirects_ac1(client):
    _make_user()

    resp = client.get("/profile")

    assert resp.status_code == 302
    assert resp.headers["Location"] == "/login"
    body = resp.get_data(as_text=True)
    assert "Rahul Sharma" not in body
    assert "Profile" not in body


def test_profile_unknown_user_id_redirects_ac3(client):
    _make_user()
    login_as(client, 9999)

    resp = client.get("/profile")

    assert resp.status_code == 302
    assert resp.headers["Location"] == "/login"
    with client.session_transaction() as sess:
        assert "user_id" not in sess


def test_profile_garbage_cookie_redirects_ac4(client):
    _make_user()
    client.set_cookie("session", "garbage")

    resp = client.get("/profile")

    assert resp.status_code == 302
    assert resp.headers["Location"] == "/login"


@pytest.mark.parametrize("method", ["post", "put", "delete"])
def test_profile_rejects_non_get_ac5(client, method):
    # Regression guard: the placeholder route is already GET-only.
    uid = _make_user()
    login_as(client, uid)

    assert getattr(client, method)("/profile").status_code == 405


def test_profile_after_logout_redirects_ac22(client):
    uid = _make_user()
    login_as(client, uid)
    post_form(client, "/logout")

    resp = client.get("/profile")

    assert resp.status_code == 302
    assert resp.headers["Location"] == "/login"


def test_login_required_decorator_ac23(client):
    ran = []

    def view():
        ran.append(True)
        return "sentinel"

    wrapped = login_required(view)
    assert wrapped.__name__ == "view"

    with app.test_request_context():
        g.current_user = None
        resp = wrapped()
        assert resp.status_code == 302
        assert resp.headers["Location"] == "/login"
        assert not ran

        g.current_user = {"id": 1, "name": "Rahul Sharma", "email": "rahul@example.com"}
        assert wrapped() == "sentinel"
        assert ran


# --- profile page: account card and totals (Task 5) ---


def test_profile_shows_account_card_ac2(client):
    uid = _make_user()
    login_as(client, uid)

    resp = client.get("/profile")

    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "Rahul Sharma" in body
    assert "rahul@example.com" in body
    assert "Member since" in body


def test_profile_totals_and_count_ac6(client):
    uid = _make_user()
    for amount in (100.00, 250.50, 49.50):
        _add_expense(uid, amount, "Food", "2026-10-05")
    login_as(client, uid)

    body = client.get("/profile").get_data(as_text=True)

    assert "₹400.00" in body
    assert "3 expenses" in body


def test_profile_ignores_user_id_query_ac13(client):
    uid = _make_user()
    other = _make_user("Other Person", "other@example.com")
    login_as(client, uid)

    body = client.get(f"/profile?user_id={other}").get_data(as_text=True)

    assert "Rahul Sharma" in body
    assert "Other Person" not in body


def test_profile_amount_formatting_ac16(client):
    uid = _make_user()
    _add_expense(uid, 12345678.9, "Food", "2026-10-05")
    login_as(client, uid)
    assert "₹12,345,678.90" in client.get("/profile").get_data(as_text=True)


def test_profile_float_sum_formatting_ac16(client):
    uid = _make_user()
    _add_expense(uid, 0.1, "Food", "2026-10-05")
    _add_expense(uid, 0.2, "Food", "2026-10-05")
    login_as(client, uid)
    assert "₹0.30" in client.get("/profile").get_data(as_text=True)


def test_profile_not_cached_and_sets_no_cookie_ac17(client):
    uid = _make_user()
    login_as(client, uid)

    resp = client.get("/profile")

    assert resp.headers["Cache-Control"] == "no-store"
    assert "Set-Cookie" not in resp.headers


def test_profile_never_sends_hash_ac18(client):
    # Regression guard: the placeholder never leaked it either.
    uid = _make_user()
    login_as(client, uid)
    with closing(get_db()) as conn:
        stored = conn.execute(
            "SELECT password_hash FROM users WHERE id = %s", (uid,)
        ).fetchone()["password_hash"]

    body = client.get("/profile").get_data(as_text=True)

    assert stored not in body
    assert "password_hash" not in body


def test_profile_nav_and_add_expense_links_ac20(client):
    uid = _make_user()
    login_as(client, uid)

    body = client.get("/profile").get_data(as_text=True)

    assert NAV_PROFILE_LINK.search(body)
    assert 'href="/expenses/add"' in body


def test_login_lands_on_profile_ac21(client):
    _make_user()

    resp = post_form(
        client,
        "/login",
        data={"email": "rahul@example.com", "password": "password123"},
        follow_redirects=True,
    )

    assert resp.status_code == 200
    assert "Rahul Sharma" in resp.get_data(as_text=True)


def test_profile_member_since_ac24(client):
    uid = _make_user()
    _set_created_at(uid, "2026-03-05 10:20:30+00")
    login_as(client, uid)

    body = client.get("/profile").get_data(as_text=True)

    assert "Member since March 2026" in " ".join(body.split())


@pytest.mark.parametrize("value", ["garbage", ""])
def test_profile_bad_created_at_ac25(client, monkeypatch, value):
    uid = _make_user()
    login_as(client, uid)
    monkeypatch.setattr(
        "app.get_user_profile",
        lambda user_id: {"id": user_id, "name": "Rahul Sharma",
                         "email": "rahul@example.com", "created_at": value},
    )

    resp = client.get("/profile")

    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "Rahul Sharma" in body
    assert "rahul@example.com" in body
    assert "Member since" not in body


def test_profile_null_created_at_ac25(client, monkeypatch):
    uid = _make_user()
    login_as(client, uid)
    monkeypatch.setattr(
        "app.get_user_profile",
        lambda user_id: {"id": user_id, "name": "Rahul Sharma",
                         "email": "rahul@example.com", "created_at": None},
    )

    resp = client.get("/profile")

    assert resp.status_code == 200
    assert "Member since" not in resp.get_data(as_text=True)


def test_profile_vanished_user_redirects(client, monkeypatch):
    uid = _make_user()
    login_as(client, uid)
    monkeypatch.setattr("app.get_user_profile", lambda user_id: None)

    resp = client.get("/profile")

    assert resp.status_code == 302
    assert resp.headers["Location"] == "/login"
    with client.session_transaction() as sess:
        assert "user_id" not in sess


# --- category breakdown and recent expenses (Task 6) ---


def _profile_body(client, uid):
    login_as(client, uid)
    return client.get("/profile").get_data(as_text=True)


def test_profile_empty_state_ac9(client):
    uid = _make_user()

    body = _profile_body(client, uid)

    assert "₹0.00" in body
    assert "0 expenses" in body
    assert "No expenses yet." in body
    assert "category-row" not in body


def test_profile_category_percent_ac10(client):
    uid = _make_user()
    _add_expense(uid, 300, "Food", "2026-10-01")
    _add_expense(uid, 100, "Food", "2026-10-02")
    _add_expense(uid, 100, "Transport", "2026-10-03")
    _add_expense(uid, 100, "Bills", "2026-10-04")

    body = _profile_body(client, uid)

    assert "Food" in body
    assert "67%" in body


def test_profile_isolates_users_ac12(client):
    a = _make_user()
    b = _make_user("Other Person", "other@example.com")
    _add_expense(a, 111, "Food", "2026-10-01", "alpha lunch")
    _add_expense(b, 222, "Bills", "2026-10-02", "beta rent")

    body_a = _profile_body(client, a)
    assert "alpha lunch" in body_a
    assert "beta rent" not in body_a
    assert "₹222.00" not in body_a

    body_b = _profile_body(client, b)
    assert "beta rent" in body_b
    assert "alpha lunch" not in body_b
    assert "₹111.00" not in body_b


def test_profile_escapes_html_ac14(client):
    uid = _make_user("<b>x</b>", "xss@example.com")
    _add_expense(uid, 5, "Food", "2026-10-01", "<script>alert(1)</script>")

    body = _profile_body(client, uid)

    assert "&lt;b&gt;x&lt;/b&gt;" in body
    assert "&lt;script&gt;" in body
    assert "<script>alert(1)</script>" not in body


def test_profile_null_description_dash_ac15(client):
    uid = _make_user()
    _add_expense(uid, 5, "Food", "2026-10-01", None)

    body = _profile_body(client, uid)

    assert "—" in body
    assert "None" not in body


def test_profile_demo_user_ac19(client):
    from database import db
    from database.db import get_user_by_email, seed_db

    init_db()
    seed_db()
    demo = get_user_by_email("demo@spendly.com")

    body = _profile_body(client, demo["id"])

    tbody = body.split("<tbody>", 1)[1].split("</tbody>", 1)[0]
    assert len(re.findall(r"<tr\b", tbody)) == 5
    assert format_amount(sum(row[2] for row in db._DEMO_EXPENSES_TABLE)) in body
    assert f"{len(db._DEMO_EXPENSES_TABLE)} expenses" in body


# --- PostgreSQL types (AC-24, 25, 34) ---


def test_profile_queries_return_native_types_ac24(client):
    uid = _make_user()
    today = datetime.now(timezone.utc).date()
    _add_expense(uid, "100.00", "Food", today.isoformat())
    _add_expense(uid, "250.50", "Bills", "2020-01-15")
    _add_expense(uid, "49.50", "Food", "2020-01-16")
    month_start, next_month_start = month_bounds(today)

    summary = get_expense_summary(uid, month_start, next_month_start)
    categories = get_category_totals(uid)
    recent = get_recent_expenses(uid)

    assert isinstance(summary["total"], Decimal)
    assert isinstance(summary["month_total"], Decimal)
    assert isinstance(summary["count"], int)
    assert summary["total"] == Decimal("400.00")
    assert summary["month_total"] == Decimal("100.00")
    assert categories
    for row in categories:
        assert isinstance(row["total"], Decimal)
        assert isinstance(row["count"], int)
    assert recent
    for row in recent:
        assert isinstance(row["amount"], Decimal)
        assert isinstance(row["date"], date)
        assert not isinstance(row["date"], datetime)
    created_at = get_user_profile(uid)["created_at"]
    assert isinstance(created_at, datetime)
    assert created_at.tzinfo is not None


def test_summary_empty_user_types_ac25(client):
    uid = _make_user()

    row = get_expense_summary(uid, "2026-10-01", "2026-11-01")

    assert isinstance(row["total"], Decimal)
    assert isinstance(row["month_total"], Decimal)
    assert row["total"] == 0
    assert row["month_total"] == 0
    assert isinstance(row["count"], int)
    assert row["count"] == 0


def test_profile_huge_session_user_id_redirects_ac34(client):
    _make_user()
    login_as(client, 10**30)

    resp = client.get("/profile")

    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/login")
