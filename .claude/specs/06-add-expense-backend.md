# Spec: Add Expense Backend

## Overview

Give Spendly its first write path for expenses: a `create_expense()` function in `database/db.py` and a real `POST /expenses/add` handler in `app.py` that reads a submitted form, validates and normalises it, stores the expense for the signed-in user and redirects to `/profile`, where the new row immediately shows up in the totals, the category breakdown and the recent list. This is Step 6 of the roadmap and covers the backend only: there is no add-expense form page yet (the form, its template and inline error display arrive in Step 7, which is why `GET /expenses/add` stays a placeholder). It comes now because Step 5 moved storage to PostgreSQL with exact `NUMERIC(12,2)` money and real `DATE` columns, so the write path is built once against the final schema, and because the profile page (Step 4) already reads everything this step writes. This step also closes part of a known gap: `/expenses/add` stops being public.

## Depends on

- Step 01 (database setup): the `expenses` table and its CHECK constraints (`amount > 0`, the seven categories), `get_db()`, `init_db()`, the `isolated_db` / `client` fixtures.
- Step 02 (registration) and Step 03 (login and logout): users exist; `g.current_user` set by `load_current_user`; signing in through `POST /login`.
- Step 04 (profile): `login_required`, `/profile` and its read functions (`get_expense_summary`, `get_category_totals`, `get_recent_expenses`), which are used to observe the result.
- Step 05 (PostgreSQL migration): psycopg 3, `%s` placeholders, `dict_row`, autocommit, `NUMERIC(12,2)` amounts, `DATE` dates, `spendly_test`.

## Routes

- `POST /expenses/add` — validate the form, insert one expense for `g.current_user`, then `303` redirect to `/profile`; on invalid input return `400` with a fixed plain-text message — logged-in
- `GET /expenses/add` — unchanged placeholder text, now behind `@login_required` (signed out: `302` to `/login`); the text becomes `"Add expense form — coming in Step 7"` — logged-in
- Other methods on `/expenses/add` (`PUT`, `DELETE`, …) — Flask's `405` — n/a

No other new routes. `/expenses/<id>/edit` and `/expenses/<id>/delete` stay public placeholders until Steps 8-9.

## Database changes

No database changes: no new tables, columns, indexes or constraints. The existing `expenses` schema already enforces `amount > 0`, the seven categories, `NOT NULL` on `amount`, `category`, `date`, and the `user_id` foreign key.

New function in `database/db.py`:

- `create_expense(user_id: int, amount: Decimal, category: str, date: datetime.date, description: str | None) -> int` — one parameterised `INSERT INTO expenses (user_id, amount, category, date, description) VALUES (%s, %s, %s, %s, %s) RETURNING id` inside `with closing(get_db()) as conn:`; returns the new `int` id. It does no validation, rounding or formatting of its own and catches nothing: `psycopg.errors.CheckViolation` and `psycopg.errors.ForeignKeyViolation` propagate to the caller. `created_at` is left to the column default.

## Templates

- **Create:** none (the add-expense form page is Step 7).
- **Modify:** none. The profile page's existing "Add expense" link to `url_for('add_expense')` keeps working and now reaches a login-protected placeholder.

## Files to change

- `app.py` — import `re`, `unicodedata`, `create_expense`, `date` and `timedelta`; add the pure helpers `clean_expense(form)` and `validate_expense(amount, category, date, description, today)` plus the module constants `CATEGORIES`, `MAX_AMOUNT`, `MIN_EXPENSE_DATE` and `MAX_DESCRIPTION`; replace the `add_expense()` placeholder with a `GET`/`POST` route decorated with `@login_required`.
- `database/db.py` — add `create_expense()`.
- `CLAUDE.md` — document `POST /expenses/add`, the helpers and `create_expense()`; update the "known gaps" note so only `/expenses/<id>/edit` and `/delete` are listed as public; record in the known gaps that `POST /expenses/add` has no CSRF token yet, that CSRF protection is deferred to Step 7 (which must add a token with acceptance criteria), and that the app must not be deployed until then.

## Files to create

