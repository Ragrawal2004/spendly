import os
import re
import secrets
import unicodedata
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from functools import wraps

import psycopg
from flask import (
    Flask,
    g,
    make_response,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from werkzeug.security import check_password_hash, generate_password_hash

from database.db import (
    create_expense,
    create_user,
    get_category_totals,
    get_expense_summary,
    get_filtered_expenses,
    get_filtered_summary,
    get_recent_expenses,
    get_user_by_email,
    get_user_by_id,
    get_user_profile,
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

CATEGORIES = ("Food", "Transport", "Bills", "Health", "Entertainment", "Shopping", "Other")
MAX_AMOUNT = Decimal("10000000.00")
MIN_EXPENSE_DATE = date(2000, 1, 1)
MAX_DESCRIPTION = 200
_AMOUNT_RE = re.compile(r"[0-9]{1,15}(\.[0-9]{1,2})?")
_DATE_RE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
PAGE_SIZE = 20
MAX_SEARCH = 100
_PAGE_RE = re.compile(r"[0-9]{1,9}")


def startup():
    with app.app_context():
        init_db()
        if os.environ.get("SPENDLY_ENV") != "production":
            seed_db()


startup()


CSRF_ERROR = "Invalid or missing form token. Reload the page and try again."


@app.template_global("csrf_token")
def get_csrf_token():
    token = session.get("csrf_token")
    if not isinstance(token, str) or not token:
        token = secrets.token_urlsafe(32)
        session["csrf_token"] = token
    return token


# Registered before load_current_user, so a bad POST is rejected before any DB work or session.clear().
@app.before_request
def check_csrf_token():
    if request.method != "POST" or request.endpoint is None:
        return None
    expected = session.get("csrf_token")
    submitted = request.form.get("csrf_token")
    if (
        isinstance(expected, str) and expected
        and isinstance(submitted, str) and submitted
        and secrets.compare_digest(submitted.encode("utf-8"), expected.encode("utf-8"))
    ):
        return None
    return CSRF_ERROR, 400, {"Content-Type": "text/plain; charset=utf-8"}


@app.before_request
def load_current_user():
    if request.endpoint == "static":
        return
    g.current_user = None
    if "user_id" not in session:
        return
    user_id = session["user_id"]
    user = None
    if isinstance(user_id, int) and not isinstance(user_id, bool):
        user = get_user_by_id(user_id)
    if user is None:
        session.clear()
        return
    g.current_user = user


@app.context_processor
def inject_current_user():
    return {"current_user": getattr(g, "current_user", None)}


def month_bounds(today):
    start = today.replace(day=1)
    if start.month == 12:
        next_start = start.replace(year=start.year + 1, month=1)
    else:
        next_start = start.replace(month=start.month + 1)
    return start.isoformat(), next_start.isoformat()


def member_since(created_at):
    if isinstance(created_at, datetime):
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        else:
            created_at = created_at.astimezone(timezone.utc)
        return created_at.strftime("%B %Y")
    if isinstance(created_at, str):
        try:
            return datetime.strptime(created_at, "%Y-%m-%d %H:%M:%S").strftime("%B %Y")
        except ValueError:
            return None
    return None


@app.template_filter("format_amount")
def format_amount(value):
    return f"₹{value:,.2f}"


def _to_decimal(x):
    return x if isinstance(x, Decimal) else Decimal(str(x))


def category_share(total, overall):
    if not overall:
        return 0
    t, o = _to_decimal(total), _to_decimal(overall)
    return int((t * 100 / o).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not getattr(g, "current_user", None):
            return redirect(url_for("login"))
        return view(*args, **kwargs)

    return wrapped


def no_store(rv, status=200):
    resp = make_response(rv, status)
    resp.headers["Cache-Control"] = "no-store"
    return resp


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
    if g.current_user:
        return redirect(url_for("profile"))

    if request.method == "GET":
        return no_store(render_template("register.html"))

    name, email, password, confirm_password = clean_registration(request.form)
    error = validate_registration(name, email, password, confirm_password)
    if error is None:
        try:
            create_user(name, email, generate_password_hash(password))
        except psycopg.errors.UniqueViolation:
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


@app.route("/login", methods=["GET", "POST"])
def login():
    if g.current_user:
        return redirect(url_for("profile"))

    if request.method == "GET":
        return no_store(
            render_template("login.html", registered=request.args.get("registered") == "1")
        )

    email, password = clean_login(request.form)
    if not email or not password:
        error, status = "Please enter your email and password.", 400
    else:
        user = authenticate(email, password)
        if user is not None:
            session.clear()
            session["user_id"] = user["id"]
            get_csrf_token()  # fresh token for the new privilege level
            return redirect(url_for("profile"))
        error, status = "Invalid email or password.", 401
    return render_template("login.html", error=error, email=email), status


@app.route("/terms")
def terms():
    return render_template("terms.html")


@app.route("/privacy")
def privacy():
    return render_template("privacy.html")


@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect(url_for("landing"))


@app.route("/profile")
@login_required
def profile():
    uid = g.current_user["id"]
    user = get_user_profile(uid)
    if user is None:
        session.clear()
        return redirect(url_for("login"))

    month_start, next_month_start = month_bounds(datetime.now(timezone.utc).date())
    summary = get_expense_summary(uid, month_start, next_month_start)
    categories = [
        {
            "category": row["category"],
            "total": row["total"],
            "count": row["count"],
            "percent": category_share(row["total"], summary["total"]),
        }
        for row in get_category_totals(uid)
    ]
    recent = get_recent_expenses(uid)

    resp = make_response(
        render_template(
            "profile.html",
            user=user,
            member_since=member_since(user["created_at"]),
            summary=summary,
            categories=categories,
            recent=recent,
        )
    )
    resp.headers["Cache-Control"] = "no-store"
    return resp


def clean_expense(form):
    amount = form.get("amount", "").strip()
    category = form.get("category", "").strip()
    date = form.get("date", "").strip()
    description = form.get("description", "").strip()
    return amount, category, date, description


def validate_expense(amount, category, date, description, today):
    if not _AMOUNT_RE.fullmatch(amount):
        return "Enter a valid amount, like 250 or 99.50.", None
    value = Decimal(amount)
    if value <= 0:
        return "Amount must be greater than ₹0.", None
    if value > MAX_AMOUNT:
        return "Amount must be ₹1,00,00,000 or less.", None

    if category not in CATEGORIES:
        return "Please choose a category.", None

    # `date` is the form string here, so parse with strptime rather than date.fromisoformat.
    if not _DATE_RE.fullmatch(date):
        return "Enter a valid date.", None
    try:
        day = datetime.strptime(date, "%Y-%m-%d").date()
    except ValueError:
        return "Enter a valid date.", None
    if not MIN_EXPENSE_DATE <= day <= today + timedelta(days=1):
        return "Date must be between 1 January 2000 and tomorrow.", None

    if len(description) > MAX_DESCRIPTION:
        return "Description must be 200 characters or fewer.", None
    if any(unicodedata.category(c) == "Cc" for c in description):
        return "Description cannot contain line breaks or control characters.", None

    return None, {
        "amount": value,
        "category": category,
        "date": day,
        "description": description or None,
    }


def render_expense_form(today, status=200, error=None, amount="", category="", date_value=None, description=""):
    return no_store(
        render_template(
            "add_expense.html",
            error=error, amount=amount, category=category, description=description,
            date_value=today.isoformat() if date_value is None else date_value,
            categories=CATEGORIES,
            min_date=MIN_EXPENSE_DATE.isoformat(),
            max_date=(today + timedelta(days=1)).isoformat(),
            max_description=MAX_DESCRIPTION,
        ),
        status,
    )


@app.route("/expenses/add", methods=["GET", "POST"])
@login_required
def add_expense():
    today = datetime.now(timezone.utc).date()
    if request.method == "GET":
        return render_expense_form(today)

    amount, category, date_str, description = clean_expense(request.form)
    error, values = validate_expense(amount, category, date_str, description, today=today)
    if error:
        return render_expense_form(
            today, 400, error=error, amount=amount, category=category,
            date_value=date_str, description=description,
        )

    try:
        create_expense(g.current_user["id"], **values)
    except psycopg.errors.ForeignKeyViolation:
        session.clear()
        return redirect(url_for("login"))
    return redirect(url_for("profile"), code=303)


def _filter_date(value):
    value = value.strip()
    if not _DATE_RE.fullmatch(value):
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


def clean_expense_filters(args):
    category = args.get("category", "").strip()
    q = args.get("q", "").strip()
    if not q or len(q) > MAX_SEARCH or any(unicodedata.category(c) == "Cc" for c in q):
        q = None
    page = args.get("page", "").strip()
    return {
        "category": category if category in CATEGORIES else None,
        "date_from": _filter_date(args.get("date_from", "")),
        "date_to": _filter_date(args.get("date_to", "")),
        "q": q,
        "page": max(int(page), 1) if _PAGE_RE.fullmatch(page) else 1,
    }


def page_window(count, page, page_size):
    pages = max(1, (count + page_size - 1) // page_size)
    page = min(max(page, 1), pages)
    offset = (page - 1) * page_size
    first = offset + 1 if count else 0
    last = min(offset + page_size, count)
    return {"page": page, "pages": pages, "offset": offset, "first": first, "last": last}


@app.route("/expenses")
@login_required
def expense_list():
    uid = g.current_user["id"]
    filters = clean_expense_filters(request.args)
    criteria = (filters["category"], filters["date_from"], filters["date_to"], filters["q"])

    summary = get_filtered_summary(uid, *criteria)
    pager = page_window(summary["count"], filters["page"], PAGE_SIZE)
    expenses = []
    owns_expenses = summary["count"] > 0
    if owns_expenses:
        expenses = get_filtered_expenses(uid, *criteria, PAGE_SIZE, pager["offset"])
    elif any(value is not None for value in criteria):
        # Pick the empty state: does the user own any expenses at all?
        owns_expenses = get_filtered_summary(uid, None, None, None, None)["count"] > 0

    # Only effective, non-default filters are carried into the page links (D7).
    active = {key: filters[key] for key in ("category", "q") if filters[key] is not None}
    for key in ("date_from", "date_to"):
        if filters[key] is not None:
            active[key] = filters[key].isoformat()
    prev_url = next_url = None
    if pager["page"] > 1:
        prev_url = url_for("expense_list", page=pager["page"] - 1, **active)
    if pager["page"] < pager["pages"]:
        next_url = url_for("expense_list", page=pager["page"] + 1, **active)

    return no_store(
        render_template(
            "expenses.html",
            filters=filters, summary=summary, pager=pager, expenses=expenses,
            owns_expenses=owns_expenses, prev_url=prev_url, next_url=next_url,
            categories=CATEGORIES, max_search=MAX_SEARCH,
        )
    )


# ------------------------------------------------------------------ #
# Placeholder routes — students will implement these                  #
# ------------------------------------------------------------------ #

@app.route("/expenses/<int:id>/edit")
def edit_expense(id):
    return "Edit expense — coming in Step 8"


@app.route("/expenses/<int:id>/delete")
def delete_expense(id):
    return "Delete expense — coming in Step 9"


if __name__ == "__main__":
    app.run(debug=True, port=5001)
