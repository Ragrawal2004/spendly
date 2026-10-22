# Spec: Add Expense Form and CSRF

## Overview

Give the add-expense backend from Step 6 a real page, and close the CSRF gap that has been carried as a known risk since Step 2. `GET /expenses/add` stops returning the placeholder string and renders `templates/add_expense.html`: a form with amount, category (a `<select>` of the seven categories), date (prefilled with today in UTC) and an optional description of up to 200 characters, plus a submit button and a cancel link back to `/profile`. A failed validation no longer returns a plain-text 400. It re-renders the same form, status 400, with the error message and the values the user typed, all escaped by Jinja autoescaping. At the same time every state-changing `POST` (`/expenses/add`, `/login`, `/register`, `/logout`) gets a hand-rolled synchronizer token: `secrets.token_urlsafe(32)` stored in the signed session, sent back as a hidden `csrf_token` field in every form and compared with `secrets.compare_digest`. A missing or wrong token gets a fixed plain-text 400 and changes nothing. The navbar gets an "Add Expense" link for signed-in users. This step also decides open review flag R4 (`Cf` characters are stored). It comes now because Step 7 is the first step where users can submit expenses from a page, and CLAUDE.md blocks deployment until CSRF ships.

## Depends on

- Step 01 (database setup): `expenses` table, `isolated_db` and `client` fixtures.
- Step 02 (registration): `POST /register`, `clean_registration`, `validate_registration`, `register.html`.
- Step 03 (login and logout): `POST /login`, `authenticate`, `POST /logout`, session handling, `load_current_user`, the nav sign-out form.
- Step 04 (profile): `login_required`, `/profile`, its `Cache-Control: no-store` and "200 path never writes the session" rules, `profile.html`.
- Step 05 (PostgreSQL migration): psycopg 3, `%s` placeholders, `spendly_test`.
- Step 06 (add expense backend): `POST /expenses/add`, `clean_expense`, `validate_expense`, `create_expense`, `CATEGORIES`, `MAX_DESCRIPTION`, `MIN_EXPENSE_DATE`, open review flag R4.

## Routes

No new routes. Changed behaviour:

- `GET /expenses/add` — renders the add-expense form (was the placeholder string); sets `Cache-Control: no-store` — logged-in
- `POST /expenses/add` — CSRF check first; a validation error now re-renders the form with status 400 (was plain text); success unchanged (303 to `/profile`) — logged-in
- `POST /login` — CSRF check first; otherwise unchanged; a successful sign-in issues a fresh token — public
- `POST /register` — CSRF check first; otherwise unchanged — public
- `POST /logout` — CSRF check first; otherwise unchanged — logged-in (a signed-out session with a valid token still just clears and redirects, as today)
- `GET /login` — the 200 page now embeds the session token, so it sets `Cache-Control: no-store`; otherwise unchanged (signed-in users are still redirected to `/profile`) — public
- `GET /register` — same: the 200 page sets `Cache-Control: no-store`; otherwise unchanged — public

`GET /login`, `GET /register` and every page that renders a `POST` form make sure the session holds a token before the HTML is sent.

## Database changes

No database changes. Verified against `database/db.py`: `create_expense`, `create_user` and the `users` / `expenses` schema are used as they are. No new queries.

## Templates

- **Create:**
  - `templates/add_expense.html` — extends `base.html`. A `POST` form to `url_for('add_expense')` with:
    - hidden `csrf_token`
    - `amount`: `type="text"` with `inputmode="decimal"`, labelled "Amount (₹)", `required`, `maxlength="18"`
    - `category`: a `<select>` with a first option "Choose a category" (`value=""`, `disabled`), then the seven `CATEGORIES` in order; the submitted category is `selected` on re-render when it is one of the seven
    - `date`: `type="date"`, `value` today in UTC as `YYYY-MM-DD` (or the submitted value on re-render), `min="2000-01-01"`, `max` tomorrow in UTC, `required`
    - `description`: `type="text"` (not a textarea, because line breaks are rejected), `maxlength="200"`, optional
    - a submit button "Add expense" and a "Cancel" link to `url_for('profile')`
    - an error box (same pattern as `auth-error`) shown only when `error` is set
    - Values come only from Jinja expressions with autoescaping, never `|safe`, `Markup` or `{% autoescape false %}`.