- `tests/test_add_expense.py`

## New dependencies

No new dependencies.

## Rules for implementation

- No SQLAlchemy or ORMs
- Parameterised queries only; no SQL in `app.py`, the route calls `create_expense()`
- Passwords hashed with werkzeug (this step does not create or check passwords)
- Use CSS variables — never hardcode hex values (this step adds no CSS)
- All templates extend `base.html` (this step adds no templates)
- Emails are stripped and lowercased in application code before saving or looking up (the database CHECK requires lowercase); this step reads no email
- Login errors never reveal whether the email or the password was wrong (unchanged; do not touch `authenticate()`)
- Secrets such as the Flask secret key come from environment variables, never from the code
- Passwords and password hashes are never printed or logged
- The owner of the new expense is always `g.current_user["id"]`. Any `user_id`, `id` or similar field in the form, query string or JSON body is ignored; the route never reads `session` directly
- Protection is the existing `login_required` decorator, placed below `@app.route(...)`; no second sign-in check in the view
- `clean_expense(form)` returns `(amount, category, date, description)` as strings: `amount`, `date` and `description` are stripped of surrounding whitespace; `category` is stripped but its case is kept. Missing fields become `""`
- `validate_expense(amount, category, date, description, today)` is pure (no request, no database, no clock — `today` is passed in) and returns `(error, values)`: either `(message, None)` or `(None, {"amount": Decimal, "category": str, "date": datetime.date, "description": str | None})`. Checks run in this order and the first failure wins: amount, category, date, description
- **Amount:** must pass `re.fullmatch(r"[0-9]{1,15}(\.[0-9]{1,2})?", amount)` (ASCII digits only — use `[0-9]`, not `\d`, which matches non-ASCII digits; `fullmatch`, not `match` with `$`, because `$` also matches before a trailing `\n`); this rejects signs, commas, spaces, exponents (`1e3`), `nan`/`inf`, a leading or trailing `.`, more than two decimals, and more than 15 integer digits. Then it is converted with `Decimal(amount)` (never `float`), must be `> 0` and `<= MAX_AMOUNT` (`Decimal("10000000.00")`, ₹1 crore). The 15-digit allowance exists so that a well-formed but too-large amount (9 to 15 integer digits) gets the "₹1,00,00,000 or less" message instead of the format message; 16 or more digits is treated as malformed
- **Category:** must be exactly one of `CATEGORIES` = `("Food", "Transport", "Bills", "Health", "Entertainment", "Shopping", "Other")`, the same seven values and spelling as the schema CHECK; `"food"` or `"FOOD"` is rejected, not corrected
- **Date:** must first pass `re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", date)`, and only then be parsed with `date.fromisoformat` (a `ValueError` means not a real calendar date). The regex check is required because Python 3.11+ `date.fromisoformat` also accepts ISO week dates (`2026-W43-4`) and compact forms (`20261022`), which must be rejected. The date must be no earlier than `MIN_EXPENSE_DATE` (`date(2000, 1, 1)`) and no later than `today + timedelta(days=1)` (one day of slack for users ahead of UTC). The route passes `today = datetime.now(timezone.utc).date()`
- **Description:** optional. Blank (after stripping) becomes `None` and is stored as SQL `NULL`; otherwise it must be at most `MAX_DESCRIPTION` (200) characters, counted after stripping, and must contain no control character: any character whose `unicodedata.category(c)` is `"Cc"` is rejected. That covers `\x00`, every other C0 control (including `\t`, `\n` and `\r`), `\x7f` (DEL) and the C1 controls `\x80`–`\x9f`. Decision: `\n` and `\r` are **not** allowed — the description is a single-line field shown in one table cell, and the Step 7 form uses a single-line `<input>`. Leading or trailing `\t`/`\n`/`\r` are removed by `str.strip()` before this check, so only inner ones are rejected; `\x00` is not whitespace and is never stripped. This check is what prevents a 500: PostgreSQL `TEXT` cannot store NUL, so passing `\x00` to `create_expense` would raise `psycopg.DataError` (uncaught, HTTP 500) instead of a clean 400. The length check runs before the control-character check. Amount, category and date cannot carry a control character past their own checks (regex `fullmatch` and exact membership)
- On success the route calls `create_expense(g.current_user["id"], **values)` and returns `redirect(url_for("profile"), code=303)` (Post/Redirect/Get, so a browser refresh does not resubmit)
- On a validation error the route returns the fixed message as the body with status `400` and `Content-Type: text/plain; charset=utf-8`. The message never echoes user input, and nothing is written to the database
- If `create_expense` raises `psycopg.errors.ForeignKeyViolation` (the user row was deleted after `load_current_user` ran), the route calls `session.clear()` and redirects to `/login`; any other database error (including `CheckViolation`, which validation should make impossible) is not caught and gives Flask's 500
- The route never writes the session on the success or error paths
- CSRF protection is deliberately deferred to Step 7, where the add-expense form exists: this step adds no CSRF token, and `POST /expenses/add` relies only on the `SameSite=Lax` session cookie until then. Step 7's spec must add a CSRF token to the form and its check to `POST /expenses/add`, with acceptance criteria covering a missing token, a wrong token and a valid token. The app must not be deployed (`SPENDLY_ENV=production` or any public host) before Step 7 ships that token. This gap is recorded in the CLAUDE.md known-gaps note
- No rate limiting; no duplicate detection — two identical submissions create two expenses

