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


def test_app_config_cookie_secure_is_false_outside_production():
    import app as app_module

    assert app_module.app.config["SESSION_COOKIE_SECURE"] is False


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


# --- before_request / context processor (AC-18, AC-19, AC-24, AC-32) ---


def login_as(client, uid):
    with client.session_transaction() as sess:
        sess["user_id"] = uid


def test_ac18_nonexistent_user_id_is_cleared_and_nav_is_logged_out(client):
    login_as(client, 9999)

    response = client.get("/")

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "Sign in" in body
    assert "Get started" in body
    with client.session_transaction() as sess:
        assert "user_id" not in sess


def test_ac19_garbage_session_cookie_renders_login(client):
    client.set_cookie("session", "garbage")

    response = client.get("/login")

    assert response.status_code == 200


def test_ac24_nonexistent_user_id_still_renders_login_form(client):
    login_as(client, 9999)

    response = client.get("/login")

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert 'name="email"' in body
    assert 'name="password"' in body


@pytest.mark.parametrize("bad_value", ["1", [1], True])
def test_ac32_wrong_type_user_id_is_cleared(client, bad_value):
    _make_user()
    login_as(client, bad_value)

    response = client.get("/login")

    assert response.status_code == 200
    with client.session_transaction() as sess:
        assert "user_id" not in sess


# --- login failures and GET (AC-4 to AC-7, AC-9, AC-20, AC-25, AC-27, AC-28, AC-31) ---

GENERIC_ERROR = "Invalid email or password."
BLANK_ERROR = "Please enter your email and password."


def _make_rahul():
    return _make_user(password_hash=generate_password_hash("password123"))


def _post_login(client, email, password):
    return client.post("/login", data={"email": email, "password": password})


def test_ac4_wrong_password_gives_401_and_generic_message(client):
    _make_rahul()

    response = _post_login(client, "rahul@example.com", "wrong-password")

    assert response.status_code == 401
    assert GENERIC_ERROR in response.get_data(as_text=True)
    with client.session_transaction() as sess:
        assert "user_id" not in sess


def test_ac5_unknown_email_gives_401_and_same_message(client):
    _make_rahul()

    response = _post_login(client, "nobody@example.com", "password123")

    assert response.status_code == 401
    assert GENERIC_ERROR in response.get_data(as_text=True)


def test_ac6_wrong_password_and_unknown_email_pages_are_identical(client):
    _make_rahul()

    wrong_password = _post_login(client, "rahul@example.com", "wrong-password")
    unknown_email = _post_login(client, "nobody@example.com", "wrong-password")

    page_a = wrong_password.get_data(as_text=True).replace("rahul@example.com", "EMAIL")
    page_b = unknown_email.get_data(as_text=True).replace("nobody@example.com", "EMAIL")
    assert wrong_password.status_code == unknown_email.status_code == 401
    assert page_a == page_b
    for phrase in ("email not found", "no account", "wrong password"):
        assert phrase not in page_a.lower()


@pytest.mark.parametrize(
    "data",
    [
        {"email": "", "password": "password123"},
        {"email": "   ", "password": "password123"},
        {"password": "password123"},
        {"email": "rahul@example.com", "password": ""},
        {"email": "rahul@example.com"},
    ],
)
def test_ac7_blank_or_missing_fields_give_400(client, data):
    _make_rahul()

    response = client.post("/login", data=data)

    assert response.status_code == 400
    assert BLANK_ERROR in response.get_data(as_text=True)
    with client.session_transaction() as sess:
        assert "user_id" not in sess


def test_ac9_password_with_trailing_space_is_rejected(client):
    _make_rahul()

    response = _post_login(client, "rahul@example.com", "password123 ")

    assert response.status_code == 401
    with client.session_transaction() as sess:
        assert "user_id" not in sess


def test_ac20_query_string_credentials_are_ignored(client):
    _make_rahul()

    response = client.get("/login?email=rahul@example.com&password=password123")

    assert response.status_code == 200
    with client.session_transaction() as sess:
        assert "user_id" not in sess


