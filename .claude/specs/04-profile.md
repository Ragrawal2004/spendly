# Spec: Profile

## Overview

Replace the `/profile` placeholder string with a real, read-only profile page that is only available to signed-in users. The page shows who the user is (name, email, member-since date) and a summary of their spending: total spent, number of expenses, spent this month, a per-category breakdown, and their five most recent expenses. It is Step 4 of the roadmap: login (Step 3) sends users to `/profile` but the page does not exist and is not protected, and the expense features (Steps 7-9) will later add, edit and delete the rows this page summarises. The page is built against the demo data seeded in Step 1, so it is useful before any expense can be added through the UI.

## Depends on

- Step 01 (database setup): `users` and `expenses` tables, `get_db()`, `seed_db()` demo data, the `isolated_db` / `client` fixtures in `tests/conftest.py`.
- Step 02 (registration): users exist; `create_user()`.
- Step 03 (login and logout): `g.current_user` set by the `load_current_user` hook; the post-login redirect to `/profile`; the nav bar with the user's name and the sign-out form.

## Routes

- `GET /profile` — render the profile page for `g.current_user`; if nobody is signed in, redirect to `/login` (302) — logged-in
- `POST /profile`, `PUT`, `DELETE` and other methods — not allowed: Flask's 405 — n/a (the page is read-only; editing the profile is out of scope)

No other new routes. `/expenses/add`, `/expenses/<id>/edit` and `/expenses/<id>/delete` stay placeholders and stay unprotected in this step (they arrive with Steps 7-9). The profile page may link to `url_for('add_expense')` only.

## Database changes

No database changes: no new tables, columns or constraints. Everything shown is derived from the existing `users` and `expenses` tables.

New read-only functions in `database/db.py`, each using `with closing(get_db()) as conn:` and a parameterised `SELECT` (no string-built SQL), each scoped by `user_id` so one user can never read another user's rows:

