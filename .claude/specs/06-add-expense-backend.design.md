# Design: Add Expense Backend (Step 6)

Source: `.claude/specs/06-add-expense-backend.md`. Branch `feature/add-expense-backend`.

## 1. Signatures and placement

### `app.py`
Imports (merged into the existing lines, alphabetical like today):
```python
import os
import re
import secrets
import unicodedata
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
...
from database.db import (create_expense, create_user, ...)   # create_expense first, alphabetical
```

Module constants: after `_DUMMY_PASSWORD_HASH` (line 54), so they sit with the other module-level config:
```python
CATEGORIES = ("Food", "Transport", "Bills", "Health", "Entertainment", "Shopping", "Other")
MAX_AMOUNT = Decimal("10000000.00")
MIN_EXPENSE_DATE = date(2000, 1, 1)
MAX_DESCRIPTION = 200
_AMOUNT_RE = re.compile(r"[0-9]{1,15}(\.[0-9]{1,2})?")
_DATE_RE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
```

Helpers: placed directly above the add-expense route, the same way `clean_registration`/`validate_registration`
sit above `register` and `clean_login`/`authenticate` sit above `login`:
```python
def clean_expense(form) -> tuple[str, str, str, str]
def validate_expense(amount, category, date, description, today) -> tuple[str | None, dict | None]
```

Route: replaces the placeholder at `app.py:302-304`. It moves out of the "Placeholder routes" block to just
after `profile()`, and the endpoint name stays `add_expense`:
```python
@app.route("/expenses/add", methods=["GET", "POST"])
@login_required
def add_expense():
```

### `database/db.py`
Placed after `create_user()` (the other write function):
```python
def create_expense(
    user_id: int, amount: Decimal, category: str, date: date, description: str | None
) -> int:
    with closing(get_db()) as conn:
        row = conn.execute(
            "INSERT INTO expenses (user_id, amount, category, date, description) "
            "VALUES (%s, %s, %s, %s, %s) RETURNING id",
            (user_id, amount, category, date, description),
        ).fetchone()
        return row["id"]
```
db.py imports needed by the annotations:
```python
from datetime import date, datetime, timezone   # `date` is already imported on line 3; keep it
from decimal import Decimal                      # new
```
Check that nothing else in db.py shadows `date` at module level. As of now nothing does: `seed_db` uses
`date_str`, and the only `date` names are SQL column names inside strings. The `date` parameter of
`create_expense` shadows the class only inside that function, which never uses the class.
Annotations are resolved in module scope, so `date: date` refers to the class.
A single statement with autocommit needs no `conn.transaction()` (same as `create_user`). It catches nothing.

## 2. Validation: regexes, order, messages

`clean_expense(form)`: `form.get(k, "").strip()` for `amount`, `category`, `date`, `description`. Only these
four keys are read, so `user_id` or any other field is never looked at.

`validate_expense` runs these checks in order and returns on the first failure, `(msg, None)`:

| # | Check | Message |
|---|---|---|
| 1 | `_AMOUNT_RE.fullmatch(amount)` fails | `Enter a valid amount, like 250 or 99.50.` |
| 2 | `Decimal(amount) <= 0` | `Amount must be greater than ₹0.` |
| 3 | `Decimal(amount) > MAX_AMOUNT` | `Amount must be ₹1,00,00,000 or less.` |
| 4 | `category not in CATEGORIES` | `Please choose a category.` |
| 5 | `_DATE_RE.fullmatch(date)` fails, or parse raises `ValueError` | `Enter a valid date.` |
| 6 | not `MIN_EXPENSE_DATE <= d <= today + timedelta(days=1)` | `Date must be between 1 January 2000 and tomorrow.` |
| 7 | `len(description) > MAX_DESCRIPTION` | `Description must be 200 characters or fewer.` |
| 8 | any `unicodedata.category(c) == "Cc"` | `Description cannot contain line breaks or control characters.` |

On success it returns `(None, {"amount": Decimal, "category": str, "date": date, "description": str | None})`,
with `description = description or None`. The amount is never converted with `float`. Rules for both regexes:
`[0-9]` instead of `\d`, and `fullmatch` instead of `match`/`$`.

Date parse: see C5. The parameter named `date` hides the `date` class inside the function, so the parse is
`datetime.strptime(date, "%Y-%m-%d").date()`, run only after `_DATE_RE` matches. For any input the regex lets
through, it accepts and rejects exactly what `date.fromisoformat` would (`2026-02-30` and `0000-01-01` both
raise `ValueError`).

