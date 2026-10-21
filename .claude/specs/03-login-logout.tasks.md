# Tasks: Step 3 — Login and Logout

Companion to `03-login-logout.md` (spec) and `03-login-logout.design.md` (design). Planning only; no code here.

**How to work through this list**
- Do the tasks in order. Each task is one commit.
- Red, green, commit: write the listed test first and watch it fail, make it pass, then run `.venv/bin/pytest -q` before committing.
- When a test passes before the code exists, say so; it is a regression guard. Tests that must fail first: AC-32 and the session-cleared part of AC-18.
- All new tests go in `tests/test_login_logout.py` unless a task says otherwise. Test setup follows spec section "Acceptance criteria and tests" (temporary database via `SPENDLY_DB`, `init_db()` after the fixture, users via `create_user()` with `generate_password_hash`; default user `Rahul Sharma` / `rahul@example.com` / `password123`).
- Commit messages follow the repo's `type: summary` style. The `Co-Authored-By` trailer is added at commit time.
- Where an AC is only partly satisfiable until a later task lands, the task says so; the AC is owned by the task where it first passes in full (see the coverage table at the end).

---

## Task 1: conftest secret key

**Goal:** make `app` importable in every test run once it requires a secret key.

**Change:** `tests/conftest.py` — module-level `os.environ.setdefault("SPENDLY_SECRET_KEY", ...)` next to the existing `SPENDLY_DB` line, before `import pytest`. Not an autouse fixture (too late: `app` reads the key at import).

**ACs satisfied:** none directly. Enabler for AC-1 to AC-32.

**Test first:** no new test. Before the change, nothing needs the key, so there is nothing to fail yet. Verify afterwards that `.venv/bin/pytest -q` is still green and that `SPENDLY_SECRET_KEY` is set when the first test module is collected.

**Commit:** `test: set secret key in conftest before app is imported`

---

## Task 2: db.py read functions

**Goal:** routes can fetch users without touching SQL.

**Change:** `database/db.py` — add `get_user_by_email(email)` (returns `id, name, email, password_hash`) and `get_user_by_id(user_id)` (returns `id, name, email`, no hash). Both use `with closing(get_db()) as conn:`, a parameterised `SELECT`, and return `Row | None`. No schema change.

**ACs satisfied:** none directly. Foundation for AC-2, AC-10, AC-18, AC-26.

**Test first:** direct tests of the two functions (extra to the AC list, in `tests/test_login_logout.py`): hit by exact lowercase email, miss returns `None`, `get_user_by_id` hit and miss, and the id lookup row has no `password_hash` key.

**Commit:** `feat: add get_user_by_email and get_user_by_id`

---

## Task 3: resolve_secret_key and session_cookie_secure

**Goal:** secure secret-key handling and cookie config, with no literal key anywhere.

**Change:** `app.py` — pure `resolve_secret_key(env)` and `session_cookie_secure(env)` defined before `app = Flask(...)`; set `app.secret_key` from `resolve_secret_key(os.environ)` and the cookie config (`HTTPONLY=True`, `SAMESITE="Lax"`, `SECURE=session_cookie_secure(os.environ)`) before `startup()` runs, so a production import without a key fails before any database work. Add the `secrets` import. Empty `SPENDLY_SECRET_KEY` counts as unset; the `RuntimeError` names the variable, never a value.

**ACs satisfied:** AC-23, AC-30.

**Test first:**
- AC-23 direct cases (key returned; 64-hex random in dev for empty env / `development` / empty key, two calls differ; `RuntimeError` in production for missing and empty key).
- AC-23 subprocess case: copy `os.environ`, delete `SPENDLY_SECRET_KEY`, set `SPENDLY_ENV=production` and a `SPENDLY_DB` path inside a fresh, not-yet-existing temp directory, run `sys.executable -c "import app"` with `cwd` at the repo root; assert non-zero exit and that the path is still missing.
- AC-30 (`True` for production; `False` for empty env and `development`).

**Commit:** `feat: read secret key and cookie flags from environment`

---

## Task 4: clean_login and authenticate

**Goal:** the only form reader and the only credential check, both with uniform timing and no leaks.

**Change:** `app.py` —
- `clean_login(form) -> (email, password)`: email stripped and lowercased, password untouched, missing fields become `""`.
- `_DUMMY_PASSWORD_HASH`: one `generate_password_hash` call on a constant non-secret string, same call shape as `register()` and `seed_db()`, defined after the app config and before `startup()`.
- `authenticate(email, password) -> Row | None`: exactly one `check_password_hash` call on every path. Email over 254 or password over 128 characters: compare a fixed string to the dummy hash, return `None`, no lookup. Otherwise look the user up, use their hash or the dummy hash, and wrap only the check in `try/except ValueError` (treated as a failed check, never logged). Add imports `check_password_hash`, `get_user_by_email`, `get_user_by_id` by name so tests can monkeypatch them.