- `get_user_profile(user_id) -> sqlite3.Row | None` — returns `id, name, email, created_at` (no password hash), or `None`.
- `get_expense_summary(user_id, month_start, next_month_start) -> sqlite3.Row` — one row with `total` (sum of `amount` over all the user's expenses, `0` when none), `count`, and `month_total` (sum of `amount` where `date >= month_start AND date < next_month_start`, `0` when none). The month bounds are ISO `YYYY-MM-DD` strings computed in application code and passed as parameters. Use `COALESCE(SUM(...), 0)`.
- `get_category_totals(user_id) -> list[sqlite3.Row]` — rows of `category, total, count`, grouped by category, ordered by `total` descending then `category` ascending (stable order for ties).
- `get_recent_expenses(user_id, limit=5) -> list[sqlite3.Row]` — rows of `id, amount, category, date, description`, ordered by `date` descending then `id` descending, at most `limit` rows (the limit is passed as a parameter).

Amounts are stored as `REAL`. All rounding for display happens in the template or the route (`"%.2f"`), never in SQL.

## Templates

- **Create:**
  - `templates/profile.html` — extends `base.html`; blocks: title ("Profile - Spendly"), content. Sections: (1) account card with name, email, "Member since <Month YYYY>"; (2) stat tiles for total spent, this month, number of expenses; (3) "By category" list with each category's total and its share of the overall total as a percentage; (4) "Recent expenses" table (date, category, description, amount) with an empty state; (5) an "Add expense" link to `url_for('add_expense')`.
- **Modify:**
  - `templates/base.html` — make the nav user name (`.nav-user`) a link to `url_for('profile')`.

Empty state: a user with no expenses sees zeroed tiles ("₹0.00", "0 expenses"), no category list, and the text "No expenses yet." instead of the table; the page never divides by zero.

## Files to change

- `app.py` — import the new db functions and `functools.wraps`; add a `login_required` decorator; replace the `profile()` placeholder with the real route, decorated with `@login_required`; add a pure helper `month_bounds(today) -> (month_start, next_month_start)` returning ISO strings (December rolls over to January of the next year); add a `format_amount` Jinja filter (or equivalent) that renders `1234.5` as `₹1,234.50`.
- `database/db.py` — add the four read functions above.
- `templates/base.html` — link on the nav user name.
- `static/css/style.css` — styles for the profile page (`.profile-*`, `.stat-tile`, `.category-row`, `.expense-table`, `.empty-state`), using existing CSS variables only; responsive down to 375px width.
- `CLAUDE.md` — mark Step 4 complete; document `/profile` and the new db functions; remove "`/profile` is not yet protected" from the known gaps.

## Files to create

- `templates/profile.html`
- `tests/test_profile.py`

## New dependencies

No new dependencies.

## Rules for implementation

- No SQLAlchemy or ORMs
- Parameterised queries only
- Passwords hashed with werkzeug (this step does not create or check passwords)
- Use CSS variables — never hardcode hex values (add a new variable to `:root` if a colour is missing)
- All templates extend `base.html`
- Emails are stripped and lowercased in application code before saving or looking up (SQLite NOCASE is ASCII-only); this step only displays the stored email and never looks one up
- Login errors never reveal whether the email or the password was wrong (unchanged; do not touch `authenticate()`)
- Secrets such as the Flask secret key come from environment variables, never from the code
- Passwords and password hashes are never printed or logged, never selected by the profile queries, and never passed to the template
- The route reads the user from `g.current_user`, never from `session` directly; the profile queries use `g.current_user["id"]`, never an id from the URL, query string or form, so a user can only ever see their own data
- Protection is done by a `login_required` decorator in `app.py`, built with `functools.wraps` so the wrapped view keeps its name and docstring: if `g.current_user` is falsy it returns `redirect(url_for('login'))`, otherwise it calls the view. It is applied to `/profile` with `@login_required` placed below `@app.route(...)`. The decorator is the only place that makes this check.
- The unauthenticated redirect is always the fixed `url_for('login')`: no `next` parameter and no user-supplied redirect target
- Data sources on the page: `name` and `email` come from `g.current_user`; `created_at` comes from `get_user_profile(g.current_user["id"])`. If `get_user_profile` returns `None` (the user row vanished between the `before_request` lookup and the route), the route treats the request as signed out: it calls `session.clear()` and returns `redirect(url_for('login'))`, with no exception and no profile data.
- "Member since <Month YYYY>": the route (through a small helper in `app.py`) parses `created_at` with `datetime.strptime(created_at, "%Y-%m-%d %H:%M:%S")` (the format of SQLite `datetime('now')`) and formats it with `"%B %Y"`; the template only prints the result. If `created_at` is `NULL` or does not parse (`TypeError` or `ValueError`), the "Member since" line is omitted and the rest of the page renders normally; it never raises.
- Route code calls the `database/db.py` functions; no SQL in `app.py`
- "This month" uses the server's UTC date (`datetime.now(timezone.utc).date()`, as `seed_db` does); `month_bounds` takes the date as an argument so tests can pass a fixed one
- Jinja autoescaping stays on; never use `|safe` on user data (name, email, description are all user-supplied); template attribute values from user input are always quoted
- The page sets no cookies and changes no session state; it is a pure read
- The page is not cached across users: send `Cache-Control: no-store` on the 200 response so the back button after logout does not re-show it from cache

## Error handling

| Action | Required result |
| --- | --- |
| `GET /profile`, signed in | HTTP 200, profile page |
| `GET /profile`, no session | HTTP 302 to `/login`, no profile data in the body |
| `GET /profile`, session holds a non-int or unknown `user_id` | Session cleared by the existing hook, then HTTP 302 to `/login` |
| `GET /profile`, tampered or garbage session cookie | HTTP 302 to `/login`, no exception |
| `GET /profile`, signed in but `get_user_profile` returns `None` | Session cleared, HTTP 302 to `/login`, no exception |
| `POST /profile` (or any non-GET method) | HTTP 405 |
| Signed-in user has no expenses | HTTP 200, empty state, no exception |
| A user's name, email or expense description contains HTML | Shown escaped, never as markup |
| `GET /profile?user_id=2` or any query string | Ignored; the page still shows the signed-in user's data |
| Any other database error | Not caught; Flask returns HTTP 500 |

## Edge cases

- No expenses at all: zero totals, no category list, "No expenses yet.", no division by zero in the percentage
- Exactly one expense; exactly five expenses; six or more (only the five newest are listed, ordered newest first; same-date ties broken by higher `id` first)
- Expenses dated in previous months or years count in "total" but not in "this month"
- Expense dated on the first or last day of the month is counted in "this month"; one dated on the first day of the next month is not
- December: `month_bounds` for 2026-12-15 gives `2026-12-01` and `2027-01-01`
- Two categories with equal totals are ordered alphabetically
- A category with no expenses is not listed
- Percentages: each category's share is `total / overall_total * 100`, rounded to a whole number with round-half-up (`math.floor(share + 0.5)`), not Python's banker's `round()`; the displayed values may not sum to exactly 100 and that is accepted
- An expense description of 200 characters (no spaces, and one with spaces) wraps inside its table cell; the page has no horizontal scroll at 375px width
- A `NULL` or empty expense description is shown as "—", not "None"
- Very large amounts (e.g. 12345678.9) are formatted with thousands separators and two decimals; floating point sums like 0.1 + 0.2 display as `₹0.30`
- Two users with expenses: each sees only their own totals and rows
- Name containing HTML (`<b>x</b>`) or a very long name (100 chars) does not break the layout (long text wraps)
- Logged-out access: redirected to `/login`; after sign-in the user lands on `/profile` (existing Step 3 behaviour)
- Back button after sign-out: `Cache-Control: no-store` prevents the cached page from being re-shown; a fresh request redirects to `/login`
- Repeated reloads: idempotent, no state change
- The profile route does not touch the placeholder expense routes; those remain publicly reachable and are recorded as an intentional gap until Steps 7-9

## Acceptance criteria and tests

Each criterion is one test in `tests/test_profile.py`. Tests use temporary databases through the `SPENDLY_DB` environment variable (the existing autouse `isolated_db` fixture), call `init_db()` through the `client` fixture, create users with `create_user()` and `generate_password_hash`, insert expenses with direct parameterised inserts through `get_db()`, sign in by setting `session["user_id"]` through `client.session_transaction()`, and never touch the real `spendly.db`. Unless stated, the test user is `Rahul Sharma`, `rahul@example.com`.

- **AC-1** Given no session, when `GET /profile` is requested, then the response is 302 to `/login` and the body contains neither the user's name nor "Profile".
- **AC-2** Given a signed-in user, when `GET /profile` is requested, then the status is 200 and the page contains the user's name, their email and "Member since".
- **AC-3** Given a session whose `user_id` is a non-existent id, when `GET /profile` is requested, then the response is 302 to `/login` and the session no longer holds `user_id`.
- **AC-4** Given a client whose session cookie is replaced with garbage, when `GET /profile` is requested, then the response is 302 to `/login` and no exception is raised.
- **AC-5** Given a signed-in user, when `POST /profile` is sent, then the status is 405.
- **AC-6** Given a signed-in user with expenses of 100.00, 250.50 and 49.50, when the page is requested, then it shows total `₹400.00` and `3 expenses`.
- **AC-7** Given `month_bounds` called directly, when called with 2026-10-21 it returns `("2026-10-01", "2026-11-01")` and with 2026-12-15 it returns `("2026-12-01", "2027-01-01")`.
- **AC-8** Given `get_expense_summary` called directly with expenses dated on the first day of the month, the last day of the month, the first day of the next month and the previous month, when it is called with that month's bounds, then `month_total` counts only the first two and `total` counts all four.
- **AC-9** Given a signed-in user with no expenses, when the page is requested, then the status is 200, it shows `₹0.00`, `0 expenses` and "No expenses yet.", and no category rows are rendered.
- **AC-10** Given expenses in Food (300, 100), Transport (100) and Bills (100), when `get_category_totals` is called, then the rows are `Food 400 (2)`, `Bills 100 (1)`, `Transport 100 (1)` in that order (total descending, ties alphabetical), and the page shows Food with `67%` (round(400 / 600 × 100)).
- **AC-11** Given seven expenses on distinct dates, when `get_recent_expenses` is called, then exactly five rows come back, newest date first; and given two expenses on the same date, the one with the higher `id` comes first.
- **AC-12** Given two users with different expenses, when each is signed in and requests `/profile`, then each page contains only that user's amounts and descriptions and none of the other's.
- **AC-13** Given a signed-in user, when `GET /profile?user_id=<other user's id>` is requested, then the page still shows the signed-in user's name and not the other user's.
- **AC-14** Given a user named `<b>x</b>` with an expense description `<script>alert(1)</script>`, when the page is requested, then the HTML contains `&lt;b&gt;x&lt;/b&gt;` and `&lt;script&gt;` and does not contain a raw `<script>alert(1)</script>`.
- **AC-15** Given an expense with a `NULL` description, when the page is requested, then the row shows "—" and the HTML does not contain the text "None".
- **AC-16** Given an expense of 12345678.9, when the page is requested, then the page contains `₹12,345,678.90`; and given expenses of 0.1 and 0.2, it shows `₹0.30`.
- **AC-17** Given a signed-in user, when the response is inspected, then it has the header `Cache-Control: no-store` and sets no `Set-Cookie` header.
- **AC-18** Given a signed-in user, when the response body is inspected, then it does not contain the user's `password_hash` or the string `password_hash`.
- **AC-19** Given the demo user seeded by `seed_db()` and signed in, when `/profile` is requested, then the page lists exactly five recent expenses and shows the sum of the eight demo amounts as total.
- **AC-20** Given a signed-in user, when `/profile` is requested, then the nav user name is a link to `/profile` and the page contains a link to `/expenses/add`.
- **AC-21** Given a user who signs in through `POST /login` with valid credentials, when the redirect is followed, then the final response is 200 and shows the profile page (end-to-end with Step 3).
- **AC-22** Given a signed-in user who then sends `POST /logout`, when `GET /profile` is requested, then the response is 302 to `/login`.
- **AC-23** Given a view function wrapped with `login_required` and called inside `app.test_request_context()`, when `g.current_user` is `None`, then the result is a redirect whose `Location` is `/login` with no query string (no `next`) and the view body did not run; when `g.current_user` is a user row, then the view body runs and its return value is passed through; and the wrapped function keeps its `__name__`.
- **AC-24** Given a user whose `created_at` is set to the fixed value `2026-03-05 10:20:30`, when the signed-in user requests `/profile`, then the page contains `Member since March 2026`.
- **AC-25** Given a user whose `created_at` is `garbage` or empty (set by an `UPDATE`), or `get_user_profile` monkeypatched to return a row whose `created_at` is `None`, when `/profile` is requested, then the status is 200, the page does not contain "Member since", and no exception is raised.

## Open questions

- Should the page also let users edit their name or change their password? Recommended default: no — read-only in this step; editing is a separate future step.
- Should "this month" use the server's UTC date or a per-user timezone? Recommended default: server UTC date, consistent with `seed_db`; there is no timezone setting on users.
- Currency symbol: `₹` hardcoded? Recommended default: yes, `₹` (the app's tagline and demo data are in rupees); no currency setting.
- Should the expense placeholder routes (`/expenses/add` etc.) be login-protected now? Recommended default: no — they are placeholders; protect them in Steps 7-9 when they become real.

## Definition of done

- [ ] All acceptance criteria (AC-1 to AC-25) pass with `pytest -q`, and the existing Step 1-3 tests still pass
- [ ] The app was run by hand (`SPENDLY_SECRET_KEY=dev-only-value .venv/bin/python3 app.py`) and verified in the browser:
  - [ ] Visiting `/profile` signed out redirects to `/login`
  - [ ] Signing in as `demo@spendly.com` / `demo123` lands on a profile page showing "Demo User", the email, total, this-month total, count, the category breakdown and five recent expenses, newest first
  - [ ] A freshly registered user sees the empty state with no errors
  - [ ] Clicking the nav name goes to `/profile`; "Add expense" goes to the placeholder
  - [ ] After "Sign out", the browser back button does not show the profile page content on reload
  - [ ] The layout is readable at 375px width and at desktop width, with no horizontal scroll
  - [ ] An expense with a 200-character description (insert one for the demo user) wraps inside its cell with no horizontal scroll at 375px width
- [ ] No hardcoded hex colours added: `git diff main -- static/css/style.css | grep -E '^\+.*#[0-9a-fA-F]{3,8}\b'` prints nothing, except lines that define variables inside the `:root` block
- [ ] `grep -n "password_hash" templates/profile.html` finds nothing, and no new db function selects `password_hash`
- [ ] `grep -nE "(SELECT|INSERT|UPDATE|DELETE)" app.py` finds no SQL
- [ ] `CLAUDE.md` marks Step 4 complete and no longer lists `/profile` as unprotected
- [ ] `shasum spendly.db` before and after `pytest -q` is identical
