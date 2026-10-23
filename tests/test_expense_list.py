import html
import re
from contextlib import closing
from datetime import date
from decimal import Decimal
from urllib.parse import parse_qs, urlsplit

from werkzeug.datastructures import MultiDict
from werkzeug.security import generate_password_hash

import app
from app import CATEGORIES, clean_expense_filters, format_amount, page_window
from database.db import (
    _like_pattern,
    create_expense,
    create_user,
    get_db,
    get_filtered_summary,
)
from helpers import csrf_token

_NAV_EXPENSES_RE = re.compile(r'<a\b[^>]*\bhref="/expenses"[^>]*>Expenses</a>')


def _make_user(email="rahul@example.com"):
    return create_user("Rahul Sharma", email, generate_password_hash("password123"))


def login_as(client, uid):
    with client.session_transaction() as sess:
        sess["user_id"] = uid
    csrf_token(client)


def _add(uid, amount="100.00", category="Food", day="2026-03-01", description=None):
    return create_expense(
        uid, Decimal(amount), category, date.fromisoformat(day), description
    )


def _rows():
    with closing(get_db()) as conn:
        return conn.execute(
            "SELECT id, user_id, amount, category, date, description "
            "FROM expenses ORDER BY id"
        ).fetchall()


def _text(body):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]*>", " ", body))).strip()


def _listed(body):
    tbody = re.search(r"<tbody>(.*?)</tbody>", body, re.DOTALL)
    if tbody is None:
        return []
    cells = re.findall(r"<bdi>(.*?)</bdi>", tbody.group(1), re.DOTALL)
    return [html.unescape(cell) for cell in cells]


def _link(body, label):
    for attrs, text in re.findall(r"<a\b([^>]*)>(.*?)</a>", body, re.DOTALL):
        if text.strip() == label:
            href = re.search(r'\bhref="([^"]*)"', attrs)
            return html.unescape(href.group(1)) if href else None
    return None


def _query(href):
    return parse_qs(urlsplit(href).query, keep_blank_values=True)


def _empty_block(body):
    match = re.search(r'<div class="empty-state">(.*?)</div>', body, re.DOTALL)
    return match.group(1) if match else None


def _input_value(body, name):
    for tag in re.findall(r"<input\b[^>]*>", body):
        if re.search(rf'\bname="{re.escape(name)}"', tag):
            value = re.search(r'\bvalue="([^"]*)"', tag)
            return html.unescape(value.group(1)) if value else None
    return None


def _selected_option(body):
    match = re.search(r'<option\b[^>]*\bvalue="([^"]*)"[^>]*\bselected\b[^>]*>', body)
    return html.unescape(match.group(1)) if match else None


def test_filtered_summary_types_ac23(client):
    a = _make_user("a@example.com")
    b = _make_user("b@example.com")
    _add(a, amount="0.10")
    _add(a, amount="0.20")
    _add(b, amount="5.00")

    summary = get_filtered_summary(a, None, None, None, None)
    assert summary["count"] == 2
    assert type(summary["count"]) is int
    assert summary["total"] == Decimal("0.30")
    assert isinstance(summary["total"], Decimal)

    bills = get_filtered_summary(a, "Bills", None, None, None)
    assert bills["count"] == 0
    assert bills["total"] == Decimal("0")
    assert isinstance(bills["total"], Decimal)


def test_like_pattern_ac36():
    assert _like_pattern(r"50%_\x") == r"%50\%\_\\x%"


def test_clean_expense_filters_ac34():
    keys = {"category", "date_from", "date_to", "q", "page"}

    result = clean_expense_filters(MultiDict())
    assert result == {
        "category": None, "date_from": None, "date_to": None, "q": None, "page": 1,
    }

    result = clean_expense_filters(MultiDict([("category", " Food "), ("category", "Bills")]))
    assert set(result) == keys
    assert result["category"] == "Food"

    result = clean_expense_filters(MultiDict({"date_from": "2026-04-01"}))
    assert set(result) == keys
    assert result["date_from"] == date(2026, 4, 1)

    result = clean_expense_filters(MultiDict({"q": "x" * 100}))
    assert set(result) == keys
    assert result["q"] == "x" * 100

    for value in ("x" * 101, "a\x00b"):
        result = clean_expense_filters(MultiDict({"q": value}))
        assert set(result) == keys, f"q={value!r}"
        assert result["q"] is None, f"q={value!r}"

    result = clean_expense_filters(MultiDict({"page": "3"}))
    assert set(result) == keys
    assert result["page"] == 3

    for value in ("0", "\u0663", "1234567890"):
        result = clean_expense_filters(MultiDict({"page": value}))
        assert set(result) == keys, f"page={value!r}"
        assert result["page"] == 1, f"page={value!r}"


def test_page_window_ac35():
    last_page = {"page": 2, "pages": 2, "offset": 20, "first": 21, "last": 25}
    assert page_window(0, 1, 20) == {"page": 1, "pages": 1, "offset": 0, "first": 0, "last": 0}
    assert page_window(25, 1, 20) == {"page": 1, "pages": 2, "offset": 0, "first": 1, "last": 20}
    assert page_window(25, 2, 20) == last_page
    assert page_window(25, 99, 20) == last_page
    assert page_window(20, 2, 20) == {"page": 1, "pages": 1, "offset": 0, "first": 1, "last": 20}
    assert page_window(21, 2, 20) == {"page": 2, "pages": 2, "offset": 20, "first": 21, "last": 21}


def test_signed_out_redirects_ac1(client):
    resp = client.get("/expenses")

    assert resp.status_code == 302
    assert resp.headers["Location"] == "/login"