**ACs satisfied:** none in full at this point. These land in Task 6 once the route exists: AC-25, AC-28, AC-31. Write their function-level halves now, calling `authenticate` directly:
- unknown email with `get_user_by_email` monkeypatched to `None` and `check_password_hash` recording calls: one call, returns `None` (AC-25)
- 255-char email and 129-char password: returns `None`, no exception (AC-28)
- users with stored hashes `"not-a-hash"`, `"hash"`, `""`, `"x$y$z"`, `"scrypt:bad$s$h"` (parametrized): returns `None`, no exception (AC-31)

**Test first:** the three function-level tests above, plus `clean_login` unit cases (padded mixed-case email lowercased and stripped, password with spaces untouched, missing fields become `""`).

**Commit:** `feat: add clean_login and constant-time authenticate`

---

## Task 5: before_request and context processor

**Goal:** a single place that resolves the session user, tolerating bad sessions.

**Change:** `app.py` —
- `before_request` hook: skip when `request.endpoint == "static"`. No `user_id` in session: `g.current_user = None`, no query. Present: it must be an `int` and not a `bool`; a wrong type or a `get_user_by_id` miss calls `session.clear()` and sets `g.current_user = None`. Add `session` and `g` imports.
- Context processor supplying `current_user` as `getattr(g, "current_user", None)`.
- Only this hook reads `session["user_id"]`.

**ACs satisfied:** AC-18, AC-19, AC-24, AC-32.

**Test first:**
- AC-18: signed session with a nonexistent `user_id`, `GET /` returns 200, logged-out nav, `user_id` gone from the session.
- AC-19: `client.set_cookie("session", "garbage")`, `GET /login` returns 200.
- AC-24: nonexistent `user_id`, `GET /login` returns 200 with inputs `email` and `password`.
- AC-32: parametrized over a string, a list and `True`; set via `session_transaction`, `GET /login` returns 200 and `user_id` is gone.

Add a small `login_as(client, uid)` helper in the test file (via `session_transaction`) for later tasks.

**Commit:** `feat: resolve current user per request and clear bad sessions`

---

## Task 6: login failures and GET

**Goal:** `GET /login` and every failing `POST /login` behave correctly, with generic errors and no information leaks.

**Change:** `app.py` — `login()` accepts `GET` and `POST`:
1. If `g.current_user`: redirect to `url_for("profile")` before the form is read.
2. `GET`: render with `registered=request.args.get("registered") == "1"`; query-string `email`/`password` ignored.
3. `POST`: `clean_login`; blank email or password gives 400 "Please enter your email and password."; else `authenticate`; `None` gives 401 "Invalid email or password."; both errors re-render with the cleaned email passed back and no password. No SQL in `app.py`, nothing logged or printed from the form.

The success branch (session and redirect) is Task 7. The `value`/`action` attributes in the template are finished in Task 10; this task only passes the context.

**ACs satisfied:** AC-4, AC-5, AC-6, AC-7, AC-9, AC-20, AC-25, AC-27, AC-28, AC-31.

**Test first** (one test per AC, in order):
- AC-4: wrong password gives 401, message shown, no `user_id`.
- AC-5: unknown email gives 401, same message.
- AC-6: AC-4 and AC-5 pages identical after substituting the email; none of "email not found", "no account", "wrong password".
- AC-7: parametrized blank/whitespace/missing email, empty/missing password, each 400 with the blank-fields message, no session.
- AC-9: `"password123 "` gives 401, no session.
- AC-20: `GET /login?email=...&password=...` gives 200 and no `user_id`.
- AC-25: monkeypatch `app.get_user_by_email` to `None` and `app.check_password_hash` to record; POST an unknown email; one call, 401.
- AC-27: `/login?registered=1` shows the banner; `/login` does not.
- AC-28: 255-char email and 129-char password both give 401 with the generic message.
- AC-31: parametrized over the five bad hashes through POST: 401, generic message, no exception.

AC-14's `GET /login` redirect is implemented here and tested in Task 9.

**Commit:** `feat: handle login failures with generic errors`

---

## Task 7: login success

**Goal:** a valid login starts a session safely.

**Change:** `app.py` — in `login()`, the success branch: `session.clear()`, then `session["user_id"] = user["id"]`, redirect to `url_for("profile")` (302). No `next` parameter; the redirect target is fixed.

**ACs satisfied:** AC-2, AC-3, AC-10, AC-15, AC-21, AC-26, AC-29.

