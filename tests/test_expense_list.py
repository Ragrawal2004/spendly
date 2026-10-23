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


def _three_categories(uid):
    _add(uid, amount="10.00", category="Food", day="2026-03-01", description="food-1")
    _add(uid, amount="20.00", category="Bills", day="2026-03-02", description="bills-1")
    _add(uid, amount="5.50", category="Food", day="2026-03-03", description="food-2")


def _four_dates(uid):
    _add(uid, day="2026-03-31", description="mar-31")
    _add(uid, day="2026-04-01", description="apr-01")
    _add(uid, day="2026-04-30", description="apr-30")
    _add(uid, day="2026-05-01", description="may-01")


def test_category_filter_ac9(client):
    uid = _make_user()
    _three_categories(uid)
    login_as(client, uid)

    resp = client.get("/expenses?category=Food")
    body = resp.get_data(as_text=True)

    assert resp.status_code == 200
    assert _listed(body) == ["food-2", "food-1"]
    text = _text(body)
    assert "Showing 1-2 of 2" in text
    assert "Total: \u20b915.50" in text
    assert _selected_option(body) == "Food"


def test_invalid_category_ignored_ac10(client):
    uid = _make_user()
    _three_categories(uid)
    login_as(client, uid)

    for value in ("food", "Groceries", "Food' OR '1'='1", " "):
        resp = client.get("/expenses", query_string={"category": value})
        body = resp.get_data(as_text=True)
        assert resp.status_code == 200, f"category={value!r}"
        assert _listed(body) == ["food-2", "bills-1", "food-1"], f"category={value!r}"
        assert _selected_option(body) == "", f"category={value!r}"


def test_date_range_inclusive_ac11(client):
    uid = _make_user()
    _four_dates(uid)
    login_as(client, uid)

    resp = client.get("/expenses?date_from=2026-04-01&date_to=2026-04-30")
    body = resp.get_data(as_text=True)

    assert resp.status_code == 200
    assert _listed(body) == ["apr-30", "apr-01"]
    assert _input_value(body, "date_from") == "2026-04-01"
    assert _input_value(body, "date_to") == "2026-04-30"


def test_single_date_bounds_ac12(client):
    uid = _make_user()
    _four_dates(uid)
    login_as(client, uid)

    resp = client.get("/expenses?date_from=2026-04-30")
    assert _listed(resp.get_data(as_text=True)) == ["may-01", "apr-30"]

    resp = client.get("/expenses?date_to=2026-04-01")
    assert _listed(resp.get_data(as_text=True)) == ["apr-01", "mar-31"]

    resp = client.get("/expenses?date_from=2026-04-01&date_to=2026-04-01")
    assert _listed(resp.get_data(as_text=True)) == ["apr-01"]


def test_reversed_dates_no_match_ac13(client):
    uid = _make_user()
    _four_dates(uid)
    login_as(client, uid)

    resp = client.get("/expenses?date_from=2026-05-01&date_to=2026-04-01")
    body = resp.get_data(as_text=True)

    assert resp.status_code == 200
    assert "No expenses match these filters." in _text(body)
    assert "<table" not in body


def test_invalid_dates_ignored_ac14(client):
    uid = _make_user()
    _four_dates(uid)
    login_as(client, uid)
    everything = ["may-01", "apr-30", "apr-01", "mar-31"]

    for name in ("date_from", "date_to"):
        for value in (
            "2026-02-30",
            "2026-4-1",
            "yesterday",
            "2026-04-01T00:00",
            "\uff12\uff10\uff12\uff16-04-01",
            "0000-01-01",
        ):
            resp = client.get("/expenses", query_string={name: value})
            body = resp.get_data(as_text=True)
            assert resp.status_code == 200, f"{name}={value!r}"
            assert _listed(body) == everything, f"{name}={value!r}"
            assert _input_value(body, name) == "", f"{name}={value!r}"


def test_search_case_insensitive_ac15(client):
    uid = _make_user()
    _add(uid, day="2026-03-01", description="Team lunch")
    _add(uid, day="2026-03-02", description="LUNCHBOX")
    _add(uid, day="2026-03-03", description="Dinner")
    _add(uid, day="2026-03-04")
    login_as(client, uid)

    resp = client.get("/expenses?q=lunch")
    assert _listed(resp.get_data(as_text=True)) == ["LUNCHBOX", "Team lunch"]

    resp = client.get("/expenses", query_string={"q": "  lunch  "})
    body = resp.get_data(as_text=True)
    assert _listed(body) == ["LUNCHBOX", "Team lunch"]
    assert _input_value(body, "q") == "lunch"