def test_no_expenses_empty_state_ac2(client):
    uid = _make_user()
    login_as(client, uid)

    resp = client.get("/expenses")
    body = resp.get_data(as_text=True)

    assert resp.status_code == 200
    assert resp.headers.get("Cache-Control") == "no-store"
    assert "Set-Cookie" not in resp.headers
    block = _empty_block(body)
    assert block is not None
    assert "No expenses yet." in block
    assert _link(block, "Add expense") == "/expenses/add"
    assert "<table" not in body
    assert "Showing" not in body
    assert "Total:" not in body


def test_rows_newest_first_ac3(client):
    uid = _make_user()
    _add(uid, day="2026-03-01", description="a")
    _add(uid, day="2026-03-01", description="b")
    _add(uid, amount="1234.50", category="Bills", day="2026-03-05", description="c")
    _add(uid, category="Transport", day="2026-02-10")
    login_as(client, uid)

    resp = client.get("/expenses")
    body = resp.get_data(as_text=True)

    assert resp.status_code == 200
    assert _listed(body) == ["c", "b", "a", "\u2014"]
    tbody = re.search(r"<tbody>(.*?)</tbody>", body, re.DOTALL).group(1)
    rows = [_text(row) for row in re.findall(r"<tr>(.*?)</tr>", tbody, re.DOTALL)]
    assert rows == [
        "2026-03-05 Bills c \u20b91,234.50",
        "2026-03-01 Food b \u20b9100.00",
        "2026-03-01 Food a \u20b9100.00",
        "2026-02-10 Transport \u2014 \u20b9100.00",
    ]


def test_only_own_rows_ac4(client):
    a = _make_user("a@example.com")
    b = _make_user("b@example.com")
    _add(a, amount="10.00", category="Food", description="a-food")
    _add(a, amount="20.00", category="Bills", description="a-bills")
    _add(b, amount="5.00", category="Food", description="secret-b")
    _add(b, amount="7.00", category="Bills", description="b-bills")
    a_amounts = {"a-food": Decimal("10.00"), "a-bills": Decimal("20.00")}
    login_as(client, a)

    resp = client.get("/expenses")
    assert resp.status_code == 200
    assert sorted(_listed(resp.get_data(as_text=True))) == ["a-bills", "a-food"]

    for query in ({}, {"q": "secret-b"}, {"category": "Food"}, {"user_id": str(b)}):
        resp = client.get("/expenses", query_string=query)
        body = resp.get_data(as_text=True)
        assert resp.status_code == 200, f"query={query!r}"
        listed = _listed(body)
        assert not any("secret-b" in item for item in listed), f"query={query!r}"
        assert set(listed) <= set(a_amounts), f"query={query!r}"
        text = _text(body)
        if listed:
            n = len(listed)
            total = format_amount(sum((a_amounts[d] for d in listed), Decimal("0")))
            assert f"Showing 1-{n} of {n}" in text, f"query={query!r}"
            assert f"Total: {total}" in text, f"query={query!r}"
        else:
            assert "Showing" not in text, f"query={query!r}"
            assert "Total:" not in text, f"query={query!r}"


def test_vanished_user_redirects_ac5(client):
    uid = _make_user()
    login_as(client, uid)
    with closing(get_db()) as conn:
        conn.execute("DELETE FROM users WHERE id = %s", (uid,))

    resp = client.get("/expenses")

    assert resp.status_code == 302
    assert resp.headers["Location"] == "/login"
    with client.session_transaction() as sess:
        assert "user_id" not in sess


def test_other_methods_405_ac6(client):
    uid = _make_user()
    _add(uid)
    login_as(client, uid)
    before = _rows()

    assert client.post("/expenses").status_code == 405
    assert client.put("/expenses").status_code == 405
    assert client.delete("/expenses").status_code == 405
    assert _rows() == before
    assert client.get("/expenses/").status_code == 404


def test_nav_expenses_link_ac7(client):
    for url in ("/", "/login", "/register"):
        body = client.get(url).get_data(as_text=True)
        assert _NAV_EXPENSES_RE.search(body) is None, f"url={url!r}"

    uid = _make_user()
    login_as(client, uid)
    for url in ("/profile", "/expenses", "/expenses/add"):
        resp = client.get(url)
        assert resp.status_code == 200, f"url={url!r}"
        assert _NAV_EXPENSES_RE.search(resp.get_data(as_text=True)), f"url={url!r}"


def test_read_only_page_ac8(client):
    uid = _make_user()
    _add(uid, description="lunch")
    _add(uid, category="Bills", day="2026-03-02", description="power")
    login_as(client, uid)

    resp = client.get("/expenses")
    body = resp.get_data(as_text=True)

    assert resp.status_code == 200
    assert re.search(r"/expenses/[0-9]+/(edit|delete)", body) is None
    forms = re.findall(
        r'(<form\b[^>]*\bmethod="(GET|POST)"[^>]*>)(.*?)</form>',
        body,
        re.DOTALL | re.IGNORECASE,
    )
    post_forms = [tag for tag, method, _ in forms if method.upper() == "POST"]
    get_forms = [inner for _, method, inner in forms if method.upper() == "GET"]
    assert len(post_forms) == 1
    assert 'action="/logout"' in post_forms[0]
    assert len(get_forms) == 1
    assert 'name="csrf_token"' not in get_forms[0]
    options = re.findall(r'<option\b[^>]*\bvalue="([^"]*)"[^>]*>(.*?)</option>', body)
    assert [value for value, _ in options] == ["", *CATEGORIES]
    assert options[0][1] == "All categories"
