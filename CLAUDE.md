# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project overview

Spendly is a Flask-based expense tracker, built incrementally as a step-by-step learning project. The codebase is intentionally scaffolded with placeholder routes and an empty database module — features are implemented one step at a time rather than all at once.

## Commands

The venv lives at `.venv/` (not `venv/` — note the `.gitignore` excludes `venv/`, which doesn't match the actual `.venv/` directory name).

```bash
# Install dependencies (venv activation doesn't persist across separate Bash calls,
# so either chain source+command, or call the venv binary directly)
.venv/bin/pip install -r requirements.txt

# Run the dev server (binds port 5001, not Flask's default 5000)
.venv/bin/python3 app.py

# Same, with a fixed secret key so sessions survive the debug reloader
SPENDLY_SECRET_KEY=dev-only-value .venv/bin/python3 app.py

# Run tests
.venv/bin/pytest
.venv/bin/pytest path/to/test_file.py::test_name   # single test
```

## Architecture

Flat, single-file Flask app — no blueprints, no app factory pattern. Everything routes from `app.py`.

- **`app.py`** — the only entry point. Each route either calls `render_template(...)` for built pages or returns a placeholder string for features not yet implemented (labeled with their build step, e.g. `"Add expense — coming in Step 7"`). Runs on port 5001 in debug mode. Built so far:
  - `/register` — `clean_registration()` and `validate_registration()` helpers; POST creates the user and redirects to `/login?registered=1`. Signed-in users are redirected to `/profile`.
  - `/login` (Step 3, complete) — `clean_login()` reads the form (email stripped and lowercased, password untouched); `authenticate()` is the only credential check and makes exactly one `check_password_hash` call on every path (a dummy hash stands in for unknown emails and over-long input; a malformed stored hash counts as a failed check), so failures take the same time and give the same generic message ("Invalid email or password."; blank fields give a 400). Success clears the session, stores `user_id` and redirects to `/profile`. Signed-in users are redirected to `/profile`.
  - `/logout` — `POST` only (`GET` gets Flask's 405), clears the session and redirects to `/`. The nav "Sign out" button is a small POST form.
  - `/profile` (Step 4, complete) — `GET` only, behind `@login_required`. Fetches `get_user_profile(uid)` for the signed-in user; if that returns `None` (user vanished mid-request) it clears the session and redirects to `/login`. Otherwise renders `profile.html` with the account card (name, email, "Member since" only when `created_at` parses), stat tiles (total, this month, expense count), the category breakdown with percentages, and the five most recent expenses (or a "No expenses yet." empty state). The response sets `Cache-Control: no-store` and the 200 path never writes the session. It reads only `g.current_user["id"]`, never a request parameter, so no one can view another user's page. The nav user name links here.
  - `login_required(view)` — the only signed-out gate: if `g.current_user` is falsy it redirects to `/login` (no `next` parameter, nothing read from the request), otherwise calls the view. Apply it below `@app.route(...)`.
  - Profile helpers (pure, unit tested without a request): `month_bounds(today)` returns ISO strings for the first day of this month and of next month (December rolls to January); `member_since(created_at)` turns `"YYYY-MM-DD HH:MM:SS"` into `"March 2026"`, or `None` for missing or malformed input; `format_amount(value)` gives `₹12,345.60` and is also registered as the `format_amount` Jinja filter; `category_share(total, overall)` gives a half-up rounded whole percentage, or `0` when `overall` is 0. The current month comes from `datetime.now(timezone.utc).date()`.
  - `resolve_secret_key(env)` and `session_cookie_secure(env)` — pure helpers that read the environment for the secret key and the cookie `Secure` flag.
- **Sessions** — the signed Flask cookie session holds only `user_id` and is non-permanent (ends with the browser session). Cookies are `HttpOnly`, `SameSite=Lax`, and `Secure` in production. A `before_request` hook (`load_current_user`) is the only code that reads `session["user_id"]`: it sets `g.current_user` (a `get_user_by_id` row, or `None`) and clears the session if `user_id` is not an `int` or no longer matches a user. A context processor exposes it to templates as `current_user`. Routes check `g.current_user`, never the session. Known gaps, deliberately left: no CSRF token (only `SameSite=Lax`), no rate limiting, and the `/expenses/*` placeholder routes are public until Steps 7-9.
- **Environment variables** — `SPENDLY_SECRET_KEY` signs the session cookie. If unset or empty, a random key is generated per process (fine for development, but sessions are lost on restart or debug reload). `SPENDLY_ENV=production` makes a missing key a startup `RuntimeError`, skips demo seeding and sets `Secure` on the cookie. `SPENDLY_DB` overrides the database path (tests use it). Never hard-code a key. `tests/conftest.py` sets a test key before `app` is imported.
- **`database/db.py`** — all SQLite access lives here: `get_db()` (connection with `row_factory` and foreign keys enabled), `init_db()` (creates tables with `CREATE TABLE IF NOT EXISTS`), `seed_db()` (demo data for development, including the `demo@spendly.com` / `demo123` user), `create_user()` (parameterised insert; lets `sqlite3.IntegrityError` propagate so the route can report a duplicate email), `get_user_by_email()` (returns `id, name, email, password_hash` or `None`; used only for login), `get_user_by_id()` (returns `id, name, email`, no hash, or `None`), and the profile reads: `get_user_profile(user_id)` (`id, name, email, created_at`, no hash, or `None`), `get_expense_summary(user_id, month_start, next_month_start)` (one row of `total`, `count`, `month_total`, zeros when there are no expenses; the month is `month_start <= date < next_month_start`), `get_category_totals(user_id)` (`category, total, count`, ordered by total descending then category) and `get_recent_expenses(user_id, limit=5)` (`id, amount, category, date, description`, newest date first, ties by higher `id`). Every query filters by `user_id` and does no rounding; formatting happens in `app.py`. Routes in `app.py` call these rather than touching raw SQL.
- **`templates/`** — server-rendered Jinja2 templates. `base.html` is the shared shell (nav, footer, font/CSS/JS includes); page templates (`landing.html`, `login.html`, `register.html`, `profile.html`, `terms.html`, `privacy.html`) extend it via `{% block content %}`.
- **`static/`** — assets served directly via `url_for('static', filename=...)`, referenced from `base.html` so they're shared across all pages: one CSS file (`css/style.css`) and one JS file (`js/main.js`, currently empty — students add JS here as features are built).

No ORM — the data layer is meant to be raw `sqlite3` access through `database/db.py`.