def test_search_percent_literal_ac16(client):
    uid = _make_user()
    _add(uid, day="2026-03-01", description="50% off shoes")
    _add(uid, day="2026-03-02", description="500 rupees")
    _add(uid, day="2026-03-03", description="5 0 %")
    _add(uid, day="2026-03-04", description="Paid 50")
    login_as(client, uid)

    resp = client.get("/expenses", query_string={"q": "50%"})

    assert resp.status_code == 200
    assert _listed(resp.get_data(as_text=True)) == ["50% off shoes"]


def test_search_underscore_backslash_ac17(client):
    uid = _make_user()
    _add(uid, day="2026-03-01", description="a_b")
    _add(uid, day="2026-03-02", description="axb")
    _add(uid, day="2026-03-03", description=r"C:\temp")
    _add(uid, day="2026-03-04", description=r"100\%")
    _add(uid, day="2026-03-05", description="plain")
    login_as(client, uid)

    expected = {
        "a_b": ["a_b"],
        "\\": [r"100\%", r"C:\temp"],
        r"\%": [r"100\%"],
        "_": ["a_b"],
    }
    for value, listed in expected.items():
        resp = client.get("/expenses", query_string={"q": value})
        assert resp.status_code == 200, f"q={value!r}"
        assert _listed(resp.get_data(as_text=True)) == listed, f"q={value!r}"


def test_search_length_limits_ac18(client):
    uid = _make_user()
    long_description = "long-" * 20
    assert len(long_description) == 100
    _add(uid, day="2026-03-01", description="first")
    _add(uid, day="2026-03-02", description="second")
    _add(uid, day="2026-03-03", description="third")
    _add(uid, day="2026-03-04", description=long_description)
    login_as(client, uid)
    everything = [long_description, "third", "second", "first"]

    resp = client.get("/expenses", query_string={"q": "   "})
    body = resp.get_data(as_text=True)
    assert _listed(body) == everything
    assert "No expenses match" not in body

    resp = client.get("/expenses", query_string={"q": "x" * 101})
    body = resp.get_data(as_text=True)
    assert _listed(body) == everything
    assert _input_value(body, "q") == ""

    resp = client.get("/expenses", query_string={"q": long_description})
    assert _listed(resp.get_data(as_text=True)) == [long_description]


def test_search_control_chars_ac19(client):
    uid = _make_user()
    _add(uid, day="2026-03-01", description="ab")
    _add(uid, day="2026-03-02", description="a b")
    login_as(client, uid)

    for value in ("a\x00b", "a\nb", "\x7f"):
        resp = client.get("/expenses", query_string={"q": value})
        assert resp.status_code == 200, f"q={value!r}"
        assert _listed(resp.get_data(as_text=True)) == ["a b", "ab"], f"q={value!r}"


def test_filters_combine_ac20(client):
    uid = _make_user()
    _add(uid, category="Food", day="2026-04-01", description="Lunch first")
    _add(uid, category="Food", day="2026-04-10", description="team lunch")
    _add(uid, category="Food", day="2026-04-30", description="LUNCH last")
    _add(uid, category="Bills", day="2026-04-10", description="lunch bill")
    _add(uid, category="Food", day="2026-03-31", description="lunch early")
    _add(uid, category="Food", day="2026-05-01", description="lunch late")
    _add(uid, category="Food", day="2026-04-15", description="dinner")
    login_as(client, uid)

    resp = client.get(
        "/expenses?category=Food&date_from=2026-04-01&date_to=2026-04-30&q=lunch"
    )

    assert resp.status_code == 200
    assert _listed(resp.get_data(as_text=True)) == ["LUNCH last", "team lunch", "Lunch first"]


def _table_state():
    with closing(get_db()) as conn:
        return conn.execute(
            "SELECT (SELECT count(*) FROM users) AS users, "
            "(SELECT count(*) FROM expenses) AS expenses, "
            "to_regclass('public.users') IS NOT NULL AS users_exists, "
            "to_regclass('public.expenses') IS NOT NULL AS expenses_exists"
        ).fetchone()