- **Modify:**
  - `templates/base.html` — signed-in nav gets an `<a href="{{ url_for('add_expense') }}">Add Expense</a>` link before the user name; the sign-out form gets the hidden `csrf_token` field.
  - `templates/login.html` — hidden `csrf_token` field in the form.
  - `templates/register.html` — hidden `csrf_token` field in the form.
  - `templates/profile.html` — the description cell wraps the text in `<bdi>` (R4 decision); nothing else changes (no dashboard redesign).

## Files to change

- `app.py` — CSRF helpers and hook, token issued at login, `GET /expenses/add` renders the form, `POST /expenses/add` 400 path renders the form.
- `templates/base.html`, `templates/login.html`, `templates/register.html`, `templates/profile.html` — as listed above.
- `static/css/style.css` — styles for the add-expense page and the nav link, using existing variables only.
- `tests/conftest.py` — add the shared CSRF test helpers (see "Conflicts with existing tests"); the existing guards and fixtures are not changed.
- `tests/test_add_expense.py`, `tests/test_login_logout.py`, `tests/test_profile.py`, `tests/test_registration.py` — deliberate updates for the token (see "Conflicts with existing tests").
- `CLAUDE.md` — document the form, CSRF and the R4 decision; remove the "Do not deploy before Step 7" note only after the CSRF ACs pass and the manual check is done. Also update the roadmap (docs item below).

**Docs item — roadmap in CLAUDE.md:** add a step list to CLAUDE.md with the new roadmap: Steps 1–6 as built, Step 7 add-expense form and CSRF (this step), Step 8 dashboard UI, Step 9 list/search/filter expenses, Step 10 edit expense, Step 11 delete expense, Step 12 deploy. Change the Sessions note "until Steps 8-9" to "until Steps 10-11". Do **not** change the placeholder strings in `app.py`: `"Edit expense — coming in Step 8"` and `"Delete expense — coming in Step 9"` stay as they are, and CLAUDE.md says these strings are out of date and will be replaced in Steps 10 and 11.

## Files to create

- `templates/add_expense.html`
- `tests/test_add_expense_form_csrf.py` — one test per acceptance criterion below, named `test_..._acN`.

## New dependencies

No new dependencies. No Flask-WTF, no itsdangerous calls of our own; only the standard library `secrets` module, which `app.py` already imports.

## Rules for implementation

- No SQLAlchemy or ORMs
- Parameterised queries only (`%s` placeholders); this step adds no SQL
- Passwords hashed with werkzeug
- Use CSS variables — never hardcode hex values (no hex outside `:root` in `style.css`)
- No inline styles (`style="..."` attributes or `<style>` blocks) in any template
- All templates extend `base.html`
- Emails are stripped and lowercased in application code before saving or looking up (the database CHECK requires lowercase)
- Login errors never reveal whether the email or the password was wrong
- Secrets such as the Flask secret key come from environment variables, never from the code
- Passwords and password hashes are never printed or logged
- Never print `DATABASE_URL`, `SPENDLY_TEST_DATABASE_URL` or the CSRF token in logs or error messages
- Money stays `Decimal`; currency is shown as `₹`
- `clean_expense`, `validate_expense` and `create_expense` are called unchanged (same signatures, same messages, same check order)
- **CSRF token design (decided):**
  - One token per session, not per request. It is created with `secrets.token_urlsafe(32)` the first time a form needs it and stored as `session["csrf_token"]`.
  - It is replaced whenever the session's privilege changes: a successful login runs `session.clear()`, then sets `user_id` and a new token; logout clears the session, so the old token dies with it.
  - **Why per session:** per-request rotation breaks the back button, a second open tab and double-submit recovery, and adds a session write (and `Set-Cookie`) on every response. That would break the Step 4 and Step 6 "never writes the session" rules and would add no real protection here. The token sits in a signed, `HttpOnly` cookie session and is never put in a URL. Rotating at login stops a token planted before sign-in from being reused after it.
  - A helper (e.g. `get_csrf_token()`) returns the session token, creating it if missing. It is exposed to templates as `csrf_token()`, and every `<form method="POST">` renders `<input type="hidden" name="csrf_token" value="{{ csrf_token() }}">`.
  - One `before_request` hook checks every `POST` that matched a route (`request.endpoint` is not `None`). It is registered **before** `load_current_user`, so a tampered or stale request is rejected before any database work and before the session can be cleared. Non-`POST` methods are not checked, and neither are unmatched requests, so 404 and 405 stay as they are.
  - The check passes only when the session token is a non-empty `str`, the submitted `request.form["csrf_token"]` is a non-empty `str`, and `secrets.compare_digest(submitted.encode("utf-8"), expected.encode("utf-8"))` is true. Comparing bytes avoids the `TypeError` that `compare_digest` raises on non-ASCII `str`. A missing token on both sides never counts as a match.
  - On failure the hook returns `"Invalid or missing form token. Reload the page and try again."`, status 400, `Content-Type: text/plain; charset=utf-8`. It never echoes input or the token, never touches the database and never modifies the session, so no `Set-Cookie`.
  - The token is read only from the form body, never from the query string or a header.
