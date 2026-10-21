# Spec: Login and Logout

## Overview

Make sign-in and sign-out work. Today `GET /login` renders a form whose `POST` is not handled, and `/logout` is a placeholder string. This step adds form handling for login (normalise the email, look up the user, verify the password hash with werkzeug), stores the user id in a signed Flask session, and makes logout clear that session. The navigation bar switches between "Sign in / Get started" and the user's name with a "Sign out" button depending on session state. It is Step 3 of the roadmap: registration (Step 2) creates accounts but nobody can use them until this step, and every later feature (profile, expenses) needs to know who is logged in.

## Depends on

- Step 01 (database setup): `users` table, `get_db()`, `init_db()`, `seed_db()` (demo user `demo@spendly.com` / `demo123`), test fixtures in `tests/conftest.py`.
- Step 02 (registration): users with hashed passwords and lowercased emails exist; `/login?registered=1` banner exists; the `client` fixture exists.

## Routes

- `GET /login` — render the sign-in form (with the `registered=1` banner as today); if already logged in, redirect to `/profile` — public
- `POST /login` — validate and authenticate; on success set the session and redirect to `/profile` (302); on failure re-render the form with a generic error and HTTP 401 (or 400 for blank fields) — public
- `POST /logout` — clear the session and redirect to `/` (302) — logged-in or logged-out (idempotent, never an error)
- `GET /logout` — no longer logs out: responds 405 Method Not Allowed (a state-changing action must not be triggerable by a link or image tag) — public
- `GET /register`, `POST /register` — existing; a logged-in user is redirected to `/profile` instead of seeing the form — public
- `GET /profile` — remains the Step 4 placeholder; used only as the post-login target. Not protected in this step (protection arrives with the real page in Step 4).

## Database changes

No database changes. The `users` table already has `email` (unique, NOCASE), `password_hash` and `name`.

Two new read functions in `database/db.py` so routes never touch raw SQL, each using `with closing(get_db()) as conn:` and a parameterised `SELECT`:

- `get_user_by_email(email) -> sqlite3.Row | None` — exact match on the already cleaned (stripped, lowercased) email; returns `id, name, email, password_hash`.
- `get_user_by_id(user_id) -> sqlite3.Row | None` — returns `id, name, email` (no hash) for the nav bar.

## Templates

- **Create:** none
- **Modify:**
  - `templates/login.html` — post to `url_for('login')`; re-fill `email` (never the password) after an error; keep the `registered` banner and the `.auth-error` block; add `maxlength` attributes matching server limits (email 254, password 128); `autocomplete="email"` and `autocomplete="current-password"`
  - `templates/base.html` — in `.nav-links`: when `current_user` is set, show the user's name (escaped) and a `<form method="POST" action="{{ url_for('logout') }}">` containing a "Sign out" button; otherwise show the existing "Sign in" and "Get started" links

## Files to change

- `app.py` — pure `resolve_secret_key(env)` and `session_cookie_secure(env)` functions, with the secret key and cookie settings taken from the environment; `session`, `g` and `check_password_hash` imports; `clean_login()` helper; `login()` accepts `GET` and `POST`; `logout()` becomes `POST`-only and real; a `before_request` hook that sets `g.current_user`; `register()` and `login()` redirect logged-in users based on `g.current_user`; a `context_processor` supplying `current_user` from `g.current_user`
- `database/db.py` — add `get_user_by_email()` and `get_user_by_id()`
- `templates/login.html`
- `templates/base.html`
- `static/css/style.css` — style the sign-out button so it looks like a nav link (`.nav-signout`), using existing CSS variables only
- `tests/conftest.py` — set `SPENDLY_SECRET_KEY` at module level with `os.environ.setdefault`, before any test imports `app` (an autouse fixture is too late, because `app` reads the key at import)
- `CLAUDE.md` — mark Step 3 complete and document the session and the secret key variable
- `README` or `.env.example`, only if one already exists — mention `SPENDLY_SECRET_KEY`

## Files to create

- `tests/test_login_logout.py`

## New dependencies

No new dependencies. Flask's built-in signed-cookie session is used.

## Rules for implementation