def test_ac25_unknown_email_through_post_does_one_check(client, monkeypatch):
    import app as app_module

    monkeypatch.setattr(app_module, "get_user_by_email", lambda email: None)
    calls = []
    monkeypatch.setattr(
        app_module,
        "check_password_hash",
        lambda pwhash, password: calls.append((pwhash, password)) or False,
    )

    response = _post_login(client, "nobody@example.com", "password123")

    assert response.status_code == 401
    assert len(calls) == 1


def test_ac27_registered_banner_only_with_query_flag(client):
    with_flag = client.get("/login?registered=1").get_data(as_text=True)
    without_flag = client.get("/login").get_data(as_text=True)

    assert "Account created" in with_flag
    assert "Account created" not in without_flag


@pytest.mark.parametrize(
    "email, password",
    [("a" * 255, "password123"), ("rahul@example.com", "p" * 129)],
)
def test_ac28_oversized_input_through_post_gives_generic_401(client, email, password):
    _make_rahul()

    response = _post_login(client, email, password)

    assert response.status_code == 401
    assert GENERIC_ERROR in response.get_data(as_text=True)


@pytest.mark.parametrize(
    "bad_hash", ["not-a-hash", "hash", "", "x$y$z", "scrypt:bad$s$h"]
)
def test_ac31_malformed_stored_hash_through_post_gives_generic_401(client, bad_hash):
    _make_user(password_hash=bad_hash)

    response = _post_login(client, "rahul@example.com", "password123")

    assert response.status_code == 401
    assert GENERIC_ERROR in response.get_data(as_text=True)


# --- login success (AC-2, AC-3, AC-10, AC-15, AC-21, AC-26, AC-29) ---

from database.db import seed_db


def test_ac2_valid_login_redirects_to_profile_with_only_user_id(client):
    uid = _make_rahul()

    response = _post_login(client, "rahul@example.com", "password123")

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/profile")
    with client.session_transaction() as sess:
        assert dict(sess) == {"user_id": uid}


def test_ac3_email_is_trimmed_and_case_insensitive(client):
    uid = _make_rahul()

    response = _post_login(client, "  Rahul@EXAMPLE.com ", "password123")

    assert response.status_code == 302
    with client.session_transaction() as sess:
        assert sess["user_id"] == uid


def test_ac10_non_ascii_email_registered_then_logs_in_in_other_case(client):
    client.post(
        "/register",
        data={
            "name": "Eve",
            "email": "É@x.com",
            "password": "password123",
            "confirm_password": "password123",
        },
    )

    response = _post_login(client, "É@X.COM", "password123")

    assert response.status_code == 302
    with client.session_transaction() as sess:
        assert "user_id" in sess


def test_ac15_valid_login_while_signed_in_keeps_existing_session(client):
    uid_a = _make_rahul()
    uid_b = create_user("Asha", "asha@example.com", generate_password_hash("secret123"))
    login_as(client, uid_a)

    response = _post_login(client, "asha@example.com", "secret123")

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/profile")
    with client.session_transaction() as sess:
        assert sess["user_id"] == uid_a != uid_b


def test_ac21_login_discards_other_session_data(client):
    uid = _make_rahul()
    with client.session_transaction() as sess:
        sess["junk"] = 1

    _post_login(client, "rahul@example.com", "password123")

    with client.session_transaction() as sess:
        assert dict(sess) == {"user_id": uid}


def test_ac26_seeded_demo_user_can_log_in(client):
    init_db()
    seed_db()

    response = _post_login(client, "demo@spendly.com", "demo123")

    assert response.status_code == 302
    with client.session_transaction() as sess:
        assert "user_id" in sess


def test_ac29_login_cookie_is_httponly_and_samesite_lax(client):
    _make_rahul()

    response = _post_login(client, "rahul@example.com", "password123")

    cookie = response.headers["Set-Cookie"]
    assert "HttpOnly" in cookie
    assert "SameSite=Lax" in cookie


# --- logout (AC-11, AC-12, AC-13, AC-22) ---


def test_ac11_logout_clears_session_and_redirects_to_landing(client):
    uid = _make_rahul()
    login_as(client, uid)

    response = client.post("/logout")

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/")
    with client.session_transaction() as sess:
        assert "user_id" not in sess


