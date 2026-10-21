# Design: Step 3 — Login and Logout

Companion to `03-login-logout.md`. Design only; no code. All eight open questions in the spec take its recommended defaults (POST-only logout, no CSRF library, redirect to `/profile`, browser-session cookie, random dev key, no rate limiting, logged-in users redirected away from `/login` and `/register`, `/profile` unprotected).

## 1. `app.py`

**Order of definitions (top to bottom):** imports → `resolve_secret_key`, `session_cookie_secure` → `app = Flask(...)` → secret key and cookie config → `_DUMMY_PASSWORD_HASH` → `startup()` and its call → routes. The key must be set before `startup()` so a production import without a key fails before any database work (AC-23 subprocess test).

**New imports:** `secrets`, `session`, `g`, `check_password_hash`, `get_user_by_email`, `get_user_by_id`. The last three are imported by name so tests can monkeypatch `app.check_password_hash` and `app.get_user_by_email` (AC-25).

**`resolve_secret_key(env) -> str`** (pure)
- Key set and non-empty: return it.
- Otherwise, `SPENDLY_ENV != "production"`: return `secrets.token_hex(32)`.
- Otherwise: raise `RuntimeError` naming the variable, never a value.
- An empty `SPENDLY_SECRET_KEY` counts as unset (Flask treats a falsy key as no key and fails on first session access).

**`session_cookie_secure(env) -> bool`** (pure): true only when `SPENDLY_ENV == "production"`.

**Cookie config:** `HTTPONLY=True`, `SAMESITE="Lax"`, `SECURE=session_cookie_secure(os.environ)`. Non-permanent session.

**`before_request` hook**
- Skip when `request.endpoint == "static"`.
- No `user_id` in session: `g.current_user = None`, no database query.
- `user_id` present: it must be an `int` and not a `bool`. A wrong type or a `get_user_by_id` miss calls `session.clear()` and sets `g.current_user = None`.
- The type guard matters because a validly signed but non-int value (e.g. a list) would otherwise make sqlite raise `InterfaceError` and return a 500 (AC-32).
- Only this hook reads `session["user_id"]`; only `login()` writes it.

**Context processor:** supplies `current_user` as `getattr(g, "current_user", None)` (the default covers requests where the hook was skipped).

**`clean_login(form) -> (email, password)`:** email stripped and lowercased, password untouched, missing fields become `""`. Mirrors `clean_registration`. The only reader of the raw form.

**`_DUMMY_PASSWORD_HASH`:** one `generate_password_hash` call on a constant, non-secret string with default arguments, the same call shape as `register()` and `seed_db()`. Costs one scrypt per import of `app`.

**`authenticate(email, password) -> Row | None`.** Every path makes exactly one `check_password_hash` call.
- Length limits apply to the cleaned email (after strip and lowercase) and the untouched password. A whitespace-only password is non-empty, so it goes through `authenticate` and gets a 401, not a 400.
- Email longer than 254 or password longer than 128: compare a fixed short string against the dummy hash, return `None`, no lookup. This keeps timing uniform and avoids hashing a huge input.
- Otherwise: `get_user_by_email`; use the user's hash, or the dummy hash if there is no user. Run the check inside `try/except ValueError` and treat an exception as a failed check. Return the user only if the user exists and the check passed.
- Only a `ValueError` raised around `check_password_hash` is caught, and it is never logged or printed. Any other database error is not caught and becomes a 500.
- The catch is needed because werkzeug's `check_password_hash` returns `False` for `"not-a-hash"` (no `$`) but `_hash_internal` raises `ValueError` for an unknown method (`"x$y$z"`) or malformed scrypt arguments (AC-31).

**`login()` (GET, POST)**
1. If `g.current_user`: redirect to `url_for("profile")`. This happens before the form is read, so a logged-in POST never handles a password (AC-14, AC-15).
2. GET: render with `registered=request.args.get("registered") == "1"`. Query-string `email` and `password` are ignored (AC-20).
3. POST: `clean_login`. Blank email or password gives 400 with "Please enter your email and password." Otherwise `authenticate`. `None` gives 401 with "Invalid email or password." Both error responses (400 and 401) re-fill the email input with the cleaned (stripped, lowercased) email; the password is never re-filled. Success calls `session.clear()`, sets `session["user_id"]`, and redirects to `url_for("profile")`. `registered` is not passed on POST. The redirect target is fixed; there is no `next` parameter.

**`logout()`:** `methods=["POST"]` only, so GET returns Flask's automatic 405. `session.clear()`, redirect to `url_for("landing")`. Moves out of the placeholder section.

**`register()`:** the same `g.current_user` redirect at the top, before the GET/POST split.

## 2. `database/db.py`
Two read functions in the style of `create_user` (`with closing(get_db()) as conn:`, parameterised `SELECT`, returning `Row | None`):
- `get_user_by_email(email)`: returns `id, name, email, password_hash`; `WHERE email = ?`. The column is `COLLATE NOCASE` (ASCII only), so the caller's `.lower()` is what lets `É@X.COM` match the stored `é@x.com` (AC-10).
- `get_user_by_id(user_id)`: returns `id, name, email` (no hash).

No schema change.

