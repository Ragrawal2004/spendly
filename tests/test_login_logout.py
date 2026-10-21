from database.db import (
    create_user,
    get_user_by_email,
    get_user_by_id,
    init_db,
)


def _make_user(name="Rahul Sharma", email="rahul@example.com", password_hash="hash"):
    init_db()
    return create_user(name, email, password_hash)


def test_get_user_by_email_hit_returns_row_with_hash():
    uid = _make_user()

    row = get_user_by_email("rahul@example.com")

    assert row["id"] == uid
    assert row["name"] == "Rahul Sharma"
    assert row["email"] == "rahul@example.com"
    assert row["password_hash"] == "hash"


def test_get_user_by_email_miss_returns_none():
    _make_user()

    assert get_user_by_email("nobody@example.com") is None


def test_get_user_by_id_hit_returns_row():
    uid = _make_user()

    row = get_user_by_id(uid)

    assert row["id"] == uid
    assert row["name"] == "Rahul Sharma"
    assert row["email"] == "rahul@example.com"


def test_get_user_by_id_miss_returns_none():
    uid = _make_user()

    assert get_user_by_id(uid + 1000) is None


def test_get_user_by_id_row_has_no_password_hash():
    uid = _make_user()

    row = get_user_by_id(uid)

    assert "password_hash" not in row.keys()
