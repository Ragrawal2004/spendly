import sqlite3

import pytest
from werkzeug.security import check_password_hash

import app as app_module
from database.db import get_db

VALID = {"name": "Rahul Sharma", "email": "rahul@example.com", "password": "password123"}
DUP = "An account with this email already exists."


def post(client, **over):
    data = {**VALID, **over}
    return client.post("/register", data={k: v for k, v in data.items() if v is not None})


@pytest.fixture
def spy(monkeypatch):
    """Wrap app.create_user, recording any exception it raises."""
    raised = []
    real = app_module.create_user

    def wrapper(*a, **k):
        try:
            return real(*a, **k)
        except Exception as e:
            raised.append(e)
            raise

    monkeypatch.setattr(app_module, "create_user", wrapper)
    return raised


def rows():
    conn = get_db()
    try:
        return conn.execute("SELECT * FROM users").fetchall()
    finally:
        conn.close()


def test_ac01_get_form(client):
    r = client.get("/register")
    assert r.status_code == 200
    for f in ("name", "email", "password"):
        assert f'name="{f}"' in r.get_data(as_text=True)


def test_ac02_success(client):
    r = post(client)
    assert r.status_code == 302 and r.headers["Location"].endswith("/login?registered=1")
    u = rows()
    assert len(u) == 1 and u[0]["name"] == "Rahul Sharma" and u[0]["email"] == "rahul@example.com"


def test_ac03_hashed(client):
    post(client)
    h = rows()[0]["password_hash"]
    assert h != "password123" and check_password_hash(h, "password123")


def test_ac04_email_normalised(client):
    post(client, email="  Rahul@Example.COM ")
    assert rows()[0]["email"] == "rahul@example.com"


@pytest.mark.parametrize("email", ["RAHUL@example.com", " rahul@example.com "])
def test_ac05_06_duplicate(client, spy, email):
    post(client)
    assert spy == []
    r = post(client, email=email)
    assert len(spy) == 1 and isinstance(spy[0], sqlite3.IntegrityError)
    assert r.status_code == 400 and DUP in r.get_data(as_text=True)
    assert len(rows()) == 1


@pytest.mark.parametrize("name", ["", "   ", "\t\n"])
def test_ac07_blank_name(client, name):
    r = post(client, name=name)
    assert r.status_code == 400 and "Please enter your name." in r.get_data(as_text=True)
    assert rows() == []


def test_ac08_name_length(client):
    r = post(client, name="a" * 101)
    assert r.status_code == 400 and "Name must be 100 characters or fewer." in r.get_data(as_text=True)
    assert post(client, name="a" * 100).status_code == 302


@pytest.mark.parametrize(
    "email", ["", "plain", "a@", "@b.com", "a@b", "a@@b.com", "a b@c.com", "a@.com", "a@b.com."]
)
def test_ac09_bad_email(client, email):
    r = post(client, email=email)
    assert r.status_code == 400 and "Please enter a valid email address." in r.get_data(as_text=True)
    assert rows() == []


def test_ac10_password_length(client):
    r = post(client, password="a" * 7)
    assert r.status_code == 400 and "at least 8" in r.get_data(as_text=True)
    r = post(client, password="a" * 129)
    assert r.status_code == 400 and "128 characters or fewer" in r.get_data(as_text=True)
    assert post(client, email="a@x.com", password="a" * 8).status_code == 302
    assert post(client, email="b@x.com", password="a" * 128).status_code == 302


def test_ac11_missing_password(client):
    r = post(client, password=None)
    assert r.status_code == 400 and "at least 8" in r.get_data(as_text=True)


def test_ac12_refill_no_password(client):
    r = post(client, name="Asha", email="asha@example.com", password="Zq9x-k7")
    html = r.get_data(as_text=True)
    assert r.status_code == 400
    assert "at least 8" in html
    assert 'value="Asha"' in html
    assert 'value="asha@example.com"' in html
    assert "Zq9x-k7" not in html
    assert rows() == []


def test_ac13_escaped(client):
    r = post(client, name="<script>alert(1)</script>", password="a" * 7)
    html = r.get_data(as_text=True)
    assert r.status_code == 400
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html and "<script>alert(1)" not in html


def test_ac14_double_submit(client, spy):
    assert post(client).status_code == 302
    assert spy == []
    r = post(client)
    assert len(spy) == 1 and isinstance(spy[0], sqlite3.IntegrityError)
    assert r.status_code == 400 and DUP in r.get_data(as_text=True)
    assert len(rows()) == 1


def test_ac15_integrity_error(client, monkeypatch):
    def boom(*a, **k):
        raise sqlite3.IntegrityError("x")

    monkeypatch.setattr(app_module, "create_user", boom)
    r = post(client)
    assert r.status_code == 400 and DUP in r.get_data(as_text=True)


def test_ac16_login_banner(client):
    assert "Account created" in client.get("/login?registered=1").get_data(as_text=True)
    assert "Account created" not in client.get("/login").get_data(as_text=True)


def test_ac17_no_secret_leak(client, caplog):
    r = post(client, password="Zq9x-secret-1")
    h = rows()[0]["password_hash"]
    out = r.get_data(as_text=True) + caplog.text
    assert "Zq9x-secret-1" not in out and h not in out
    assert h not in r.get_data(as_text=True)


def test_ac18_unicode_duplicate(client):
    assert post(client, email="É@x.com").status_code == 302
    for e in ("é@x.com", "É@X.COM"):
        r = post(client, email=e)
        assert r.status_code == 400 and DUP in r.get_data(as_text=True)
    assert len(rows()) == 1


def test_ac19_password_spaces(client):
    post(client, password="  password123  ")
    h = rows()[0]["password_hash"]
    assert check_password_hash(h, "  password123  ") and not check_password_hash(h, "password123")


def test_ac20_name_stripped(client):
    post(client, name="  Rahul Sharma  ")
    assert rows()[0]["name"] == "Rahul Sharma"


def test_ac21_get_creates_nothing(client):
    r = client.get("/register?name=Rahul&email=rahul@example.com&password=password123")
    assert r.status_code == 200 and rows() == []