def test_ac12_logout_without_session_is_harmless_and_repeatable(client):
    init_db()

    for _ in range(2):
        response = client.post("/logout")

        assert response.status_code == 302
        assert response.headers["Location"].endswith("/")


def test_ac13_get_logout_is_405_and_keeps_session(client):
    uid = _make_rahul()
    login_as(client, uid)

    response = client.get("/logout")

    assert response.status_code == 405
    with client.session_transaction() as sess:
        assert sess["user_id"] == uid


def test_ac22_login_and_logout_leak_no_password_or_hash(client, caplog):
    stored_hash = generate_password_hash("password123")
    _make_user(password_hash=stored_hash)

    with caplog.at_level("DEBUG"):
        responses = [
            _post_login(client, "rahul@example.com", "password123"),
            client.post("/logout"),
        ]

    for response in responses:
        haystack = [response.get_data(as_text=True), *response.headers.getlist("Set-Cookie")]
        for text in haystack:
            assert "password123" not in text
            assert stored_hash not in text
    assert "password123" not in caplog.text
    assert stored_hash not in caplog.text


# --- register redirect (AC-14) ---


def _count_users():
    from contextlib import closing

    from database.db import get_db

    with closing(get_db()) as conn:
        return conn.execute("SELECT COUNT(*) AS n FROM users").fetchone()["n"]


def test_ac14_signed_in_get_login_redirects_to_profile(client):
    uid = _make_rahul()
    login_as(client, uid)

    response = client.get("/login")

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/profile")


def test_ac14_signed_in_get_register_redirects_to_profile(client):
    uid = _make_rahul()
    login_as(client, uid)

    response = client.get("/register")

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/profile")


def test_ac14_signed_in_post_register_redirects_and_creates_no_user(client):
    uid = _make_rahul()
    login_as(client, uid)

    response = client.post(
        "/register",
        data={
            "name": "Priya Patel",
            "email": "priya@example.com",
            "password": "password123",
            "confirm_password": "password123",
        },
    )

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/profile")
    assert _count_users() == 1


# --- templates (AC-1, AC-8, AC-16, AC-17) ---


def test_ac1_login_page_has_fields_and_posts_to_login(client):
    response = client.get("/login")

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert 'name="email"' in body
    assert 'name="password"' in body
    assert re.search(r'<form[^>]*method="POST"[^>]*action="/login"', body)


def test_ac8_failed_login_refills_email_but_never_password(client):
    _make_rahul()

    response = _post_login(client, "rahul@example.com", "wrong-secret-pw")

    body = response.get_data(as_text=True)
    assert re.search(r'<input[^>]*name="email"[^>]*value="rahul@example.com"', body)
    assert "wrong-secret-pw" not in body


def test_ac16_nav_reflects_login_state(client):
    uid = _make_rahul()

    logged_out = client.get("/").get_data(as_text=True)
    assert "Sign in" in logged_out
    assert "Get started" in logged_out
    assert 'action="/logout"' not in logged_out

    login_as(client, uid)
    logged_in = client.get("/").get_data(as_text=True)
    assert "Rahul Sharma" in logged_in
    assert re.search(r'<form[^>]*method="POST"[^>]*action="/logout"', logged_in)
    assert "Get started" not in logged_in


def test_ac17_user_name_is_escaped_in_nav(client):
    uid = _make_user(name="<b>x</b>", password_hash=generate_password_hash("password123"))
    login_as(client, uid)

    body = client.get("/").get_data(as_text=True)

    assert "&lt;b&gt;x&lt;/b&gt;" in body
    assert "<b>x</b>" not in body


def test_ac31_session_user_id_is_int_after_register_and_login(client):
    init_db()
    client.post(
        "/register",
        data={
            "name": "Rahul Sharma",
            "email": "rahul@example.com",
            "password": "password123",
            "confirm_password": "password123",
        },
    )
    _post_login(client, "rahul@example.com", "password123")

    with client.session_transaction() as sess:
        user_id = sess["user_id"]
    assert isinstance(user_id, int)
    assert user_id == get_user_by_email("rahul@example.com")["id"]
    assert client.get("/profile").status_code == 200
