import re
from contextlib import closing
from datetime import date

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
    client.post("/logout")

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
            "SELECT password_hash FROM users WHERE id = ?", (uid,)
        ).fetchone()[0]

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

    resp = client.post(
        "/login",
        data={"email": "rahul@example.com", "password": "password123"},
        follow_redirects=True,
    )

    assert resp.status_code == 200
    assert "Rahul Sharma" in resp.get_data(as_text=True)


def test_profile_member_since_ac24(client):
    uid = _make_user()
    _set_created_at(uid, "2026-03-05 10:20:30")
    login_as(client, uid)

    body = client.get("/profile").get_data(as_text=True)

    assert "Member since March 2026" in " ".join(body.split())


@pytest.mark.parametrize("value", ["garbage", ""])
def test_profile_bad_created_at_ac25(client, value):
    uid = _make_user()
    _set_created_at(uid, value)
    login_as(client, uid)

    resp = client.get("/profile")

    assert resp.status_code == 200
    assert "Member since" not in resp.get_data(as_text=True)


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