- `GET /expenses/add` and its 400 re-render, and the 200 pages of `GET /login` and `GET /register`, set `Cache-Control: no-store` (each page carries the session token).
- The 400 re-render passes the cleaned values from `clean_expense` back to the template; the success and 400 paths still never write the session (the token already exists because the request passed the check).
- **R4 decision:** `Cf` characters (zero-width joiners, zero-width spaces, bidi marks and overrides) are kept and stored; `validate_expense` is not changed. ZWJ and ZWNJ are required in Devanagari and other Indic scripts and inside emoji sequences, so rejecting `Cf` would block real Indian-language descriptions. A description is only ever shown to its owner and is always escaped. The one real effect, a bidi override reordering the text around it, is contained by wrapping the description in `<bdi>` on the profile page. Record this in CLAUDE.md and close R4.
- No dashboard redesign; `/profile` changes only by the `<bdi>` wrap and the nav link.
- Tests use `spendly_test` only; one test per acceptance criterion.

## Error handling

| Action | Required result |
| --- | --- |
| Any protected `POST` (`/expenses/add`, `/login`, `/register`, `/logout`) without a `csrf_token` field | HTTP 400, `text/plain; charset=utf-8`, body exactly `Invalid or missing form token. Reload the page and try again.`; no database write; no `Set-Cookie` |
| Same, with a wrong token (random, from another session, empty, non-ASCII, very long) | Same 400 and body; no write; no `Set-Cookie`; never a 500 |
| Same, with the right token but the session holds no token | Same 400 (nothing to match) |
| `POST /expenses/add` with a valid token and valid fields, signed in | 303 to `/profile`, one row (unchanged from Step 6) |
| `POST /expenses/add` with a valid token and an invalid field, signed in | HTTP 400, `text/html`, the add-expense page with the exact Step 6 message and the submitted values, escaped; no row; no `Set-Cookie` |
| `POST /expenses/add` with a valid token, signed out | 302 to `/login`; no row |
| `POST /expenses/add` with a valid token, session `user_id` no longer exists | 302 to `/login`, session cleared, no row (CSRF passes first, then `load_current_user` clears) |
| `create_expense` raises `ForeignKeyViolation` | Session cleared, 302 to `/login` (unchanged) |
| `GET /expenses/add`, signed out | 302 to `/login` |
| `GET /expenses/add`, signed in | 200, the form, `Cache-Control: no-store` |
| `GET /login` or `GET /register`, signed out | 200, the form with the token, `Cache-Control: no-store` |
| `GET /login` or `GET /register`, signed in | 302 to `/profile` (unchanged) |
| `POST /login` with a valid token and correct credentials | Session cleared, new `user_id` and new token, 302 to `/profile` |
| `POST /login` with a valid token and wrong credentials | 401 `Invalid email or password.` (unchanged); token not rotated |
| `POST /register` with a valid token | Unchanged behaviour (302 to `/login?registered=1`, or 400 with the existing messages) |
| `POST /logout` with a valid token | Session cleared, 302 to `/` (unchanged) |
| `PUT` / `DELETE /expenses/add` | 405 (unchanged; hook checks only `POST`) |
| `POST` to a `GET`-only route (e.g. `/profile`) | 405, not 400 |
| `POST` to an unknown URL | 404, not 400 |
| Form body over 500 kB | Werkzeug 413 before any view (unchanged) |
| Any other database error | Not caught; Flask 500 |