## 3. Description control-character rule
- The text is stripped in `clean_expense`, so leading/trailing `\t \n \r` are already gone (`"Lunch\n"` → `"Lunch"`).
- Blank after stripping → `None`. The length and control checks are skipped (nothing to check).
- The length check (step 7) runs before the control check (step 8).
- Rejected: any char with `unicodedata.category(c) == "Cc"`, i.e. U+0000–U+001F, U+007F, U+0080–U+009F. That
  includes inner `\n`, `\r`, `\t` and `\x00` (`\x00` is never stripped, and without this check it would reach
  PostgreSQL and raise `DataError` → 500).
- Not rejected: other categories (`Cf` such as zero-width joiner, emoji, Devanagari). The spec does not ask for
  that (see R4).

## 4. Route flow
1. `@login_required`: if `g.current_user` is falsy → 302 `/login`. That covers no session, a non-int
   `user_id`, and an unknown `user_id` (the existing `load_current_user` clears it).
2. `GET` → `return "Add expense form — coming in Step 7"` (200).
3. `POST`: `amount, category, date_str, description = clean_expense(request.form)`.
4. `error, values = validate_expense(..., today=datetime.now(timezone.utc).date())`.
5. If `error` → `return error, 400, {"Content-Type": "text/plain; charset=utf-8"}`. The body is the fixed
   message, user input is never echoed, and the session is not touched.
6. `try: create_expense(g.current_user["id"], **values)`
   `except psycopg.errors.ForeignKeyViolation: session.clear(); return redirect(url_for("login"))` (302).
   Any other exception is not caught → 500.
7. `return redirect(url_for("profile"), code=303)`.
- Other methods → Flask's 405 (from `methods=`). The route never reads `session[...]`.

## 5. Acceptance criteria → tests (all in `tests/test_add_expense.py`)

Local helpers, copying the `tests/test_profile.py` pattern: `_make_user(name, email)` (calls `init_db()` +
`create_user`), `login_as(client, uid)` via `client.session_transaction()`, `_rows(uid=None)` (a parameterised
SELECT through `get_db()`), `_valid_form(**over)`, `_today()` = `datetime.now(timezone.utc).date()`.

| AC | Test | Kind |
|---|---|---|
| AC-1 | `test_post_signed_out_redirects_ac1` | route |
| AC-2 | `test_post_valid_creates_row_ac2` | route |
| AC-3 | `test_post_strips_whitespace_ac3` | route |
| AC-4 | `test_blank_description_stored_null_ac4` | route |
| AC-5 | `test_invalid_amount_format_ac5` (parametrised) | pure |
| AC-6 | `test_amount_bounds_ac6` | pure |
| AC-7 | `test_category_ac7` | pure |
| AC-8 | `test_date_rules_ac8` (includes ISO week `2026-W43-4` and compact `20261022`, both rejected) | pure |
| AC-9 | `test_date_year_rollover_ac9` | pure |
| AC-10 | `test_description_length_ac10` | pure |
| AC-11 | `test_check_order_ac11` | pure |
| AC-12 | `test_invalid_post_plain_text_400_ac12` | route |
| AC-13 | `test_error_does_not_echo_input_ac13` | route |
| AC-14 | `test_form_user_id_ignored_ac14` | route |
| AC-15 | `test_double_submit_two_rows_ac15` | route |
| AC-16 | `test_profile_totals_exact_ac16` | route + profile |
| AC-17 | `test_description_escaped_on_profile_ac17` | route + profile |
| AC-18 | `test_get_placeholder_protected_ac18` | route |
| AC-19 | `test_other_methods_405_ac19` | route |
| AC-20 | `test_unknown_session_user_ac20` | route |
| AC-21 | `test_foreign_key_violation_clears_session_ac21` (monkeypatch `app.create_expense`) | route |
| AC-22 | `test_no_set_cookie_ac22` | route |
| AC-23 | `test_create_expense_roundtrip_ac23` | db |
| AC-24 | `test_create_expense_constraints_ac24` | db |
| AC-25 | `test_clean_expense_ac25` (werkzeug `MultiDict`) | pure |
| AC-26 | `test_end_to_end_login_add_profile_ac26` | route |
| AC-27 | `test_description_control_chars_ac27` (includes `\x00`, an inner `\n` and an inner `\t`: each a 400, never a 500, no row written) | route |