## 3. Templates and CSS
- **`login.html`:** form `action` uses `url_for('login')`. The email input gets a quoted `value` (default empty), `maxlength="254"`, `autocomplete="email"`. The password input gets `maxlength="128"`, `autocomplete="current-password"` and never a value. Keep the `registered` banner and the `.auth-error` block.
- **`base.html`, inside `.nav-links`:** if `current_user`, show a `<span class="nav-user">` with the name (autoescaped, no `|safe`) and a `<form method="POST" action="{{ url_for('logout') }}">` with a "Sign out" button (`.nav-signout`). Otherwise keep the existing "Sign in" and "Get started" links. Jinja's `.name` falls back to `["name"]` on a `sqlite3.Row`.
- **`style.css`:**
  - `.nav-signout` copies the `.nav-links a` look (`var(--ink-muted)`, hover `var(--ink)`) onto a `<button>`: no background or border, `font: inherit`, `cursor: pointer`. The wrapping form is `display: inline` or `contents`. CSS variables only.
  - The ≤600px rule `.nav-links a:not(.nav-cta) { display: none }` hides only `<a>` tags, so on mobile a logged-in user still sees the name and the Sign out button. Check this visually.
  - `.nav-user` needs at most a small rule.

## 4. `tests/conftest.py`
- Add `os.environ.setdefault("SPENDLY_SECRET_KEY", "test-only-secret-key")` at module level next to the existing `SPENDLY_DB` line, before `import pytest`. An autouse fixture would be too late because `app` reads the key at import.
- `client` and `isolated_db` are unchanged. Logged-in helpers (e.g. `login_as(client, uid)` via `session_transaction`) live in `tests/test_login_logout.py`.

**Notes for the new test file**
- AC-26 must call `seed_db()` itself. Import-time `startup()` seeds only the `mkstemp` database, and each test uses a fresh `tmp_path` database.
- AC-19: replace the session cookie with garbage (e.g. `client.set_cookie("session", "garbage")`), then `GET /login` returns 200.
- AC-21: put `session["junk"] = 1` in the session via `session_transaction`, log in, and assert `junk` is gone and only `user_id` remains.
- AC-22: use `caplog` and assert neither the password nor the hash appears in the logs, and that no `ValueError` text containing the hash is logged.
- AC-23 subprocess: copy `os.environ`, delete `SPENDLY_SECRET_KEY` (conftest's `setdefault` would otherwise leak it), set `SPENDLY_ENV=production` and a `SPENDLY_DB` path inside a fresh temp directory that does not yet exist, and run `sys.executable -c "import app"` with `cwd` at the repo root. Assert a non-zero exit and that the path is still missing.
- AC-32: parametrize over a string, a list and `True`; set each as `session["user_id"]` via `session_transaction`, `GET /login` returns 200, and `user_id` is gone from the session.

## 5. Existing test to change
`tests/test_database.py::test_startup_skips_seed_in_production` currently sets `SPENDLY_ENV=production` and then runs `import app`. In a full run `app` is already cached, so this works. Run alone, it is the first import: it would need a key and would leave `app` cached with `SESSION_COOKIE_SECURE=True`, which can break cookie handling for later tests over plain `http`.

**Change:** `import app` before `monkeypatch.setenv("SPENDLY_ENV", "production")`, then call `app.startup()`. Assertions stay the same.

## 6. Spec conflicts and resolutions

| # | Issue | Resolution |
|---|---|---|
| 1 | "No lookup needed" for over-length input would leak timing if it also skipped the hash | Keep one dummy compare. AC-25 still holds |
| 2 | werkzeug raises `ValueError` for unknown hash methods | Catch only `ValueError` around `check_password_hash` in `authenticate`; any other error stays a 500 |
| 3 | With no key set, the debug reloader generates a new key on each reload and logs you out | Accepted; the manual DoD run sets `SPENDLY_SECRET_KEY` |

**Checked, no conflict**
- AC-16's "no 'Get started'" is safe on `/`: `landing.html` says "Create free account".
- Existing registration tests only touch `/register` and `/login?registered=1`.
- Nothing asserts the old `/logout` placeholder.
- No README or `.env.example` exists, so that spec line is a no-op.

**Known gaps, per spec:** no CSRF token (SameSite=Lax only), no rate limiting, `/profile` unprotected until Step 4.

## 7. Verification
- `.venv/bin/pytest -q`: new `tests/test_login_logout.py` (AC-1 to AC-32) plus the existing suites. Also run `test_startup_skips_seed_in_production` on its own.
- Manual: `SPENDLY_SECRET_KEY=dev-only-value .venv/bin/python3 app.py` (port 5001) and the spec's browser checklist. `SPENDLY_ENV=production .venv/bin/python3 -c "import app"` with no key must raise `RuntimeError`.
- No password or hash appears in the terminal output of the running app during the manual run.
- `grep -nE "^def (landing|profile)\(" app.py` prints both function names.
- Greps: the spec's SQL grep returns nothing; `grep -nE "secret_key *= *[\"']" app.py` returns nothing; no hex colours added to `style.css`.
- `git status` shows changes only in the files the spec lists (the spec, design and tasks files are already committed).
- Update `CLAUDE.md`: Step 3 complete, the session design, and `SPENDLY_SECRET_KEY` / `SPENDLY_ENV`.
