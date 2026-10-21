import os
import secrets
import sqlite3

from flask import Flask, redirect, render_template, request, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from database.db import (
    create_user,
    get_user_by_email,
    get_user_by_id,
    init_db,
    seed_db,
)


def resolve_secret_key(env):
    key = env.get("SPENDLY_SECRET_KEY")
    if key:
        return key
    if env.get("SPENDLY_ENV") == "production":
        raise RuntimeError("SPENDLY_SECRET_KEY must be set when SPENDLY_ENV=production")
    return secrets.token_hex(32)


def session_cookie_secure(env):
    return env.get("SPENDLY_ENV") == "production"


app = Flask(__name__)
app.secret_key = resolve_secret_key(os.environ)
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=session_cookie_secure(os.environ),
)

_DUMMY_PASSWORD_HASH = generate_password_hash("spendly-dummy-password")


def startup():
    with app.app_context():
        init_db()
        if os.environ.get("SPENDLY_ENV") != "production":
            seed_db()


startup()


# ------------------------------------------------------------------ #
# Routes                                                              #
# ------------------------------------------------------------------ #

@app.route("/")
def landing():
    return render_template("landing.html")


def clean_registration(form):
    name = form.get("name", "").strip()
    email = form.get("email", "").strip().lower()
    password = form.get("password", "")
    confirm_password = form.get("confirm_password", "")
    return name, email, password, confirm_password


def validate_registration(name, email, password, confirm_password):
    if not name:
        return "Please enter your name."
    if len(name) > 100:
        return "Name must be 100 characters or fewer."

    local, at, domain = email.partition("@")
    if (
        not email
        or len(email) > 254
        or any(c.isspace() for c in email)
        or not at
        or "@" in domain
        or not local
        or "." not in domain
        or domain.startswith(".")
        or domain.endswith(".")
    ):
        return "Please enter a valid email address."

    if len(password) < 8:
        return "Password must be at least 8 characters."
    if len(password) > 128:
        return "Password must be 128 characters or fewer."
    if password != confirm_password:
        return "Passwords do not match."
    return None


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "GET":
        return render_template("register.html")

    name, email, password, confirm_password = clean_registration(request.form)
    error = validate_registration(name, email, password, confirm_password)
    if error is None:
        try:
            create_user(name, email, generate_password_hash(password))
        except sqlite3.IntegrityError:
            error = "An account with this email already exists."
    if error:
        return render_template("register.html", error=error, name=name, email=email), 400
    return redirect(url_for("login", registered=1))


def clean_login(form):
    email = form.get("email", "").strip().lower()
    password = form.get("password", "")
    return email, password


def authenticate(email, password):
    if len(email) > 254 or len(password) > 128:
        check_password_hash(_DUMMY_PASSWORD_HASH, "invalid")
        return None

    user = get_user_by_email(email)
    pwhash = user["password_hash"] if user else _DUMMY_PASSWORD_HASH
    try:
        ok = check_password_hash(pwhash, password)
    except ValueError:
        ok = False
    return user if ok else None


@app.route("/login")
def login():
    return render_template("login.html", registered=request.args.get("registered") == "1")


@app.route("/terms")
def terms():
    return render_template("terms.html")


@app.route("/privacy")
def privacy():
    return render_template("privacy.html")


# ------------------------------------------------------------------ #
# Placeholder routes — students will implement these                  #
# ------------------------------------------------------------------ #

@app.route("/logout")
def logout():
    return "Logout — coming in Step 3"


@app.route("/profile")
def profile():
    return "Profile page — coming in Step 4"


@app.route("/expenses/add")
def add_expense():
    return "Add expense — coming in Step 7"


@app.route("/expenses/<int:id>/edit")
def edit_expense(id):
    return "Edit expense — coming in Step 8"


@app.route("/expenses/<int:id>/delete")
def delete_expense(id):
    return "Delete expense — coming in Step 9"


if __name__ == "__main__":
    app.run(debug=True, port=5001)