- No SQLAlchemy or ORMs
- Parameterised queries only
- Passwords hashed with werkzeug (`check_password_hash` to verify; never compare strings)
- Use CSS variables — never hardcode hex values
- All templates extend `base.html`
- Emails are stripped and lowercased in application code before saving or looking up (SQLite NOCASE is ASCII-only)
- Login errors never reveal whether the email or the password was wrong: the same message, status and response shape for unknown email, wrong password, and a user whose hash does not verify
- Secrets such as the Flask secret key come from environment variables, never from the code. `app.secret_key` is set from `resolve_secret_key(os.environ)`, a pure function `resolve_secret_key(env) -> str` in `app.py`: if `SPENDLY_SECRET_KEY` is set in `env`, return its value; if it is unset and `SPENDLY_ENV != "production"`, return a random per-process key from `secrets.token_hex(32)` (sessions end on restart; acceptable for development); if it is unset and `SPENDLY_ENV == "production"`, raise `RuntimeError`, so importing `app` never starts with a guessable key. No default key literal anywhere in the code.
- Passwords and password hashes are never printed or logged, and never stored in the session
- The session stores only `user_id` (an int). Configure `SESSION_COOKIE_HTTPONLY=True` (Flask default, set explicitly), `SESSION_COOKIE_SAMESITE="Lax"`, and `SESSION_COOKIE_SECURE=session_cookie_secure(os.environ)`, where the pure function `session_cookie_secure(env) -> bool` returns `True` only when `SPENDLY_ENV == "production"`. The session is non-permanent (ends when the browser closes).
- `clean_login(form) -> (email, password)` in `app.py`: `email` stripped and lowercased, `password` untouched, missing fields become `""`. Nothing else reads the raw form.
- Authentication lives in one function in `app.py` that takes `(email, password)` and returns the user row or `None`. When no user matches the email it still runs `check_password_hash` against a module-level dummy hash (generated once at import with the same method and settings as real hashes, i.e. the same `generate_password_hash` call and arguments used when registering a user) so response time does not reveal which emails exist.
- On successful login call `session.clear()` before setting `session["user_id"]` (prevents session fixation)
- Logout uses `session.clear()` and is `POST`-only
- Route code calls `get_user_by_email()` / `get_user_by_id()`; no SQL in `app.py`
- The post-login redirect is always the fixed `url_for('profile')`. There is no `next` parameter and no user-supplied redirect target (avoids open redirects).
- Jinja autoescaping stays on; never use `|safe` on user input (the nav bar prints the user's name)
- Template attribute values from user input are always quoted
- A `before_request` hook sets `g.current_user` for every request except `request.endpoint == "static"`: it looks up the user by `session["user_id"]` with `get_user_by_id()`; if there is no `user_id`, `g.current_user` is `None`; if the id is not found (user deleted, stale session), it clears the session and sets `g.current_user` to `None`. The context processor (supplying `current_user` to templates) and the redirects in `login()` and `register()` all read `g.current_user`; nothing else looks up the session user.

## Error handling

| Action | Required result |
| --- | --- |
| `email` or `password` empty / missing from POST | HTTP 400, form re-rendered, error "Please enter your email and password." |
| Email not registered | HTTP 401, error "Invalid email or password." |
| Email registered, wrong password | HTTP 401, identical error "Invalid email or password." and identical page |
| `email` longer than 254 or `password` longer than 128 characters | HTTP 401, same "Invalid email or password." (no lookup needed; no length-specific message) |
| Success | HTTP 302 to `/profile`; `session["user_id"]` equals the user's id |
| `POST /login` while already logged in | HTTP 302 to `/profile`; the session is not replaced |
| `GET /login`, `GET /register` or `POST /register` while logged in | HTTP 302 to `/profile` |
| `POST /logout` | HTTP 302 to `/`; session empty; works when already logged out |
| `GET /logout` | HTTP 405 |
| Session holds a `user_id` that no longer exists | Session cleared; page renders as logged-out; no exception |
| `SPENDLY_SECRET_KEY` unset in production | `RuntimeError` at startup |
| Any other database error | Not caught; Flask returns HTTP 500 |

On every login error the submitted `email` is put back in the form; the password field is always empty.

## Edge cases

- Empty or whitespace-only email; empty password; fields missing from the POST entirely
- Email with surrounding spaces and mixed case (`"  Demo@Spendly.COM "`) logs in as `demo@spendly.com`
- Non-ASCII email: a user registered as `É@x.com` (stored `é@x.com`) can log in with `É@X.COM`
- Password with leading or trailing spaces is not stripped: `"demo123 "` does not log in the demo user
- Password with only the wrong letter case (`DEMO123`) fails
- Unknown email and wrong password produce byte-identical responses apart from the re-filled email
- Repeated submit of the same valid login: the second request sees an existing session and gets the 302 to `/profile`, no error
- Logging in as a second user in a browser that already has a session: redirected, session unchanged (they must sign out first)
- Logout when not logged in: 302 to `/`, no error
- Logout twice in a row: both 302
- Back button after logout: the cached page may show, but any request to the server sees no session (full protection of private pages comes with Step 4)
- Logged-out access to protected pages: `/profile` and the expense routes are still placeholders in this step and are not protected; recorded here as an intentional gap until Step 4
- A tampered or garbage session cookie is treated as logged-out, never a 500
- A user name containing HTML (`<b>x</b>`) is shown escaped in the nav bar
- `GET /login?email=...&password=...` must not log anyone in

## Acceptance criteria and tests

Each criterion is one test in `tests/test_login_logout.py`. Tests use temporary databases through the `SPENDLY_DB` environment variable (the existing autouse fixture), call `init_db()` after the fixture has set the path, create users through `create_user()` with `generate_password_hash`, and never touch the real `spendly.db`. Unless stated, the test user is `Rahul Sharma`, `rahul@example.com`, `password123`.

- **AC-1** Given an initialised database and no session, when `GET /login` is requested, then the status is 200 and the page has inputs named `email` and `password` and a form that posts to `/login`.
- **AC-2** Given the test user exists, when valid credentials are POSTed, then the response is 302 to `/profile` and the session contains `user_id` equal to the user's id and nothing else: `dict(session) == {"user_id": <id>}` (checked with `client.session_transaction()`).
- **AC-3** Given the test user, when `"  Rahul@EXAMPLE.com "` and the right password are POSTed, then login succeeds as in AC-2.
- **AC-4** Given the test user, when the right email and a wrong password are POSTed, then the status is 401, the page shows "Invalid email or password.", and the session has no `user_id`.
- **AC-5** Given no user with the email `nobody@example.com`, when it is POSTed with any password, then the status is 401 with the same message as AC-4.
- **AC-6** Given the responses from AC-4 and AC-5 (same submitted email text substituted), when their HTML is compared, then the error message and status are identical and neither mentions "email not found", "no account", or "wrong password".
- **AC-7** Given the email `""`, `"   "`, or a missing `email` field, or an empty or missing `password`, when each is POSTed, then each returns 400 with "Please enter your email and password." and no session is created.
- **AC-8** Given a failed login with email `rahul@example.com`, when the page is rendered, then the email appears in the `email` input value and the submitted password appears nowhere in the HTML.
- **AC-9** Given the password `"password123 "` (trailing space) and the test user, when it is POSTed, then the status is 401 and no session is created.
- **AC-10** Given a user registered as `É@x.com` through `/register` (stored lowercase), when `É@X.COM` and the right password are POSTed, then login succeeds.
- **AC-11** Given a logged-in client, when `POST /logout` is sent, then the response is 302 to `/` and the session has no `user_id`.
- **AC-12** Given a client with no session, when `POST /logout` is sent, then the response is 302 to `/` and no exception is raised.
- **AC-13** Given any client, when `GET /logout` is requested, then the status is 405 and a logged-in session remains logged in.
- **AC-14** Given a logged-in client, when `GET /login` and `GET /register` are requested, then each is a 302 to `/profile`; and when `POST /register` is sent, it is also a 302 to `/profile`.
- **AC-15** Given a logged-in client, when `POST /login` with another user's valid credentials is sent, then the response is 302 to `/profile` and the session's `user_id` is unchanged.
- **AC-16** Given a logged-in client, when `GET /` is requested, then the HTML contains the user's name and a form posting to `/logout`, and does not contain the "Get started" link; given a logged-out client, then it contains "Sign in" and "Get started" and no logout form.
- **AC-17** Given a user whose name is `<b>x</b>`, when logged in and `GET /` is requested, then the HTML contains `&lt;b&gt;x&lt;/b&gt;` and not a raw `<b>x</b>` in the nav.
- **AC-18** Given a session whose `user_id` is set to an id that does not exist, when `GET /` is requested, then the status is 200, the page shows the logged-out nav, and the session no longer holds `user_id`.
- **AC-19** Given a client whose session cookie is replaced with garbage, when `GET /login` is requested, then the status is 200 and no exception is raised.
- **AC-20** Given `GET /login?email=rahul@example.com&password=password123`, when requested, then the status is 200 and the session has no `user_id`.
- **AC-21** Given a session pre-populated with an unrelated key (`session["junk"] = 1`) before login, when valid credentials are POSTed, then after login the session contains `user_id` and does not contain `junk`.
- **AC-22** Given a successful login and logout, when the response bodies, `Set-Cookie` values and captured log output (`caplog`) are inspected, then none contain the password or the password hash.
- **AC-23** Given `resolve_secret_key`, when it is called directly, then: with `{"SPENDLY_SECRET_KEY": "abc"}` it returns `"abc"`; with an empty env, or `{"SPENDLY_ENV": "development"}`, it returns a non-empty string of 64 hex characters (and two calls differ); with `{"SPENDLY_ENV": "production"}` and no key it raises `RuntimeError`. In addition, one subprocess test runs `python -c "import app"` with `SPENDLY_ENV=production` and `SPENDLY_SECRET_KEY` removed from the environment, and the process exits non-zero.
- **AC-24** Given a session whose `user_id` is set to an id that does not exist, when `GET /login` is requested, then the status is 200 and the page contains the sign-in form (inputs `email` and `password`).
- **AC-25** Given `app.get_user_by_email` monkeypatched to return `None` and `app.check_password_hash` monkeypatched to record calls, when an unknown email is POSTed, then `check_password_hash` was called once (the dummy-hash comparison) and the status is 401.
- **AC-26** Given the demo user seeded by `seed_db()`, when `demo@spendly.com` / `demo123` is POSTed, then login succeeds.
- **AC-27** Given `GET /login?registered=1`, when requested, then the success banner still shows (regression from Step 2); given `GET /login`, it does not.
- **AC-28** Given a 255-character email or a 129-character password, when POSTed, then the status is 401 with "Invalid email or password." and no exception is raised.
- **AC-29** Given a successful login, when the `Set-Cookie` header of the response is inspected, then the session cookie contains `HttpOnly` and `SameSite=Lax`.
- **AC-30** Given `session_cookie_secure`, when it is called directly, then it returns `True` for `{"SPENDLY_ENV": "production"}` and `False` for an empty env and for `{"SPENDLY_ENV": "development"}`.
- **AC-31** Given a user whose stored `password_hash` is not a valid hash (e.g. `"not-a-hash"`), when that user's email and any password are POSTed, then the status is 401 with "Invalid email or password." and no exception is raised.

## Open questions

1. **Should logout be `POST`-only?** Recommended default: yes (the spec assumes it). A `GET` logout can be triggered by any image or link on another site. The cost is that the nav "Sign out" is a small form button instead of a plain link.
2. **CSRF protection?** Login and logout forms are now state-changing and there is a session. Recommended default: defer a CSRF library, since `SameSite=Lax` already blocks cross-site `POST` cookies in modern browsers, and record it as a known gap to close with the first expense-writing step (Step 7). Alternative: add Flask-WTF now (new dependency).
3. **Where does login redirect?** Recommended default: `/profile` (a Step 4 placeholder for now). Alternative: `/`.
4. **Session lifetime?** Recommended default: browser-session cookie (no "remember me"). Alternative: a 7-day permanent session or a "remember me" checkbox.
5. **Missing secret key in development?** Recommended default: random per-process key, with a hard failure only in production. Alternative: fail in every environment, which is safer but adds a setup step for the learning project.
6. **Rate limiting / lockout for failed logins?** None exists. Recommended default: defer as a known gap; the dummy-hash comparison only hides timing, not brute force.
7. **Should logged-in users be redirected away from `/login` and `/register`?** Recommended default: yes, to `/profile`.
8. **Protect `/profile` now?** Recommended default: no, it is a placeholder; Step 4 adds a `login_required` guard with the real page.

## Definition of done

- [ ] All acceptance criteria AC-1 to AC-31 pass with `pytest -q`, and the existing database and registration tests still pass
- [ ] The app was run by hand (`SPENDLY_SECRET_KEY=dev-only-value .venv/bin/python3 app.py`, port 5001) and each of these was verified in the browser: demo user (`demo@spendly.com` / `demo123`) signs in and lands on the profile placeholder; the nav shows the name and "Sign out"; "Sign out" returns to the landing page with the logged-out nav; a wrong password and an unknown email show the same message; an empty form shows the blank-fields message; email is kept after an error but the password is not; visiting `/login` while signed in redirects away; typing `/logout` in the address bar shows "Method Not Allowed" and does not sign out; a newly registered user can sign in
- [ ] Starting the app with `SPENDLY_ENV=production` and no `SPENDLY_SECRET_KEY` fails with a `RuntimeError`
- [ ] `grep -nEi "select|insert|update|delete" app.py` finds no SQL in `app.py`
- [ ] `grep -nE "secret_key *= *[\"']" app.py` prints nothing (no literal key)
- [ ] `git diff -U0 static/css/style.css | grep -E "^\+.*#[0-9a-fA-F]{3,8}"` prints nothing (no new hard-coded colours in the added rules)
- [ ] No password or hash appears in the terminal output of the running app during the manual run
- [ ] `git status` shows changes only in the files listed under "Files to change" and "Files to create"