## Edge cases

- Signed-out visitor opens `/login` or `/register` first: the page render creates the token and sets the session cookie, so the very first `POST` already has one.
- Pages with no form (`/`, `/terms`, `/privacy` when signed out) do not create a token and send no `Set-Cookie`.
- Signed-in pages always render the nav sign-out form, so they always need the token. A real login already stored one, so `/profile` keeps its "200 never writes the session" rule. A session that predates this step (holds `user_id` but no token) gets one written on its first page view. This is accepted and documented.
- Two tabs, back button, resubmitting after a validation error: all use the same per-session token and work.
- Double submit of the add form: both requests carry a valid token and both create rows (no dedupe, as in Step 6); the 303 means refreshing `/profile` does not resubmit.
- A token taken from another user's session, a token from before login, and a token from before logout are all rejected.
- Submitted token with surrounding whitespace is not stripped and so does not match (fixed-format value; nothing legitimate adds whitespace).
- Submitted token that is non-ASCII (`"é" * 43`), empty, or 10,000 characters long: 400, never a 500.
- Duplicate `csrf_token` fields in one body: `request.form.get` takes the first; a wrong first value fails.
- Re-rendered values: `"><script>alert(1)</script>` in the description and `<b>1</b>` in the amount appear only as escaped text; a valid-but-wrong-case category such as `food` is not selected (the placeholder shows); an unparseable date is still put back into the `value` attribute escaped (the browser shows it empty).
- Control characters in a rejected description (e.g. NUL) are echoed escaped in the `value` attribute; Jinja does not strip them and browsers render them as replacement characters. This is harmless and accepted.
- Default date is UTC "today", so a user in India between 00:00 and 05:30 IST sees yesterday prefilled; they can change it, and tomorrow is still accepted (Step 6 window).
- Whitespace around amount/category/date/description is stripped by `clean_expense` as before; the re-rendered values are the stripped ones.
- Signed-out `GET /expenses/add` or `POST /expenses/add` (with a valid signed-out token): redirect to `/login`, nothing written.
- Email letter case and whitespace on login/register: unchanged (stripped and lowercased) once the token passes.
- Description with `Cf` characters (U+202E RLO, U+200B ZWSP, U+200C ZWNJ in `क्‌ष`): stored unchanged; on `/profile` the text is inside `<bdi>`, so an override cannot reorder the rest of the row.

## Conflicts with existing tests

These existing tests post forms without a token, or assert behaviour this step changes on purpose. The design must list each change; none may be silently deleted.

- All `client.post(...)` call sites that post a form must first obtain a token and send it. That is 31 calls in `tests/test_add_expense.py` (20), `tests/test_login_logout.py` (8), `tests/test_profile.py` (2) and `tests/test_registration.py` (1), including the `_post_login` and registration `post` helpers.
- **Shared helper in `tests/conftest.py`:** two plain functions, imported by the test files:
  - `csrf_token(client)` returns `session["csrf_token"]` for that client. If the session has none, it first stores a fresh `secrets.token_urlsafe(32)` through `client.session_transaction()`, the same value shape the app creates.
  - `post_form(client, url, data, **kwargs)` copies `data`, adds `csrf_token=csrf_token(client)` unless the caller already passed a `csrf_token` key, and returns `client.post(url, data=..., **kwargs)`.
  - Existing call sites switch from `client.post(url, data=...)` to `post_form(client, url, ...)`. The missing-token and wrong-token ACs call `client.post` directly, or pass their own `csrf_token`.