def test_injection_strings_harmless_ac21(client):
    a = _make_user("a@example.com")
    b = _make_user("b@example.com")
    a_descriptions = ["50% off", "100%", "plain one", "plain two"]
    for i, description in enumerate(a_descriptions, start=1):
        _add(a, day=f"2026-03-0{i}", description=description)
    b_tokens = ["zq-b-7781", "zq-b-7782"]
    for token in b_tokens:
        _add(b, description=token)
    login_as(client, a)
    before = _table_state()
    assert before["users_exists"] and before["expenses_exists"]

    values = (
        "' OR 1=1 --",
        "'; DROP TABLE expenses; --",
        "<script>alert(1)</script>",
        "%' OR '1'='1",
        "%",
    )
    for name in ("category", "date_from", "date_to", "q", "page"):
        for value in values:
            resp = client.get("/expenses", query_string={name: value})
            body = resp.get_data(as_text=True)
            assert resp.status_code == 200, f"{name}={value!r}"
            for token in b_tokens:
                assert token not in body, f"{name}={value!r}"
            assert "<script>alert(1)" not in body, f"{name}={value!r}"
            if name == "q":
                expected = {d for d in a_descriptions if value in d}
            else:
                expected = set(a_descriptions)
            assert set(_listed(body)) == expected, f"{name}={value!r}"

    assert _table_state() == before


def test_no_expenses_beats_no_match_ac31(client):
    uid = _make_user()
    login_as(client, uid)

    resp = client.get("/expenses?q=anything&category=Food")
    body = resp.get_data(as_text=True)

    assert resp.status_code == 200
    block = _empty_block(body)
    assert block is not None
    assert "No expenses yet." in block
    assert "No expenses match these filters." not in body


def test_no_match_empty_state_ac32(client):
    uid = _make_user()
    _add(uid, category="Bills", description="power")
    _add(uid, category="Bills", day="2026-03-02", description="water")
    login_as(client, uid)

    resp = client.get("/expenses?category=Food")
    body = resp.get_data(as_text=True)

    assert resp.status_code == 200
    block = _empty_block(body)
    assert block is not None
    assert "No expenses match these filters." in block
    assert _link(block, "Clear filters") == "/expenses"
    assert "<table" not in body
    assert "Showing" not in body
    assert "Total:" not in body


def test_escaping_ac33(client):
    uid = _make_user()
    _add(uid, description="<script>alert(1)</script> & \u202eabc")
    login_as(client, uid)

    body = client.get("/expenses").get_data(as_text=True)
    assert "<bdi>&lt;script&gt;alert(1)&lt;/script&gt; &amp; \u202eabc</bdi>" in body
    assert "<script>alert(1)" not in body

    resp = client.get("/expenses", query_string={"q": "<b>x</b>"})
    body = resp.get_data(as_text=True)
    assert resp.status_code == 200
    q_inputs = [tag for tag in re.findall(r"<input\b[^>]*>", body) if 'name="q"' in tag]
    assert len(q_inputs) == 1
    assert 'value="&lt;b&gt;x&lt;/b&gt;"' in q_inputs[0]
    assert "<b>x</b>" not in body
    assert _listed(body) == []


def _twenty_five(uid):
    # e00 is the oldest (2026-03-01) and e24 the newest; every date is distinct.
    for i in range(25):
        _add(uid, day=date.fromordinal(date(2026, 3, 1).toordinal() + i).isoformat(),
             description=f"e{i:02d}")


_PAGE_1 = [f"e{i:02d}" for i in range(24, 4, -1)]
_PAGE_2 = [f"e{i:02d}" for i in range(4, -1, -1)]


def test_total_covers_all_pages_ac22(client):
    uid = _make_user()
    _add(uid, amount="0.10", day="2026-01-01")
    for i in range(24):
        _add(uid, amount="1000.00",
             day=date.fromordinal(date(2026, 1, 2).toordinal() + i).isoformat())
    _add(uid, amount="1234.50", day="2026-02-01")
    login_as(client, uid)

    resp = client.get("/expenses")
    body = resp.get_data(as_text=True)

    assert resp.status_code == 200
    assert len(_listed(body)) == 20
    text = _text(body)
    assert "Showing 1-20 of 26" in text
    assert "Total: ₹25,234.60" in text


def test_first_page_ac24(client):
    uid = _make_user()
    _twenty_five(uid)
    login_as(client, uid)

    resp = client.get("/expenses")
    body = resp.get_data(as_text=True)

    assert resp.status_code == 200
    assert resp.headers.get("Cache-Control") == "no-store"
    assert _listed(body) == _PAGE_1
    text = _text(body)
    assert "Showing 1-20 of 25" in text
    assert "Page 1 of 2" in text
    next_href = _link(body, "Next")
    assert next_href is not None
    assert urlsplit(next_href).path == "/expenses"
    assert _query(next_href) == {"page": ["2"]}
    assert _link(body, "Previous") is None