**Test first** (one test per AC, in order; watch each fail before the success branch exists):
- AC-2: 302 to `/profile`, `dict(session) == {"user_id": <id>}`.
- AC-3: `"  Rahul@EXAMPLE.com "` logs in.
- AC-10: register `É@x.com` through `/register`, log in as `É@X.COM`.
- AC-15: logged in as user A, POST user B's valid credentials: 302 to `/profile`, `user_id` unchanged.
- AC-21: `session["junk"] = 1`, then log in; only `user_id` remains.
- AC-26: call `seed_db()` in the test, then `demo@spendly.com` / `demo123` logs in.
- AC-29: login response `Set-Cookie` contains `HttpOnly` and `SameSite=Lax`.

**Commit:** `feat: log in with a fresh session and redirect to profile`

---

## Task 8: logout route

**Goal:** logout is real, `POST`-only, and idempotent.

**Change:** `app.py` — `logout()` with `methods=["POST"]` only, `session.clear()`, redirect to `url_for("landing")` (302). Remove it from the placeholder section. `GET /logout` gets Flask's automatic 405.

**ACs satisfied:** AC-11, AC-12, AC-13, AC-22.

**Test first:**
- AC-11: logged in, `POST /logout` gives 302 to `/`, no `user_id`.
- AC-12: no session, `POST /logout` gives 302 to `/`, no exception (also twice in a row).
- AC-13: `GET /logout` gives 405 and a logged-in session stays logged in.
- AC-22: after a successful login and logout, response bodies, `Set-Cookie` values and `caplog` output contain neither the password nor the stored hash.

**Commit:** `feat: add POST-only logout`

---

## Task 9: register redirect

**Goal:** signed-in users are sent away from the registration form.

**Change:** `app.py` — at the top of `register()`, before the `GET`/`POST` split, redirect to `url_for("profile")` when `g.current_user`.

**ACs satisfied:** AC-14.

**Test first:** AC-14 with a logged-in client: `GET /login` and `GET /register` each give 302 to `/profile`, and `POST /register` gives 302 to `/profile` and creates no user.

**Commit:** `feat: redirect logged-in users away from register`

---

## Task 10: templates and CSS

**Goal:** the forms and nav reflect login state, safely.

**Change:**
- `templates/login.html`: `action="{{ url_for('login') }}"`; quoted email `value` re-filled (never the password); `maxlength` 254 / 128; `autocomplete="email"` / `"current-password"`; keep the `registered` banner and `.auth-error` block.
- `templates/base.html`: inside `.nav-links`, when `current_user`: `<span class="nav-user">` with the autoescaped name (no `|safe`) and a `<form method="POST" action="{{ url_for('logout') }}">` with a `.nav-signout` "Sign out" button; otherwise the existing "Sign in" and "Get started" links.
- `static/css/style.css`: `.nav-signout` mirrors the `.nav-links a` look on a `<button>` (no background or border, `font: inherit`, `cursor: pointer`, hover colour), wrapping form displayed inline, small `.nav-user` rule. CSS variables only, no hex values. Check the ≤600px layout by eye: the rule hiding `a:not(.nav-cta)` must not hide the name or the button.

**ACs satisfied:** AC-1, AC-8, AC-16, AC-17.

**Test first:**
- AC-1: `GET /login` is 200 with inputs `email` and `password` and a form posting to `/login`.
- AC-8: failed login with `rahul@example.com` puts the email in the input `value`; the submitted password appears nowhere in the HTML.
- AC-16: logged in, `GET /` contains the name and a form posting to `/logout` and no "Get started"; logged out, it contains "Sign in" and "Get started" and no logout form.
- AC-17: user named `<b>x</b>`, logged in, `GET /` contains `&lt;b&gt;x&lt;/b&gt;` and no raw `<b>x</b>` in the nav.

**Commit:** `feat: login form re-fill and session-aware nav with sign-out`

---

## Task 11: test_database.py reorder

**Goal:** the existing production-env test no longer depends on test order or leaks `SESSION_COOKIE_SECURE=True`.

**Change:** `tests/test_database.py::test_startup_skips_seed_in_production` — `import app` first, then `monkeypatch.setenv("SPENDLY_ENV", "production")`, then call `app.startup()`. Assertions unchanged.

**ACs satisfied:** none. Keeps the existing database tests passing (Definition of Done, first item).

**Test first:** add a guard test in `tests/test_login_logout.py` asserting `app.config["SESSION_COOKIE_SECURE"] is False`. With the old ordering, the guard fails only when the production test runs first and is the first importer of `app` (for example `.venv/bin/pytest tests/test_database.py::test_startup_skips_seed_in_production tests/test_login_logout.py::<guard test>` in a fresh process); in a normal full run `app` is already cached, so the guard passes with either ordering and is a regression guard. Run that two-test command to see the guard fail, apply the reorder, then run it again and the full suite.