- The `login_as` helpers in `test_add_expense.py`, `test_profile.py` and `test_login_logout.py` set only `session["user_id"]`. They keep setting it and then call `csrf_token(client)`, so the session holds a token the way a real login leaves it. Otherwise rendering the nav form writes the session, and `test_profile.py:356` (no `Set-Cookie` on `/profile`) fails.
- Step 6 AC-1 (signed-out POST → 302): now needs a valid token; without one the answer is the CSRF 400.
- Step 6 AC-12 (plain-text 400 with an exact body): becomes an HTML 400 that contains the message.
- Step 6 AC-13 (input never echoed): becomes "input echoed only escaped"; the raw tags must still not appear.
- Step 6 AC-18 (placeholder body): becomes the rendered form; the signed-out redirect half stays.
- Step 6 AC-27 (exact plain-text body for control characters): becomes "400 HTML containing the message, table empty".
- Step 6 AC-19 (405 for `PUT`/`DELETE`) and AC-20 (deleted user → 302) must still pass unchanged apart from sending the token on `POST`.

## Acceptance criteria and tests

Each criterion is one test in `tests/test_add_expense_form_csrf.py`, named `test_..._acN`. Tests use the `spendly_test` PostgreSQL database (dropped and recreated before every test by `isolated_db` and `client`). They create users with `create_user()` and `generate_password_hash`, and read rows with parameterised `SELECT`s through `get_db()`. They get a token either by `GET`ting a form page and reading the hidden field, or through the shared `csrf_token(client)` / `post_form(...)` helpers in `tests/conftest.py`. They never touch `spendly` or `spendly.db`. "The CSRF 400" means status 400, `Content-Type` starting with `text/plain`, and body exactly `Invalid or missing form token. Reload the page and try again.` The valid expense form is `amount=250`, `category=Food`, `date=<today UTC>`, `description=Lunch`.

**Add-expense form**

- **AC-1** Given no session, when `GET /expenses/add` is requested, then the response is 302 to `/login`.
- **AC-2** Given a signed-in user, when `GET /expenses/add` is requested, then the status is 200 and the HTML has the site nav, a `POST` form to `/expenses/add` with inputs `amount`, `date` (value today UTC, `min="2000-01-01"`, `max` tomorrow UTC) and `description` (`maxlength="200"`), a `category` select whose non-empty options are exactly the seven categories in `CATEGORIES` order, a submit button, and a link to `/profile`.
- **AC-3** Given a signed-in user whose session already holds a token, when `GET /expenses/add` is requested, then the hidden `csrf_token` value equals `session["csrf_token"]`, `Cache-Control` is `no-store`, and no `Set-Cookie` header is sent.
- **AC-4** Given a signed-in user and a valid token, when `amount=abc`, `category=Bills`, `date=2026-10-01`, `description=Taxi` is posted, then the status is 400, `Content-Type` starts with `text/html`, the page shows `Enter a valid amount, like 250 or 99.50.`, the amount field has `value="abc"`, `Bills` is the selected option, the date field has `value="2026-10-01"`, the description field has `value="Taxi"`, the `expenses` table is empty, and no `Set-Cookie` is sent.
- **AC-5** Given a signed-in user and a valid token, when a form with `amount=<b>1</b>` and `description="><script>alert(1)</script>` is posted, then the 400 HTML contains `&lt;script&gt;` and `&lt;b&gt;` and does not contain `<script>alert(1)` or `<b>1</b>`.
- **AC-6** Given a signed-in user and a valid token, when forms that fail only on category (`food`), only on date (`1999-12-31`) and only on description (201 characters) are posted, then each is a 400 HTML page showing exactly the Step 6 message for that field, and no row is written.
- **AC-7** Given a registered user and a fresh client, when the user `GET`s `/login`, posts credentials with the token read from that page, `GET`s `/expenses/add`, and posts the valid form with the token read from that page, then the post returns 303 to `/profile`, and following it shows `Lunch` and `₹250.00`.

**CSRF on `POST /expenses/add`**

- **AC-8** Given a signed-in user whose session holds a token, when the valid form is posted without `csrf_token`, then the response is the CSRF 400, the `expenses` table is empty, and no `Set-Cookie` is sent.
- **AC-9** Given a signed-in user whose session holds a token, when the valid form is posted with a different `secrets.token_urlsafe(32)` value, then the response is the CSRF 400, the table is empty, and no `Set-Cookie` is sent.
- **AC-10** Given a signed-in user whose session holds a token, when the valid form is posted with that token, then the response is 303 to `/profile` and exactly one row exists for the user.

**CSRF on `POST /login`**

