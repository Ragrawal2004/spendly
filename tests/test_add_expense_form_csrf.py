import re
import secrets
from contextlib import closing
from datetime import datetime, timezone

from werkzeug.security import generate_password_hash

# Imported at collection time, so app's startup() demo seed runs before isolated_db drops the tables.
import app  # noqa: F401
from database.db import create_user, get_db, init_db
from helpers import csrf_token, post_form


CSRF_BODY = "Invalid or missing form token. Reload the page and try again."

_TOKEN_RE = re.compile(r'name="csrf_token" value="([^"]+)"')


def _page_token(body):
    match = _TOKEN_RE.search(body)
    return match.group(1) if match else None


def _make_user(name="Rahul Sharma", email="rahul@example.com"):
    init_db()
    return create_user(name, email, generate_password_hash("password123"))


def login_as(client, uid):
    with client.session_transaction() as sess:
        sess["user_id"] = uid
    csrf_token(client)


def _rows(uid=None):
    with closing(get_db()) as conn:
        if uid is None:
            return conn.execute(
                "SELECT id, user_id, amount, category, date, description, created_at "
                "FROM expenses ORDER BY id"
            ).fetchall()
        return conn.execute(
            "SELECT id, user_id, amount, category, date, description, created_at "
            "FROM expenses WHERE user_id = %s ORDER BY id",
            (uid,),
        ).fetchall()


def _user_rows(email):
    with closing(get_db()) as conn:
        return conn.execute("SELECT id FROM users WHERE email = %s", (email,)).fetchall()


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


def _login_form(**over):
    form = {"email": "rahul@example.com", "password": "password123"}
    form.update(over)
    return form


def _register_form(**over):
    form = {
        "name": "Asha Verma",
        "email": "asha@example.com",
        "password": "password123",
        "confirm_password": "password123",
    }
    form.update(over)
    return form


def _assert_csrf_400(resp):
    assert resp.status_code == 400
    assert resp.headers["Content-Type"].startswith("text/plain")
    assert resp.get_data(as_text=True) == CSRF_BODY


# --- POST /expenses/add (AC-8, AC-9, AC-10) ---


def test_add_missing_token_ac8(client):
    uid = _make_user()
    login_as(client, uid)

    resp = client.post("/expenses/add", data=_valid_form())

    _assert_csrf_400(resp)
    assert "Set-Cookie" not in resp.headers
    assert _rows() == []


def test_add_wrong_token_ac9(client):
    uid = _make_user()
    login_as(client, uid)

    resp = client.post(
        "/expenses/add", data=_valid_form(csrf_token=secrets.token_urlsafe(32))
    )

    _assert_csrf_400(resp)
    assert "Set-Cookie" not in resp.headers
    assert _rows() == []


def test_add_valid_token_ac10(client):
    uid = _make_user()
    login_as(client, uid)

    resp = post_form(client, "/expenses/add", _valid_form())

    assert resp.status_code == 303
    assert resp.headers["Location"].endswith("/profile")
    assert len(_rows(uid)) == 1


# --- POST /login (AC-11, AC-12, AC-13) ---


def test_login_missing_token_ac11(client):
    _make_user()
    csrf_token(client)

    resp = client.post("/login", data=_login_form())

    _assert_csrf_400(resp)
    assert "Set-Cookie" not in resp.headers
    follow = client.get("/profile")
    assert follow.status_code == 302
    assert follow.headers["Location"].endswith("/login")


def test_login_wrong_token_ac12(client):
    _make_user()
    csrf_token(client)

    resp = client.post("/login", data=_login_form(csrf_token=secrets.token_urlsafe(32)))

    _assert_csrf_400(resp)
    assert "Set-Cookie" not in resp.headers
    with client.session_transaction() as sess:
        assert "user_id" not in sess


def test_login_valid_token_ac13(client):
    uid = _make_user()

    resp = post_form(client, "/login", _login_form())

    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/profile")
    with client.session_transaction() as sess:
        assert sess["user_id"] == uid


# --- POST /register (AC-14, AC-15, AC-16) ---


def test_register_missing_token_ac14(client):
    csrf_token(client)

    resp = client.post("/register", data=_register_form())

    _assert_csrf_400(resp)
    assert _user_rows("asha@example.com") == []


def test_register_wrong_token_ac15(client):
    csrf_token(client)

    resp = client.post(
        "/register", data=_register_form(csrf_token=secrets.token_urlsafe(32))
    )

    _assert_csrf_400(resp)
    assert _user_rows("asha@example.com") == []


def test_register_valid_token_ac16(client):
    resp = post_form(client, "/register", _register_form())

    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/login?registered=1")
    assert len(_user_rows("asha@example.com")) == 1


# --- POST /logout (AC-17, AC-18, AC-19) ---


def test_logout_missing_token_ac17(client):
    uid = _make_user()
    login_as(client, uid)

    resp = client.post("/logout")

    _assert_csrf_400(resp)
    assert "Set-Cookie" not in resp.headers
    assert client.get("/profile").status_code == 200


def test_logout_wrong_token_ac18(client):
    uid = _make_user()
    login_as(client, uid)

    resp = client.post("/logout", data={"csrf_token": secrets.token_urlsafe(32)})

    _assert_csrf_400(resp)
    assert client.get("/profile").status_code == 200


def test_logout_valid_token_ac19(client):
    uid = _make_user()
    login_as(client, uid)

    resp = post_form(client, "/logout")

    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/")
    with client.session_transaction() as sess:
        assert "user_id" not in sess
        assert "csrf_token" not in sess
