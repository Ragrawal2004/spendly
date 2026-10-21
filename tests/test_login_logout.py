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


# --- resolve_secret_key / session_cookie_secure (AC-23, AC-30) ---

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent


def test_ac23_secret_key_returned_when_set():
    import app as app_module

    env = {"SPENDLY_SECRET_KEY": "abc123"}

    assert app_module.resolve_secret_key(env) == "abc123"


@pytest.mark.parametrize(
    "env",
    [
        {},
        {"SPENDLY_ENV": "development"},
        {"SPENDLY_SECRET_KEY": ""},
    ],
)
def test_ac23_dev_without_key_gets_random_hex(env):
    import app as app_module

    first = app_module.resolve_secret_key(env)
    second = app_module.resolve_secret_key(env)

    assert re.fullmatch(r"[0-9a-f]{64}", first)
    assert re.fullmatch(r"[0-9a-f]{64}", second)
    assert first != second


@pytest.mark.parametrize(
    "env",
    [
        {"SPENDLY_ENV": "production"},
        {"SPENDLY_ENV": "production", "SPENDLY_SECRET_KEY": ""},
    ],
)
def test_ac23_production_without_key_raises(env):
    import app as app_module

    with pytest.raises(RuntimeError) as exc:
        app_module.resolve_secret_key(env)

    assert "SPENDLY_SECRET_KEY" in str(exc.value)


def test_ac23_production_import_without_key_fails_before_db_work(tmp_path):
    db_path = tmp_path / "fresh-dir" / "spendly.db"
    env = os.environ.copy()
    env.pop("SPENDLY_SECRET_KEY", None)
    env["SPENDLY_ENV"] = "production"
    env["SPENDLY_DB"] = str(db_path)

    result = subprocess.run(
        [sys.executable, "-c", "import app"],
        cwd=_REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "RuntimeError" in result.stderr
    assert "SPENDLY_SECRET_KEY" in result.stderr
    assert not db_path.exists()
    assert not db_path.parent.exists()


def test_ac30_cookie_secure_true_in_production():
    import app as app_module

    assert app_module.session_cookie_secure({"SPENDLY_ENV": "production"}) is True


@pytest.mark.parametrize("env", [{}, {"SPENDLY_ENV": "development"}])
def test_ac30_cookie_secure_false_otherwise(env):
    import app as app_module

    assert app_module.session_cookie_secure(env) is False


def test_app_config_has_session_cookie_flags():
    import app as app_module

    assert app_module.app.secret_key
    assert app_module.app.config["SESSION_COOKIE_HTTPONLY"] is True
    assert app_module.app.config["SESSION_COOKIE_SAMESITE"] == "Lax"


# --- clean_login / authenticate (function-level halves of AC-25, AC-28, AC-31) ---

from werkzeug.security import check_password_hash as _real_check_password_hash
from werkzeug.security import generate_password_hash


def _record_checks(monkeypatch):
    import app as app_module

    calls = []

    def recording_check(pwhash, password):
        calls.append((pwhash, password))
        return _real_check_password_hash(pwhash, password)

    monkeypatch.setattr(app_module, "check_password_hash", recording_check)
    return calls


def test_clean_login_strips_and_lowercases_email():
    import app as app_module

    email, _ = app_module.clean_login({"email": "  Rahul@EXAMPLE.com ", "password": "x"})

    assert email == "rahul@example.com"


def test_clean_login_leaves_password_untouched():
    import app as app_module

    _, password = app_module.clean_login({"email": "a@b.com", "password": "  pass word  "})

    assert password == "  pass word  "


def test_clean_login_missing_fields_become_empty_strings():
    import app as app_module

    assert app_module.clean_login({}) == ("", "")


def test_authenticate_valid_credentials_returns_user_row(monkeypatch):
    import app as app_module

    uid = _make_user(password_hash=generate_password_hash("password123"))
    calls = _record_checks(monkeypatch)

    row = app_module.authenticate("rahul@example.com", "password123")

    assert row["id"] == uid
    assert row["email"] == "rahul@example.com"
    assert len(calls) == 1


def test_authenticate_wrong_password_returns_none_after_one_check(monkeypatch):
    import app as app_module

    _make_user(password_hash=generate_password_hash("password123"))
    calls = _record_checks(monkeypatch)

    assert app_module.authenticate("rahul@example.com", "wrong-password") is None
    assert len(calls) == 1


def test_ac25_unknown_email_does_one_check_and_returns_none(monkeypatch):
    import app as app_module

    monkeypatch.setattr(app_module, "get_user_by_email", lambda email: None)
    calls = []
    monkeypatch.setattr(
        app_module,
        "check_password_hash",
        lambda pwhash, password: calls.append((pwhash, password)) or False,
    )

    assert app_module.authenticate("nobody@example.com", "password123") is None
    assert len(calls) == 1


@pytest.mark.parametrize(
    "email, password",
    [("a" * 255, "password123"), ("rahul@example.com", "p" * 129)],
)
def test_ac28_oversized_input_returns_none_without_lookup(monkeypatch, email, password):
    import app as app_module

    def fail_lookup(_email):
        raise AssertionError("must not look the user up")

    monkeypatch.setattr(app_module, "get_user_by_email", fail_lookup)
    calls = _record_checks(monkeypatch)

    assert app_module.authenticate(email, password) is None
    assert len(calls) == 1


@pytest.mark.parametrize(
    "bad_hash", ["not-a-hash", "hash", "", "x$y$z", "scrypt:bad$s$h"]
)
def test_ac31_malformed_stored_hash_returns_none(monkeypatch, bad_hash):
    import app as app_module

    _make_user(password_hash=bad_hash)
    calls = _record_checks(monkeypatch)

    assert app_module.authenticate("rahul@example.com", "password123") is None
    assert len(calls) == 1