## Error handling

| Action | Required result |
| --- | --- |
| `POST /expenses/add` with valid fields, signed in | One new row for the signed-in user; HTTP 303, `Location: /profile` |
| `POST /expenses/add`, signed out | HTTP 302 to `/login`; no row written |
| `GET /expenses/add`, signed in | HTTP 200, body `Add expense form — coming in Step 7` |
| `GET /expenses/add`, signed out | HTTP 302 to `/login` |
| `PUT` / `DELETE /expenses/add` | HTTP 405 |
| Amount missing, blank, or not matching the pattern (`abc`, `-5`, `1,000`, `1e3`, `1.234`, `.5`, `nan`, `٥`, 16 or more integer digits such as `"9" * 21`) | HTTP 400, `Enter a valid amount, like 250 or 99.50.` |
| Amount `0` or `0.00` | HTTP 400, `Amount must be greater than ₹0.` |
| Well-formed amount above `10000000.00` (up to 15 integer digits, e.g. `10000000.01`, `123456789`, `999999999999999`) | HTTP 400, `Amount must be ₹1,00,00,000 or less.` |
| Category missing or not one of the seven (including wrong case) | HTTP 400, `Please choose a category.` |
| Date missing, wrong format (`22/10/2026`, `2026-1-5`, ISO week date `2026-W43-4`, compact `20261022`) or not a real date (`2026-02-30`) | HTTP 400, `Enter a valid date.` |
| Date before 2000-01-01 or after tomorrow (UTC) | HTTP 400, `Date must be between 1 January 2000 and tomorrow.` |
| Description longer than 200 characters after stripping | HTTP 400, `Description must be 200 characters or fewer.` |
| Description containing a control character after stripping (`\x00`, inner `\n`, `\r`, `\t`, `\x7f`, C1 controls) | HTTP 400, `Description cannot contain line breaks or control characters.` (never a `psycopg.DataError` 500; input not echoed) |
| User deleted between `load_current_user` and the insert (`ForeignKeyViolation`) | Session cleared, HTTP 302 to `/login`, no exception |
| `create_expense` called directly with `amount = 0` or a bad category | `psycopg.errors.CheckViolation` propagates |
| `create_expense` called directly with an unknown `user_id` | `psycopg.errors.ForeignKeyViolation` propagates |
| Any other database error | Not caught; Flask returns HTTP 500 |

## Edge cases

