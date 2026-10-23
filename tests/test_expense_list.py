import html
import re
from contextlib import closing
from datetime import date
from decimal import Decimal
from urllib.parse import parse_qs, urlsplit

from werkzeug.datastructures import MultiDict
from werkzeug.security import generate_password_hash

import app
from app import clean_expense_filters, page_window
from database.db import (
    _like_pattern,
    create_expense,
    create_user,
    get_db,
    get_filtered_summary,
)
from helpers import csrf_token


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