def test_last_page_ac25(client):
    uid = _make_user()
    _twenty_five(uid)
    login_as(client, uid)

    first = _listed(client.get("/expenses").get_data(as_text=True))
    resp = client.get("/expenses?page=2")
    body = resp.get_data(as_text=True)

    assert resp.status_code == 200
    assert _listed(body) == _PAGE_2
    text = _text(body)
    assert "Showing 21-25 of 25" in text
    assert "Page 2 of 2" in text
    prev_href = _link(body, "Previous")
    assert prev_href is not None
    assert urlsplit(prev_href).path == "/expenses"
    assert _query(prev_href) == {"page": ["1"]}
    assert _link(body, "Next") is None
    both = first + _listed(body)
    assert len(both) == 25
    assert sorted(both) == [f"e{i:02d}" for i in range(25)]


def test_invalid_page_ac26(client):
    uid = _make_user()
    _twenty_five(uid)
    login_as(client, uid)

    for value in ("0", "-1", "abc", "1.5", " ", "٢", "1234567890"):
        resp = client.get("/expenses", query_string={"page": value})
        body = resp.get_data(as_text=True)
        assert resp.status_code == 200, f"page={value!r}"
        assert "Showing 1-20 of 25" in _text(body), f"page={value!r}"
        assert _listed(body) == _PAGE_1, f"page={value!r}"


def test_page_clamped_ac27(client):
    uid = _make_user()
    _twenty_five(uid)
    login_as(client, uid)

    resp = client.get("/expenses?page=99")
    body = resp.get_data(as_text=True)

    assert resp.status_code == 200
    assert _listed(body) == _PAGE_2
    text = _text(body)
    assert "Showing 21-25 of 25" in text
    assert "Page 2 of 2" in text

    resp = client.get("/expenses?page=999999999")
    body = resp.get_data(as_text=True)

    assert resp.status_code == 200
    assert _listed(body) == _PAGE_2
    assert "Page 2 of 2" in _text(body)

    empty = _make_user("empty@example.com")
    login_as(client, empty)
    resp = client.get("/expenses?page=5")
    body = resp.get_data(as_text=True)

    assert resp.status_code == 200
    block = _empty_block(body)
    assert block is not None
    assert "No expenses yet." in block


def test_twenty_rows_one_page_ac28(client):
    uid = _make_user()
    for i in range(20):
        _add(uid, day=date.fromordinal(date(2026, 3, 1).toordinal() + i).isoformat(),
             description=f"e{i:02d}")
    login_as(client, uid)

    body = client.get("/expenses").get_data(as_text=True)
    text = _text(body)
    assert "Showing 1-20 of 20" in text
    assert _link(body, "Previous") is None
    assert _link(body, "Next") is None
    assert "Page 1 of" not in text

    _add(uid, day="2026-03-21", description="e20")
    body = client.get("/expenses").get_data(as_text=True)
    assert "Page 1 of 2" in _text(body)
    assert _link(body, "Next") is not None


def test_next_link_keeps_filters_ac29(client):
    uid = _make_user()
    for i in range(1, 26):
        _add(uid, category="Food", day=f"2026-04-{i:02d}", description=f"item {i:02d} 50% & more")
    login_as(client, uid)

    resp = client.get("/expenses", query_string={
        "category": "Food", "date_from": "2026-04-01", "date_to": "2026-04-30",
        "q": "50% & more",
    })
    body = resp.get_data(as_text=True)

    assert resp.status_code == 200
    raw = re.search(r'<a\b[^>]*\bhref="([^"]*)"[^>]*>\s*Next\s*</a>', body)
    assert raw is not None
    assert "&amp;" in raw.group(1)
    assert re.search(r"&(?!amp;)", raw.group(1)) is None
    href = html.unescape(raw.group(1))
    assert _query(href) == {
        "category": ["Food"], "date_from": ["2026-04-01"], "date_to": ["2026-04-30"],
        "q": ["50% & more"], "page": ["2"],
    }

    resp = client.get(href)
    body = resp.get_data(as_text=True)
    assert resp.status_code == 200
    assert _listed(body) == [f"item {i:02d} 50% & more" for i in range(5, 0, -1)]
    assert "Showing 21-25 of 25" in _text(body)
    assert _selected_option(body) == "Food"
    assert _input_value(body, "date_from") == "2026-04-01"
    assert _input_value(body, "date_to") == "2026-04-30"
    assert _input_value(body, "q") == "50% & more"


def test_next_link_drops_junk_ac30(client):
    uid = _make_user()
    _twenty_five(uid)
    login_as(client, uid)

    resp = client.get("/expenses?page=1&user_id=7&foo=bar&category=food&q=")
    body = resp.get_data(as_text=True)

    assert resp.status_code == 200
    next_href = _link(body, "Next")
    assert next_href is not None
    assert _query(next_href) == {"page": ["2"]}