- **AC-11** Given a registered user and a session holding a token, when correct credentials are posted to `/login` without `csrf_token`, then the response is the CSRF 400, no `Set-Cookie` is sent, and a following `GET /profile` redirects to `/login`.
- **AC-12** Given the same, when correct credentials are posted with a wrong token, then the response is the CSRF 400, no `Set-Cookie` is sent, and the user is not signed in.
- **AC-13** Given the same, when correct credentials are posted with the session's token, then the response is 302 to `/profile` and `session["user_id"]` is the user's id.

**CSRF on `POST /register`**

- **AC-14** Given a session holding a token, when a valid registration is posted without `csrf_token`, then the response is the CSRF 400 and the `users` table has no row for that email.
- **AC-15** Given a session holding a token, when a valid registration is posted with a wrong token, then the response is the CSRF 400 and no user row exists.
- **AC-16** Given a session holding a token, when a valid registration is posted with that token, then the response is 302 to `/login?registered=1` and one user row exists.

**CSRF on `POST /logout`**

- **AC-17** Given a signed-in user whose session holds a token, when `/logout` is posted without `csrf_token`, then the response is the CSRF 400, no `Set-Cookie` is sent, and a following `GET /profile` is 200.
- **AC-18** Given the same, when `/logout` is posted with a wrong token, then the response is the CSRF 400 and the user is still signed in.
- **AC-19** Given the same, when `/logout` is posted with the session's token, then the response is 302 to `/` and the session holds neither `user_id` nor `csrf_token`.

**Token lifecycle and checking rules**

- **AC-20** Given a fresh client with no cookie, when `GET /login` and (on another fresh client) `GET /register` are requested, then each response sets a session cookie, and the page's hidden `csrf_token` value equals `session["csrf_token"]`, is at least 43 characters long, and uses only URL-safe base64 characters.
- **AC-21** Given a signed-in user, when `GET /expenses/add` is requested twice and the valid form is then posted twice with the token from the first page, then both pages show the same token and both posts return 303 (two rows): the token is per session, not per request.
- **AC-22** Given a fresh client that `GET`s `/login` (token T1), when it signs in with T1, then `session["csrf_token"]` is a new value T2 ≠ T1, and posting `/logout` with T1 gives the CSRF 400.
- **AC-23** Given a signed-in user who logs out with a valid token T, when `/login` is then posted with T and correct credentials, then the response is the CSRF 400.
- **AC-24** Given a session holding token T, when `/login` is posted with T and a wrong password, then the response is 401 and `session["csrf_token"]` is still T.
- **AC-25** Given two clients A and B, each with its own session token, when B posts the valid expense form with A's token, then the response is the CSRF 400 and no row is written.
- **AC-26** Given a signed-in user whose session holds a token, when the valid expense form is posted with `csrf_token` set to `""`, to `"é" * 43`, to a 10,000-character string, and to the right token with a trailing space, then each response is the CSRF 400 (never 500) and no row is written.
- **AC-27** Given a signed-in user whose session holds `user_id` but no `csrf_token`, when the valid expense form is posted with `csrf_token=""` and again with no field, then each response is the CSRF 400 (an empty value never matches an absent one).
- **AC-28** Given a session holding a valid token and a `user_id` that does not exist, when the valid expense form is posted with that token, then the response is 302 to `/login`, the session no longer holds `user_id`, and no row is written (the CSRF check runs before `load_current_user`).
- **AC-29** Given a signed-in user with no token sent, when `PUT /expenses/add`, `DELETE /expenses/add` and `POST /profile` are sent, then each returns 405; and `POST /no-such-page` returns 404.
- **AC-30** Given a fresh client with no cookie, when `GET /`, `GET /terms` and `GET /privacy` are requested, then each is 200 and none sends a `Set-Cookie` header.
- **AC-31** Given a signed-out client on `/login` and `/register`, and a signed-in client on `/profile` and `/expenses/add`, when each page is fetched, then every `<form method="POST">` in its HTML contains a hidden `csrf_token` input with the session's token.

**Navbar**

- **AC-32** Given a signed-in user, when `/profile` and `/expenses/add` are fetched, then each has a link to `/expenses/add` with the text `Add Expense`; and given no session, `/`, `/login` and `/register` have no such link.