**Commit:** `test: import app before setting production env in startup test`

---

## Task 12: final sweep

**Goal:** prove the whole step meets the spec. This is the last gate before the CLAUDE.md update (Task 13).

**ACs satisfied:** all of AC-1 to AC-32 pass together (individual owners are in the coverage table below).

**Test first:** nothing new. If the sweep finds a gap, add a failing test for it first, fix it, and commit the fix separately.

**Definition of Done (copied from the spec; tick each box):**

- [ ] All acceptance criteria AC-1 to AC-32 pass with `pytest -q`, and the existing database and registration tests still pass
- [ ] The app was run by hand (`SPENDLY_SECRET_KEY=dev-only-value .venv/bin/python3 app.py`, port 5001) and each of these was verified in the browser: demo user (`demo@spendly.com` / `demo123`) signs in and lands on the profile placeholder; the nav shows the name and "Sign out"; "Sign out" returns to the landing page with the logged-out nav; a wrong password and an unknown email show the same message; an empty form shows the blank-fields message; email is kept after an error but the password is not; visiting `/login` while signed in redirects away; typing `/logout` in the address bar shows "Method Not Allowed" and does not sign out; a newly registered user can sign in
- [ ] Starting the app with `SPENDLY_ENV=production` and no `SPENDLY_SECRET_KEY` fails with a `RuntimeError`
- [ ] `grep -nE "execute\(|(SELECT|INSERT|UPDATE|DELETE) " app.py` finds no SQL in `app.py`
- [ ] `grep -nE "secret_key *= *[\"']" app.py` prints nothing (no literal key)
- [ ] `git diff -U0 static/css/style.css | grep -E "^\+.*#[0-9a-fA-F]{3,8}"` prints nothing (no new hard-coded colours in the added rules)
- [ ] No password or hash appears in the terminal output of the running app during the manual run
- [ ] `git status` shows changes only in the files under Files to change and Files to create (the spec, design and tasks files are already committed)

**Extra checks from the design (section 7):**
- `.venv/bin/pytest -q` is fully green, and `test_startup_skips_seed_in_production` also passes when run on its own.
- `grep -nE "^def (landing|profile)\(" app.py` prints both function names.
- Check the mobile (≤600px) nav while signed in: name and "Sign out" are visible.
- Known gaps stay as recorded and are not fixed here: no CSRF token (`SameSite=Lax` only), no rate limiting, `/profile` unprotected until Step 4.

**Commit:** only if the sweep produces a change: `chore: final sweep fixes for login and logout`

---

## Task 13: CLAUDE.md update

**Goal:** the project guide matches the code.

**Change:** `CLAUDE.md` — mark Step 3 complete; document the session design (`user_id` only, non-permanent, `before_request` resolves `g.current_user`, `POST`-only logout, fixed redirect to `/profile`) and the `SPENDLY_SECRET_KEY` / `SPENDLY_ENV` variables, including the dev-key behaviour and the `.venv/bin/python3 app.py` run example with a key. Update the `app.py` and `database/db.py` bullets for the new functions. No README or `.env.example` exists, so that spec line is a no-op.

**ACs satisfied:** none.

**Test first:** none (documentation). Re-read the changed lines against the final code from Tasks 3 to 10.

**Commit:** `docs: document sessions and secret key in CLAUDE.md`

---

## AC coverage

| AC | Task | AC | Task |
| --- | --- | --- | --- |
| AC-1 | 10 | AC-17 | 10 |
| AC-2 | 7 | AC-18 | 5 |
| AC-3 | 7 | AC-19 | 5 |
| AC-4 | 6 | AC-20 | 6 |
| AC-5 | 6 | AC-21 | 7 |
| AC-6 | 6 | AC-22 | 8 |
| AC-7 | 6 | AC-23 | 3 |
| AC-8 | 10 | AC-24 | 5 |
| AC-9 | 6 | AC-25 | 6 (function level in 4) |
| AC-10 | 7 | AC-26 | 7 |
| AC-11 | 8 | AC-27 | 6 |
| AC-12 | 8 | AC-28 | 6 (function level in 4) |
| AC-13 | 8 | AC-29 | 7 |
| AC-14 | 9 (GET /login half built in 6) | AC-30 | 3 |
| AC-15 | 7 | AC-31 | 6 (function level in 4) |
| AC-16 | 10 | AC-32 | 5 |

All 32 criteria are covered. Tasks 1, 2, 11 and 13 own no AC; Task 12 re-verifies all of them.
