import re
from contextlib import closing

from werkzeug.security import generate_password_hash

from database.db import create_user, get_db, init_db


def _make_user(name="Rahul Sharma", email="rahul@example.com"):
    init_db()
    return create_user(name, email, generate_password_hash("password123"))


def login_as(client, uid):
    with client.session_transaction() as sess:
        sess["user_id"] = uid


def _add_expense(uid, amount, category, date, description=None):
    with closing(get_db()) as conn:
        with conn:
            cur = conn.execute(
                "INSERT INTO expenses (user_id, amount, category, date, description) "
                "VALUES (?, ?, ?, ?, ?)",
                (uid, amount, category, date, description),
            )
    return cur.lastrowid


def _set_created_at(uid, value):
    with closing(get_db()) as conn:
        with conn:
            conn.execute("UPDATE users SET created_at = ? WHERE id = ?", (value, uid))


NAV_PROFILE_LINK = re.compile(
    r'<a\b(?=[^>]*\bhref="/profile")(?=[^>]*\bclass="nav-user")[^>]*>'
)


# --- nav (Task 1; AC-20 nav half) ---


def test_nav_user_name_links_to_profile(client):
    uid = _make_user()
    login_as(client, uid)

    body = client.get("/").get_data(as_text=True)

    assert NAV_PROFILE_LINK.search(body)