**R4 and Step 4 rule**

- **AC-33** Given a signed-in user and a valid token, when descriptions `"‮abc"`, `"a​b"` and `"क्‌ष"` are posted, then each is stored exactly as sent, and `/profile` shows each description inside a `<bdi>` element.
- **AC-34** Given a user who signed in through `GET /login` and `POST /login`, when `GET /profile` is requested, then the status is 200 and no `Set-Cookie` header is sent (the token issued at login means the nav form does not write the session).

**Caching of token pages**

- **AC-35** Given a fresh client with no cookie, when `GET /login` and `GET /register` are requested, then each response is 200 with `Cache-Control` equal to `no-store`.

## Open questions

None. The decisions the request left to this spec are made in "Rules for implementation":

- **Token lifetime:** per session, rotated at login and dropped at logout (justified above).
- **CSRF failure response:** fixed plain-text 400, not an HTML page, so it can never echo input and needs no token to render.
- **Check placement:** one global `before_request` hook on matched `POST`s, registered before `load_current_user`, so future `POST` routes are protected by default.
- **R4:** keep `Cf` characters, contain bidi with `<bdi>` on display.

## Definition of done

- [ ] All acceptance criteria pass with `.venv/bin/pytest -q`, and so does the full existing suite after the deliberate updates listed under "Conflicts with existing tests".
- [ ] Every protected route has one test each for a missing, a wrong and a valid token (AC-8 to AC-19).
- [ ] All 236 existing tests are still collected and none is deleted: `.venv/bin/pytest --collect-only -q` shows 236 plus the 35 new tests (271), and `git diff main --stat -- tests/test_add_expense.py tests/test_login_logout.py tests/test_profile.py tests/test_registration.py tests/test_database.py` together with `git diff main -- <those files> | grep '^-def test_'` shows no test function removed or renamed.
- [ ] `git diff main` on those old test files shows only two kinds of change:
  - adding the token: switching to `post_form` or `csrf_token`, and the `login_as` change
  - the five Step 6 ACs listed as intentional changes under "Conflicts with existing tests" (AC-1, AC-12, AC-13, AC-18, AC-27)
  
  No other assertion is loosened or removed.
- [ ] `grep -n "|safe\|Markup\|autoescape false" templates/` finds nothing.
- [ ] `grep -n "style=" templates/` finds nothing, and every hex colour in `static/css/style.css` sits inside `:root`.
- [ ] `grep -n "coming in Step 7" app.py` finds nothing.
- [ ] `clean_expense`, `validate_expense` and `create_expense` are unchanged in `git diff main`.
- [ ] `requirements.txt` is unchanged.
- [ ] `spendly.db` is untouched (`shasum` before and after the test run match), and the tests ran only against `spendly_test`.
- [ ] The app was run by hand (`SPENDLY_SECRET_KEY=dev-only-value .venv/bin/python3 app.py`), and each user-visible item was checked in the browser:
  - [ ] signed out: the nav has no "Add Expense" link; register and sign in work from the real pages
  - [ ] signed in: the nav shows "Add Expense"; the form shows today's date and the seven categories; Cancel goes to `/profile`
  - [ ] a valid expense shows up on `/profile`
  - [ ] an invalid amount shows the error with the typed values kept
  - [ ] sign out works
  - [ ] changing the hidden `csrf_token` in dev tools and submitting gives the fixed 400 and adds nothing
  - [ ] a description with U+202E does not reorder the other text in its row
- [ ] CLAUDE.md describes the add-expense form, the CSRF design (per-session token, rotated at login, global hook before `load_current_user`, fixed 400) and the R4 decision.
- [ ] CLAUDE.md has the new roadmap (Step 8 dashboard UI, 9 list/search/filter, 10 edit, 11 delete, 12 deploy), and its Sessions note says "until Steps 10-11". `git diff main -- app.py | grep "coming in Step"` shows only the removed Step 7 placeholder; the Step 8 and Step 9 placeholder strings are unchanged.
- [ ] The CLAUDE.md "Do not deploy before Step 7" note and the "no CSRF token on any form" known gap are removed only after the two checks above (CSRF tests and the manual tamper check) pass.