Existing suites (`test_database.py`, `test_registration.py`, `test_login_logout.py`, `test_profile.py`) must
still pass without changes.

## 6. Conflicts

- **C1 — Placeholder route.** Today `app.py:302` is `GET`-only, public, and returns
  `"Add expense — coming in Step 7"`. The spec makes it `GET`/`POST`, puts it behind `@login_required`, and
  changes the text to `"Add expense form — coming in Step 7"`. *Resolution:* follow the spec. I checked the
  tests: no test asserts the old text or public access to `/expenses/add`, so nothing breaks.
- **C2 — Profile "Add expense" link.** `templates/profile.html:49` uses `url_for('add_expense')`, and
  `test_profile_nav_and_add_expense_links_ac20` asserts `href="/expenses/add"`. *Resolution:* keep the function
  name `add_expense` and the URL, so the link and the test stay as they are. Signed-in users reach the
  placeholder. No template change.
- **C3 — CLAUDE.md.** The Architecture section says routes return placeholders like
  `"Add expense — coming in Step 7"`, and the known gaps say all `/expenses/*` placeholders are public until
  Steps 7-9. *Resolution:* the spec already lists CLAUDE.md as a file to change. Update the example text and the
  gaps note (only edit/delete stay public), and add the CSRF-deferred / do-not-deploy note.
- **C4 — Test fixtures and sign-in.** `conftest.py` has only `isolated_db` (drops the tables) and `client`
  (runs `init_db()`). There is no shared user or sign-in fixture: `_make_user` and `login_as` are copied per
  file (`test_profile.py:31-38`, `test_login_logout.py:295`). *Resolution:* define local helpers in
  `test_add_expense.py`, the same way the other files do, and leave conftest alone. The db-level tests (AC-23,
  AC-24) must use the `client` fixture or call `init_db()`, because `isolated_db` leaves no tables.
- **C5 — `date` name shadowing.** The spec says to import the `date` class into `app.py` and to parse with
  `date.fromisoformat`, but it also names a `validate_expense` parameter `date`. Inside the function that name
  is the string, so `date.fromisoformat` would raise `AttributeError`. The spec's annotation `datetime.date` in
  `db.py` is also wrong there, because `db.py` imports the `datetime` *class*. *Resolution:* keep the spec's
  signature (tests may call it by keyword, and the returned dict key `date` must match `create_expense(**values)`).
  Parse with `datetime.strptime(date, "%Y-%m-%d").date()` after the regex, which behaves the same for every
  input the regex lets through. Annotate `create_expense` with `date: date`.
- **C6 — Very large form fields. Resolved (spec corrected).** Werkzeug 3.1.6 `max_form_memory_size = 500_000`
  raises `RequestEntityTooLarge` (413) for any urlencoded body over 500 kB, before the view runs. The spec edge
  case now says this: bodies under 500 kB get the 400 from the length and regex rules, and larger ones get
  Flask's 413. *Resolution:* keep the default limit. Nothing is stored either way. No AC covers this.

## 7. Risks / flags for review
- **R1 CSRF:** `POST /expenses/add` is a state-changing endpoint with only `SameSite=Lax`. It is accepted by
  the spec and must be recorded in CLAUDE.md as a blocker before deployment.
- **R2 AC-22 Set-Cookie:** this holds only because the session is non-permanent and the view never writes it.
  Any future `session.permanent` or `SESSION_REFRESH_EACH_REQUEST` change would break it.
- **R3 Time-dependent tests:** route tests post `date=<today UTC>`. If the run crosses UTC midnight, today
  could change mid-test (still within tomorrow's slack, so it passes). The pure tests pass `today` explicitly.
- **R4 Only `Cc` is rejected:** bidi overrides (U+202E) and zero-width characters (`Cf`) are still stored.
  They are harmless with Jinja escaping, but worth a decision in Step 7.
- **R5 AC-21 exception construction:** `psycopg.errors.ForeignKeyViolation("x")` can be raised directly, the
  same pattern as `test_registration.py:126`.
- **R6 Deviation from spec wording:** C5's `strptime` replaces `date.fromisoformat`. The reviewer should
  confirm this is acceptable, or rename the parameter instead (that changes the spec signature).
