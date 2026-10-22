from contextlib import closing
from datetime import date, datetime, timezone
from decimal import Decimal

import psycopg
import pytest

from werkzeug.datastructures import MultiDict
from werkzeug.security import generate_password_hash

from app import clean_expense, validate_expense
from database.db import create_expense, create_user, get_db, init_db


AMOUNT_FORMAT_ERROR = "Enter a valid amount, like 250 or 99.50."
AMOUNT_ZERO_ERROR = "Amount must be greater than ₹0."
AMOUNT_MAX_ERROR = "Amount must be ₹1,00,00,000 or less."
CATEGORY_ERROR = "Please choose a category."
DATE_FORMAT_ERROR = "Enter a valid date."
DATE_RANGE_ERROR = "Date must be between 1 January 2000 and tomorrow."
DESCRIPTION_LENGTH_ERROR = "Description must be 200 characters or fewer."
DESCRIPTION_CONTROL_ERROR = "Description cannot contain line breaks or control characters."

TODAY = date(2026, 10, 22)

AC5_AMOUNTS = [
    "",
    "abc",
    "-5",
    "+5",
    "1,000",
    "1e3",
    "1.234",
    ".5",
    "5.",
    "nan",
    "inf",
    "2 50",
    "٥",
    "５",
    "250\n",
    "9" * 16,
    "9" * 21,
]


def _make_user(name="Rahul Sharma", email="rahul@example.com"):
    init_db()
    return create_user(name, email, generate_password_hash("password123"))


def login_as(client, uid):
    with client.session_transaction() as sess:
        sess["user_id"] = uid


def _rows(uid=None):
    sql = "SELECT id, user_id, amount, category, date, description, created_at FROM expenses"
    params = ()
    if uid is not None:
        sql += " WHERE user_id = %s"
        params = (uid,)
    with closing(get_db()) as conn:
        return conn.execute(sql + " ORDER BY id", params).fetchall()


def _today():
    return datetime.now(timezone.utc).date()


def _valid_form(**over):
    form = {
        "amount": "250",
        "category": "Food",
        "date": _today().isoformat(),
        "description": "Lunch",
    }
    form.update(over)
    return form


def _validate(amount="250", category="Food", date="2026-10-22", description="Lunch", today=TODAY):
    return validate_expense(amount, category, date, description, today)


# --- pure validation helpers ---


@pytest.mark.parametrize("amount", AC5_AMOUNTS)
def test_invalid_amount_format_ac5(amount):
    assert _validate(amount=amount) == (AMOUNT_FORMAT_ERROR, None)


def test_amount_bounds_ac6():
    for amount in ("0", "0.00"):
        assert _validate(amount=amount) == (AMOUNT_ZERO_ERROR, None)
    for amount in ("10000000.01", "123456789", "999999999999999"):
        assert _validate(amount=amount) == (AMOUNT_MAX_ERROR, None)
    for amount, expected in (
        ("0.01", Decimal("0.01")),
        ("10000000", Decimal("10000000")),
        ("007", Decimal("7")),
    ):
        error, values = _validate(amount=amount)
        assert error is None
        assert isinstance(values["amount"], Decimal)
        assert values["amount"] == expected


def test_category_ac7():
    for category in ("", "food", "FOOD", "Groceries"):
        assert _validate(category=category) == (CATEGORY_ERROR, None)
    for category in ("Food", "Transport", "Bills", "Health", "Entertainment", "Shopping", "Other"):
        error, values = _validate(category=category)
        assert error is None
        assert values["category"] == category


def test_date_rules_ac8():
    for d in ("", "22/10/2026", "2026-1-5", "2026-02-30", "2026-W43-4", "20261022"):
        assert _validate(date=d, today=TODAY) == (DATE_FORMAT_ERROR, None)
    for d in ("1999-12-31", "2026-10-24"):
        assert _validate(date=d, today=TODAY) == (DATE_RANGE_ERROR, None)
    for d, expected in (
        ("2000-01-01", date(2000, 1, 1)),
        ("2024-02-29", date(2024, 2, 29)),
        ("2026-10-23", date(2026, 10, 23)),
    ):
        error, values = _validate(date=d, today=TODAY)
        assert error is None
        assert values["date"] == expected


def test_date_year_rollover_ac9():
    today = date(2026, 12, 31)
    error, values = _validate(date="2027-01-01", today=today)
    assert error is None
    assert values["date"] == date(2027, 1, 1)
    assert _validate(date="2027-01-02", today=today) == (DATE_RANGE_ERROR, None)


def test_description_length_ac10():
    error, values = _validate(description="x" * 200)
    assert error is None
    assert values["description"] == "x" * 200

    assert _validate(description="x" * 201) == (DESCRIPTION_LENGTH_ERROR, None)

    # Length is counted after stripping, which clean_expense does.
    cleaned = clean_expense(MultiDict(_valid_form(date="2026-10-22", description="  " + "x" * 200 + "  ")))
    error, values = validate_expense(*cleaned, today=TODAY)
    assert error is None
    assert values["description"] == "x" * 200


def test_check_order_ac11():
    assert _validate(amount="abc", category="x", date="bad", description="x" * 201) == (
        AMOUNT_FORMAT_ERROR,
        None,
    )
    assert _validate(category="x", date="bad", description="x" * 201) == (CATEGORY_ERROR, None)
    assert _validate(date="bad", description="x" * 201) == (DATE_FORMAT_ERROR, None)
    # The length check runs before the control-character check.
    assert _validate(description="\x00" * 201) == (DESCRIPTION_LENGTH_ERROR, None)


def test_clean_expense_ac25():
    assert clean_expense(MultiDict()) == ("", "", "", "")
    assert clean_expense(MultiDict({"category": " food "}))[1] == "food"


def test_create_expense_roundtrip_ac23(client):
    uid = _make_user()
    expense_id = create_expense(uid, Decimal("99.50"), "Health", date(2026, 10, 5), None)
    assert isinstance(expense_id, int)
    with closing(get_db()) as conn:
        row = conn.execute(
            "SELECT user_id, amount, category, date, description, created_at "
            "FROM expenses WHERE id = %s",
            (expense_id,),
        ).fetchone()
    assert row["user_id"] == uid
    assert row["amount"] == Decimal("99.50")
    assert row["category"] == "Health"
    assert row["date"] == date(2026, 10, 5)
    assert row["description"] is None
    assert row["created_at"] is not None


def test_create_expense_constraints_ac24(client):
    uid = _make_user()
    with pytest.raises(psycopg.errors.CheckViolation):
        create_expense(uid, Decimal("0"), "Food", date(2026, 10, 5), None)
    with pytest.raises(psycopg.errors.CheckViolation):
        create_expense(uid, Decimal("10.00"), "Groceries", date(2026, 10, 5), None)
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        create_expense(uid + 1000, Decimal("10.00"), "Food", date(2026, 10, 5), None)
    assert _rows() == []
