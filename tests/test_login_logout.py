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