- Empty form, or a form with only some fields: the first failing check in the order amount → category → date → description is reported
- Surrounding whitespace on amount, date, category and description is stripped (`"  250 "` → `250.00`); inner whitespace in the amount (`"2 50"`) is rejected
- Amount boundaries: `0.01` and `10000000` / `10000000.00` accepted; `0`, `0.00` and `10000000.01` rejected; 9 to 15 integer digits get the "₹1,00,00,000 or less" message, 16 or more get the format message; `99.5` stored as `99.50`; a leading-zero amount like `007` is accepted as `7.00`
- Non-ASCII digits (Arabic-Indic `٥`, full-width `５`) are rejected, not silently converted
- Category letter case: `Food` accepted; `food`, `FOOD`, `Groceries` rejected; `" Food "` accepted after stripping
- Date boundaries: `2000-01-01` and `today + 1 day` accepted; `1999-12-31` and `today + 2 days` rejected; `2024-02-29` accepted, `2026-02-29` rejected; ISO week dates (`2026-W43-4`) and compact dates (`20261022`) rejected even though `date.fromisoformat` accepts them; December 31 → January 1 rollover for "tomorrow" handled by `timedelta`
- Description: blank or whitespace-only stored as `NULL` (profile shows "—"); exactly 200 characters accepted, 201 rejected; HTML such as `<script>` is stored as typed and shown escaped on `/profile`; non-ASCII text (`चाय ☕`) stored and shown unchanged; a NUL byte, an inner line break, tab, DEL or C1 control is rejected with 400 (a NUL would otherwise reach PostgreSQL and raise `psycopg.DataError`); a trailing `\n` (as some clients send) is stripped and accepted
- A `user_id` field in the form pointing at another user is ignored: the expense belongs to the signed-in user and the other user's totals do not change
- Logged-out access: both `GET` and `POST` redirect to `/login` and write nothing
- Session holding a non-int or unknown `user_id`: the existing hook clears it and `login_required` redirects to `/login`
- Repeated submits: each `POST` creates a separate row (no dedupe); the 303 redirect means refreshing `/profile` afterwards does not resubmit
- Very large form fields (e.g. a 1 MB amount or description) are rejected with 400 by the length rules, never stored
- Money stays exact: adding `0.10` and `0.20` makes the profile total `₹0.30`

## Acceptance criteria and tests

Each criterion is one test in `tests/test_add_expense.py`, named `test_..._acN`. Tests use the `spendly_test` PostgreSQL database (dropped and recreated before every test by the autouse `isolated_db` fixture and `client`), create users with `create_user()` and `generate_password_hash`, sign in by setting `session["user_id"]` through `client.session_transaction()`, read rows back with parameterised `SELECT`s through `get_db()`, and never touch `spendly` or `spendly.db`. Unless stated, the user is `Rahul Sharma` / `rahul@example.com`, and the valid form is `amount=250`, `category=Food`, `date=<today UTC>`, `description=Lunch`.

