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


_URLSAFE_RE = re.compile(r"[A-Za-z0-9_-]+")
_POST_FORM_RE = re.compile(
    r'<form\b[^>]*\bmethod="post"[^>]*>(.*?)</form>', re.IGNORECASE | re.DOTALL
)


def _session_token(client):
    # Reads the token without creating one (unlike helpers.csrf_token).
    with client.session_transaction() as sess:
        return sess.get("csrf_token")


def _sets_session_cookie(resp):
    return any(c.startswith("session=") for c in resp.headers.getlist("Set-Cookie"))


def _real_login(client, email="rahul@example.com"):
    page = client.get("/login")
    token = _page_token(page.get_data(as_text=True))
    resp = client.post("/login", data=_login_form(email=email, csrf_token=token))
    assert resp.status_code == 302
    return token


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


# --- Token lifecycle and checking rules (AC-20, AC-22 to AC-31) ---


def test_login_register_pages_issue_token_ac20(client):
    fresh = app.app.test_client()
    for c, url in ((client, "/login"), (fresh, "/register")):
        resp = c.get(url)

        assert resp.status_code == 200
        sets_cookie = _sets_session_cookie(resp)
        assert sets_cookie, f"{url} set no session cookie"
        page_token = _page_token(resp.get_data(as_text=True))
        session_token = _session_token(c)
        is_str = isinstance(page_token, str)
        assert is_str, f"{url} has no hidden csrf_token"
        same = page_token == session_token
        assert same, "page token differs from session token"
        token_len = len(page_token)
        assert token_len >= 43
        urlsafe = _URLSAFE_RE.fullmatch(page_token) is not None
        assert urlsafe, "token has characters outside URL-safe base64"


def test_login_rotates_token_ac22(client):
    _make_user()

    t1 = _real_login(client)

    t2 = _session_token(client)
    is_str = isinstance(t2, str) and len(t2) >= 43
    assert is_str, "login left no token in the session"
    rotated = t2 != t1
    assert rotated, "login did not rotate the token"
    resp = client.post("/logout", data={"csrf_token": t1})
    _assert_csrf_400(resp)


def test_token_dies_at_logout_ac23(client):
    uid = _make_user()
    login_as(client, uid)
    t = csrf_token(client)

    out = client.post("/logout", data={"csrf_token": t})
    assert out.status_code == 302

    resp = client.post("/login", data=_login_form(csrf_token=t))
    _assert_csrf_400(resp)


def test_failed_login_keeps_token_ac24(client):
    _make_user()
    t = csrf_token(client)

    resp = client.post("/login", data=_login_form(password="wrongpass1", csrf_token=t))

    assert resp.status_code == 401
    assert "Invalid email or password." in resp.get_data(as_text=True)
    same = _session_token(client) == t
    assert same, "failed login changed the session token"


def test_other_session_token_rejected_ac25(client):
    # Both sessions get their tokens from the app (real login), not from the test helper.
    _make_user()
    _make_user(name="Asha Verma", email="asha@example.com")
    client_b = app.app.test_client()
    _real_login(client)
    _real_login(client_b, email="asha@example.com")
    token_a = _session_token(client)

    resp = client_b.post("/expenses/add", data=_valid_form(csrf_token=token_a))

    _assert_csrf_400(resp)
    assert _rows() == []


def test_malformed_tokens_rejected_ac26(client):
    uid = _make_user()
    login_as(client, uid)
    t = csrf_token(client)

    for bad in ("", "é" * 43, "x" * 10_000, t + " "):
        resp = client.post("/expenses/add", data=_valid_form(csrf_token=bad))
        _assert_csrf_400(resp)
        assert _rows() == []


def test_absent_session_token_never_matches_ac27(client):
    uid = _make_user()
    with client.session_transaction() as sess:
        sess["user_id"] = uid
    assert _session_token(client) is None

    empty = client.post("/expenses/add", data=_valid_form(csrf_token=""))
    _assert_csrf_400(empty)
    missing = client.post("/expenses/add", data=_valid_form())
    _assert_csrf_400(missing)
    assert _rows() == []


def test_csrf_before_load_current_user_ac28(client):
    with client.session_transaction() as sess:
        sess["user_id"] = 999_999
    csrf_token(client)

    resp = post_form(client, "/expenses/add", _valid_form())

    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/login")
    with client.session_transaction() as sess:
        assert "user_id" not in sess
    assert _rows() == []


def test_405_and_404_not_checked_ac29(client):
    uid = _make_user()
    login_as(client, uid)

    assert client.put("/expenses/add").status_code == 405
    assert client.delete("/expenses/add").status_code == 405
    assert client.post("/profile").status_code == 405
    assert client.post("/no-such-page").status_code == 404


def test_formless_pages_set_no_cookie_ac30(client):
    for url in ("/", "/terms", "/privacy"):
        resp = client.get(url)
        assert resp.status_code == 200
        assert "Set-Cookie" not in resp.headers, url


def test_every_post_form_has_token_ac31(client):
    uid = _make_user()
    signed_in = app.app.test_client()
    login_as(signed_in, uid)
    pages = ((client, "/login"), (client, "/register"), (signed_in, "/profile"))

    for c, url in pages:
        resp = c.get(url)
        assert resp.status_code == 200
        session_token = _session_token(c)
        has_token = isinstance(session_token, str) and session_token != ""
        assert has_token, f"no session token after {url}"
        forms = _POST_FORM_RE.findall(resp.get_data(as_text=True))
        assert len(forms) >= 1, f"{url} has no POST form"
        for form in forms:
            same = _page_token(form) == session_token
            assert same, f"a POST form on {url} lacks the session token"


# --- Step 4 rule and caching of token pages (AC-34, AC-35) ---


def test_profile_after_real_login_no_set_cookie_ac34(client):
    _make_user()
    _real_login(client)

    resp = client.get("/profile")

    assert resp.status_code == 200
    assert "Set-Cookie" not in resp.headers


def test_login_register_no_store_ac35(client):
    fresh = app.app.test_client()
    for c, url in ((client, "/login"), (fresh, "/register")):
        resp = c.get(url)
        assert resp.status_code == 200
        assert resp.headers.get("Cache-Control") == "no-store", url