- **AC-1** Given no session, when the valid form is posted to `/expenses/add`, then the response is 302 to `/login` and the `expenses` table is empty.
- **AC-2** Given a signed-in user, when the valid form is posted, then the response is 303 with `Location` `/profile` and exactly one row exists for that user with `amount == Decimal("250.00")`, `category == "Food"`, `date == today` and `description == "Lunch"`.
- **AC-3** Given a signed-in user, when the form `amount="  1234.5 "`, `category=" Bills "`, `date=" 2026-10-01 "`, `description="  Electricity  "` is posted, then the stored row is `Decimal("1234.50")`, `"Bills"`, `date(2026, 10, 1)`, `"Electricity"`.
- **AC-4** Given a signed-in user, when the valid form is posted with `description` set to `""` and in a second request to `"   "`, then both stored rows have `description IS NULL`.
- **AC-5** Given `validate_expense` called directly, when the amount is each of `""`, `"abc"`, `"-5"`, `"+5"`, `"1,000"`, `"1e3"`, `"1.234"`, `".5"`, `"5."`, `"nan"`, `"inf"`, `"2 50"`, `"٥"`, `"５"`, `"250\n"` (unstripped), `"9" * 16`, `"9" * 21`, then each returns `("Enter a valid amount, like 250 or 99.50.", None)`.
- **AC-6** Given `validate_expense` called directly, when the amount is `"0"` or `"0.00"`, then it returns `"Amount must be greater than ₹0."`; when it is `"10000000.01"`, `"123456789"` or `"999999999999999"` (15 digits), then it returns `"Amount must be ₹1,00,00,000 or less."`; and `"0.01"`, `"10000000"` and `"007"` are accepted as `Decimal("0.01")`, `Decimal("10000000")` and `Decimal("7")`.
- **AC-7** Given `validate_expense` called directly, when the category is `""`, `"food"`, `"FOOD"` or `"Groceries"`, then it returns `"Please choose a category."`; and each of the seven valid categories is accepted.
- **AC-8** Given `validate_expense` called directly with `today = date(2026, 10, 22)`, when the date is `""`, `"22/10/2026"`, `"2026-1-5"`, `"2026-02-30"`, `"2026-W43-4"` or `"20261022"`, then it returns `"Enter a valid date."`; when it is `"1999-12-31"` or `"2026-10-24"`, then it returns the "between 1 January 2000 and tomorrow" message; and `"2000-01-01"`, `"2024-02-29"` and `"2026-10-23"` are accepted.
- **AC-9** Given `validate_expense` called directly with `today = date(2026, 12, 31)`, when the date is `"2027-01-01"`, then it is accepted, and `"2027-01-02"` is rejected.
- **AC-10** Given `validate_expense` called directly, when the description is 200 characters, then it is accepted; when it is 201 characters, then it returns `"Description must be 200 characters or fewer."`; and a 200-character description padded with surrounding spaces is accepted.
- **AC-11** Given `validate_expense` called directly with every field invalid, when it is called, then the amount message is returned; with a valid amount and everything else invalid, the category message; with a valid amount and category, the date message.
- **AC-12** Given a signed-in user, when an invalid form (`amount=abc`) is posted, then the status is 400, the `Content-Type` starts with `text/plain`, the body is exactly `Enter a valid amount, like 250 or 99.50.` and the `expenses` table is empty.
- **AC-13** Given a signed-in user, when a form whose description is `<script>alert(1)</script>` and whose amount is `<b>1</b>` is posted, then the 400 body does not contain `<script>` or `<b>` (no input is echoed).
- **AC-14** Given two users and user A signed in, when the valid form is posted with an extra field `user_id=<B's id>`, then the new row belongs to A and B has no expenses.
- **AC-15** Given a signed-in user, when the valid form is posted twice, then two rows exist for that user.
- **AC-16** Given a signed-in user with no expenses, when expenses of `0.10` (Food) and `0.20` (Transport) are posted and `/profile` is then requested, then the profile shows `₹0.30` as the total, `2 expenses`, both categories, and both descriptions in the recent list.
- **AC-17** Given a signed-in user, when a valid form with description `<script>alert(1)</script>` is posted and `/profile` is requested, then the profile HTML contains `&lt;script&gt;alert(1)&lt;/script&gt;` and not the raw tag.
- **AC-18** Given a signed-in user, when `GET /expenses/add` is requested, then the status is 200 and the body is `Add expense form — coming in Step 7`; and given no session, the response is 302 to `/login`.
- **AC-19** Given a signed-in user, when `PUT /expenses/add` and `DELETE /expenses/add` are sent, then each returns 405.
- **AC-20** Given a session whose `user_id` is an id that does not exist, when the valid form is posted, then the response is 302 to `/login`, the session no longer holds `user_id`, and no row is written.
- **AC-21** Given a signed-in user and `create_expense` monkeypatched in `app` to raise `psycopg.errors.ForeignKeyViolation`, when the valid form is posted, then the response is 302 to `/login`, the session no longer holds `user_id`, and no exception escapes.
- **AC-22** Given a signed-in user, when the valid form is posted, then the success response sets no `Set-Cookie` header; and the 400 response for an invalid form sets none either.
- **AC-23** Given `create_expense` called directly for an existing user with `Decimal("99.50")`, `"Health"`, `date(2026, 10, 5)`, `None`, then it returns an `int`, and `SELECT` by that id gives back exactly those values with `description IS NULL` and a non-null `created_at`.
- **AC-24** Given `create_expense` called directly, when `amount` is `Decimal("0")` or `category` is `"Groceries"`, then `psycopg.errors.CheckViolation` is raised; when `user_id` does not exist, then `psycopg.errors.ForeignKeyViolation` is raised; and no row is written in any case.
- **AC-25** Given `clean_expense` called with a `MultiDict` missing every field, then it returns `("", "", "", "")`; and called with `category=" food "`, it returns `"food"` (stripped, case kept).
- **AC-26** Given a user who signs in through `POST /login` with valid credentials, when the valid form is posted with the same client and the redirect is followed, then the final response is 200 and the profile lists the new expense (end-to-end with Steps 3 and 4).
- **AC-27** Given a signed-in user, when the valid form is posted with each of the descriptions `"Lunch\x00"`, `"Line1\nLine2"`, `"a\rb"`, `"a\tb"`, `"a\x7fb"` and `"a\x85b"`, then each response is 400 (not 500) with the exact body `Description cannot contain line breaks or control characters.` (so no input is echoed), and the `expenses` table stays empty; and posting `"Lunch\n"` stores `"Lunch"` (the trailing newline is stripped).

## Decisions

All former open questions are decided, using the recommended defaults:

- **Decided — invalid submissions:** plain-text 400 with a fixed message in this step; the form template and inline errors belong to Step 7, which reuses `validate_expense` unchanged.
- **Decided — date is required:** a blank date is rejected with `Enter a valid date.`; the Step 7 form will prefill today, and a silent default would hide client bugs.
- **Decided — amount limit:** ₹1 crore (`MAX_AMOUNT = Decimal("10000000.00")`), which catches typos with extra zeros while staying far below the `NUMERIC(12,2)` limit of `9999999999.99`.
- **Decided — date window:** 2000-01-01 to tomorrow (server UTC date + 1 day); the one day of slack covers users ahead of UTC (India is UTC+5:30).
- **Decided — description is optional:** stored as `NULL` when blank (the column is nullable and the profile already shows "—"); maximum 200 characters; no control characters, including `\n` and `\r`.
- **Decided — category case:** a wrong-case category such as `food` is rejected, not corrected; the Step 7 form uses a `<select>`, so only crafted requests send other values.
- **Decided — CSRF:** deferred to Step 7 with required acceptance criteria; no deployment before then (see Rules).

## Definition of done

- [ ] All acceptance criteria (AC-1 to AC-27) pass with `pytest -q`, and all existing Step 1-5 tests still pass
- [ ] The app was run by hand (`SPENDLY_SECRET_KEY=dev-only-value .venv/bin/python3 app.py`) and verified:
  - [ ] Signed out, visiting `/expenses/add` in the browser redirects to `/login`
  - [ ] Signed in as `demo@spendly.com` / `demo123`, `/expenses/add` shows `Add expense form — coming in Step 7`, and the profile's "Add expense" link reaches it
  - [ ] Signed in as the demo user, posting a valid expense (for example with the browser devtools `fetch('/expenses/add', {method: 'POST', body: new URLSearchParams({amount: '199.99', category: 'Food', date: '<today>', description: 'Test'})})`) and then loading `/profile` shows the new expense first in the recent list and the total, this-month total, count and Food share updated
  - [ ] Posting `amount=abc` the same way gives a 400 with `Enter a valid amount, like 250 or 99.50.` and `/profile` is unchanged
- [ ] `grep -nE "(SELECT|INSERT|UPDATE|DELETE)" app.py` finds no SQL
- [ ] `grep -n "float(" app.py database/db.py` finds no float conversion of amounts
- [ ] `grep -n "session\[" app.py` shows no new reads of `session` outside `load_current_user`
- [ ] `CLAUDE.md` documents `POST /expenses/add` and `create_expense()`, and lists only the edit and delete placeholders as public
- [ ] The CLAUDE.md known-gaps note says `POST /expenses/add` has no CSRF token yet, that Step 7 must add one with acceptance criteria, and that the app must not be deployed before then
- [ ] `shasum spendly.db` (if the file exists) is identical before and after `pytest -q`
