# Spec: PostgreSQL Migration

## Overview

Move Spendly's data layer from SQLite (`sqlite3`, file `spendly.db`) to PostgreSQL through `psycopg` 3, using raw parameterised SQL and no ORM. This step changes only the database layer and the code that depends on its types: there are no new routes, pages or user-visible features, and every behaviour the current 172 tests protect must still hold. It comes now, after Step 4 and before the expense write features (Steps 7-9), so that add, edit and delete are built once against the final storage: exact `NUMERIC(12,2)` money instead of `REAL`, real `DATE` and `TIMESTAMPTZ` columns instead of text, and a database-enforced lowercase, unique email. The connection string comes from `DATABASE_URL`, which is required in every environment: there is no built-in default, and any process started without it refuses to start. Tests read their URL from `SPENDLY_TEST_DATABASE_URL`, which is also required. Tests move from per-test temporary SQLite files to a dedicated `spendly_test` PostgreSQL database that is reset before every test.

## Depends on

- Step 01 (database setup): schema, `get_db()`, `init_db()`, `seed_db()`, the `isolated_db` / `client` fixtures.
- Step 02 (registration): `create_user()` and the duplicate-email handling in `/register`.
- Step 03 (login and logout): `get_user_by_email()`, `get_user_by_id()`, `resolve_secret_key()`, the production startup checks.
- Step 04 (profile): the four profile read functions and the pure helpers `member_since`, `format_amount`, `category_share`, `month_bounds`.

## Routes

No new routes. Every existing route keeps its methods, status codes, redirects, messages and markup. The `/expenses/*` placeholders are unchanged.

## Database changes

The schema is rewritten for PostgreSQL. The tables, columns, names and meaning stay the same; the types and constraints change as follows. `init_db()` still creates everything with `IF NOT EXISTS`, so running it twice is a no-op.

**`users`**

| Column | SQLite (now) | PostgreSQL (this step) |
| --- | --- | --- |
| `id` | `INTEGER PRIMARY KEY AUTOINCREMENT` | `BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY` |
| `name` | `TEXT NOT NULL`, CHECK trimmed of space/tab/LF/CR is non-empty | `TEXT NOT NULL CHECK (btrim(name, E' \t\n\r') <> '')`, same characters |
| `email` | `TEXT NOT NULL UNIQUE COLLATE NOCASE` | `TEXT NOT NULL CHECK (email = lower(email))`, no column-level `UNIQUE` |
| `password_hash` | `TEXT NOT NULL` | `TEXT NOT NULL` |
| `created_at` | `TEXT NOT NULL DEFAULT (datetime('now'))` (UTC text) | `TIMESTAMPTZ NOT NULL DEFAULT now()` |

- New index: `CREATE UNIQUE INDEX IF NOT EXISTS idx_users_email ON users (email)`. Because the CHECK forces stored emails to lowercase, a plain unique index on `email` is case-insensitive in effect, and `WHERE email = %s` lookups use it. The column-level `UNIQUE` is dropped so there is only one email index.
- The CHECK constraint is named `users_email_lowercase` so its violation is easy to identify.

**`expenses`**

| Column | SQLite (now) | PostgreSQL (this step) |
| --- | --- | --- |
| `id` | `INTEGER PRIMARY KEY AUTOINCREMENT` | `BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY` |
| `user_id` | `INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE` | `BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE` |
| `amount` | `REAL NOT NULL CHECK (amount > 0)` | `NUMERIC(12,2) NOT NULL CHECK (amount > 0)` |
| `category` | `TEXT NOT NULL CHECK (category IN (...7 values...))` | same CHECK, same seven values |
| `date` | `TEXT NOT NULL CHECK (date(date) IS NOT NULL AND date(date) = date)` | `DATE NOT NULL` |
| `description` | `TEXT` | `TEXT` |
| `created_at` | `TEXT NOT NULL DEFAULT (datetime('now'))` | `TIMESTAMPTZ NOT NULL DEFAULT now()` |

- `idx_expenses_user_date ON expenses (user_id, date)` is kept.
- Foreign keys are always enforced in PostgreSQL; `PRAGMA foreign_keys` goes away.
- `NUMERIC(12,2)` holds up to `9,999,999,999.99`. A value with more than two decimals is rounded by PostgreSQL to two (half away from zero) before the CHECK runs, so `0.004` becomes `0.00` and is rejected, and `0.005` becomes `0.01` and is accepted.

**Connection and types (`database/db.py`)**

- `get_db()` returns `psycopg.connect(url, row_factory=dict_row, autocommit=True)`, where `url` comes from `resolve_database_url(os.environ)`. Rows are plain `dict`s: `row["name"]` and `row.keys()` work, `row[0]` does not. Autocommit matches the current `isolation_level = None`: each statement commits on its own, and a failed statement does not leave the connection in an aborted transaction.
- Multi-statement writes (only `seed_db()` today) run inside one `with conn.transaction():` block.
- Every connection is closed after use (`with closing(get_db()) as conn:` stays the pattern; `with conn:` on a psycopg connection also closes it).
- Placeholders change from `?` to `%s`. `cur.lastrowid` does not exist in psycopg; `create_user()` uses `INSERT ... RETURNING id`.
- Values that come back from the database:
  - `amount`, `SUM(amount)`, and `COALESCE(SUM(...), 0)` → `decimal.Decimal` (e.g. `Decimal("400.00")`, `Decimal("0")` for no expenses)
  - `COUNT(*)` → `int`
  - `date` → `datetime.date`
  - `created_at` → timezone-aware `datetime.datetime`
  - `id`, `user_id` → `int` (so `session["user_id"] = user["id"]` still stores an `int` and `load_current_user` still accepts it)
- `get_expense_summary()` still takes ISO `YYYY-MM-DD` strings from `month_bounds()`; its SQL casts them explicitly (`%s::date`) so the comparison is between dates, never text.
- `seed_db()` keeps its "insert the demo user only if missing, all-or-nothing" behaviour without SQLite's `BEGIN IMMEDIATE`: inside one transaction it runs `INSERT INTO users ... ON CONFLICT (email) DO NOTHING RETURNING id`; no returned row means the demo user already exists, so it commits nothing else and returns. Two processes seeding at once cannot create two demo users (the unique index decides).
- Database errors raised to callers are psycopg's: `psycopg.errors.UniqueViolation`, `CheckViolation`, `ForeignKeyViolation` (all subclasses of `psycopg.IntegrityError`), and `psycopg.DataError` subclasses for bad dates and out-of-range amounts.

**`DATABASE_URL`**

New pure helper `resolve_database_url(env)` in `database/db.py`, shaped like `resolve_secret_key(env)`:

- `DATABASE_URL` set and non-empty → returned unchanged.
- unset or empty, in any environment (production, development or none set) → `RuntimeError("DATABASE_URL must be set, e.g. DATABASE_URL=postgresql://USER:PASSWORD@HOST:5432/spendly")`. The message is a fixed string: it shows only the URL shape with placeholders and never contains a value read from the environment, so no real password can appear in it.

The check happens on the first `get_db()` call, which is `startup()` → `init_db()` at import time, so any process without `DATABASE_URL` stops at import with that `RuntimeError` and makes no connection attempt. The secret key check in `resolve_secret_key` still runs first (it runs earlier at import).

**What happens to `spendly.db` and `SPENDLY_DB`**

- `SPENDLY_DB` is removed. No code reads it; if it is set it is ignored. It is removed from `CLAUDE.md`, `tests/conftest.py` and `.claude/commands/create-spec.md`.
- `spendly.db` is no longer opened, created or written by anything. The existing file in the project root is left on disk untouched; nothing deletes it. Its contents are **not** migrated: it only holds the seeded demo user, its eight demo expenses and any hand-made dev accounts, and `seed_db()` recreates the demo data in PostgreSQL on the next development start. The developer may delete the file by hand.
- `.gitignore` keeps `spendly.db` and `*.db` so a stale file is never committed.
- The `sqlite3` import is removed from `app.py` and `database/db.py`; `grep -rn sqlite3 app.py database/ tests/` finds nothing.

## Templates

- **Create:** none.
- **Modify:** none. `profile.html` prints `{{ e["date"] }}`; `str()` of a `datetime.date` is `YYYY-MM-DD`, exactly what is printed today. Amounts already go through `format_amount`.

## Files to change

- `database/db.py` — psycopg connection, `resolve_database_url`, PostgreSQL schema, `%s` placeholders, `RETURNING id`, `seed_db` with `ON CONFLICT DO NOTHING` inside `conn.transaction()`, return type hints changed from `sqlite3.Row` to `dict`.
- `app.py` — drop `import sqlite3`; `register()` catches `psycopg.errors.UniqueViolation` instead of `sqlite3.IntegrityError`; `member_since`, `format_amount` and `category_share` accept the new types (see Rules).
- `requirements.txt` — add `psycopg[binary]` pinned to an exact 3.x version.
- `tests/conftest.py` — rewritten for the `spendly_test` database (see Rules).
- `tests/test_database.py`, `tests/test_registration.py`, `tests/test_login_logout.py`, `tests/test_profile.py` — only the tests and helpers listed in "Existing tests that encode SQLite behaviour", plus the new tests below.
- `CLAUDE.md` — SQLite → PostgreSQL throughout: `DATABASE_URL` and `SPENDLY_TEST_DATABASE_URL` (both required) replace `SPENDLY_DB`; the one-time Docker setup (`docker exec spendly-pg psql -U postgres -d postgres -c "CREATE DATABASE spendly"`, and the same for `spendly_test`); the new return types; the email rule's reason; "No ORM — raw `psycopg`".
  - Note: every example URL in `CLAUDE.md` uses a placeholder password (`postgresql://postgres:PASSWORD@localhost:5432/spendly`), never the developer's real one.
- `.claude/commands/create-spec.md` — the acceptance-criteria paragraph says tests use the `spendly_test` database instead of `SPENDLY_DB` / `spendly.db`.

## Files to create

None. (No new test file: new tests go into the existing files next to the behaviour they cover.)

## New dependencies

- `psycopg[binary]` — PostgreSQL driver (psycopg 3 with the bundled libpq wheel). Pinned to one exact version in `requirements.txt`; the chosen version must ship a wheel for the project's Python (3.14).
- Not a pip package, but required: a PostgreSQL server (14 or newer) running in Docker — container `spendly-pg`, user `postgres`, port 5432 published on `localhost` — with databases `spendly` (development) and `spendly_test` (tests). The app reaches it over TCP through the full URL in `DATABASE_URL`, not through a local socket.

## Rules for implementation

- No SQLAlchemy or ORMs; raw SQL through `psycopg` only, all of it in `database/db.py`
- Parameterised queries only (`%s` placeholders); never build SQL with f-strings, `%` or `+`
- Passwords hashed with werkzeug
- Use CSS variables — never hardcode hex values (no CSS changes are expected in this step)
- All templates extend `base.html` (no template changes are expected in this step)
- Emails are stripped and lowercased in application code before saving or looking up. The reason changes: SQLite `NOCASE` is gone, and the database now rejects (CHECK) any email that is not already lowercase, so an un-lowercased email is an error, not a silent duplicate
- Login errors never reveal whether the email or the password was wrong
- Secrets such as the Flask secret key come from environment variables, never from the code
- Passwords and password hashes are never printed or logged
- `DATABASE_URL` may contain a password: it is never printed, logged, or put into an exception message; no URL with a password is written into the code (there is no built-in URL; the missing-variable messages show only a placeholder shape)
- `app.py` contains no SQL and does not call `psycopg.connect`; the only psycopg name it uses is `psycopg.errors.UniqueViolation`
- `register()` catches `psycopg.errors.UniqueViolation` only. Any other database error, including a `CheckViolation` from the lowercase CHECK, is not caught and gives HTTP 500
- `authenticate()` is unchanged: exactly one `check_password_hash` call on every path
- `member_since(created_at)`:
  - a timezone-aware `datetime` is converted to UTC, then formatted `"%B %Y"` (so the month is the UTC month, as today's SQLite `datetime('now')` is UTC)
  - a naive `datetime` is treated as already UTC
  - a string in `"YYYY-MM-DD HH:MM:SS"` form is still parsed as today (keeps the pure helper's behaviour)
  - anything else (`None`, `""`, `"garbage"`, other types) → `None`, never an exception
- `format_amount(value)` accepts `int`, `float` and `Decimal` and gives the same text for equal values: `Decimal("12345678.90")` → `₹12,345,678.90`, `Decimal("0")` → `₹0.00`, `Decimal("0.30")` → `₹0.30`
- `category_share(total, overall)` accepts `int`, `float` and `Decimal` in any combination and must not mix `Decimal` with `float` arithmetic (`Decimal + 0.5` raises `TypeError`). It returns an `int`: half-up rounding of `total / overall × 100`; `0` when `overall` is `0` or `Decimal("0")`. Results for the current inputs do not change (`(400, 600)` → 67, `(12.5, 100)` → 13, `(0, 0)` → 0)
- No rounding in SQL; formatting stays in `app.py`
- Test fixtures (`tests/conftest.py`):
  - The test database URL is `SPENDLY_TEST_DATABASE_URL`, with no default. If it is unset or empty, the run stops with `pytest.exit("SPENDLY_TEST_DATABASE_URL must be set, e.g. SPENDLY_TEST_DATABASE_URL=postgresql://USER:PASSWORD@HOST:5432/spendly_test")` before `app` is imported and before any connection. The message is a fixed string and never includes `DATABASE_URL` or any other value from the environment
  - Before `app` is imported, conftest **assigns** (not `setdefault`) `os.environ["DATABASE_URL"]` to the test URL, so a developer's own `DATABASE_URL` can never be used, seeded or wiped by tests
  - Safety guard: if the test URL's database name (parsed with `psycopg.conninfo.conninfo_to_dict`) is not exactly `spendly_test`, the run stops with `pytest.exit` before any connection, and nothing is dropped
  - If the server cannot be reached or `spendly_test` does not exist, the run stops once with a message that says to start the container (`docker start spendly-pg`) and create the database (`docker exec spendly-pg psql -U postgres -d postgres -c "CREATE DATABASE spendly_test"`); it does not fail 172 times
  - The autouse `isolated_db` fixture runs `DROP TABLE IF EXISTS expenses, users CASCADE` before each test, so each test starts from an empty database with no tables, exactly as each test today starts from an empty file. Identity counters restart because the tables are recreated
  - The `client` fixture is unchanged in meaning: `init_db()`, `TESTING = True`, a test client
  - Tests are not run in parallel (one shared database)
- Do not delete or modify `spendly.db`

## Error handling

| Action | Required result |
| --- | --- |
| Import `app` in any environment (production, development or `SPENDLY_ENV` unset) with `DATABASE_URL` unset or empty (and, in production, `SPENDLY_SECRET_KEY` set) | Process exits non-zero; stderr has `RuntimeError` and `DATABASE_URL must be set, e.g. DATABASE_URL=postgresql://USER:PASSWORD@HOST:5432/spendly`; no connection is attempted; no real password appears |
| Import `app` with `SPENDLY_ENV=production` and no `SPENDLY_SECRET_KEY` | Unchanged: `RuntimeError` naming `SPENDLY_SECRET_KEY`, raised before any database work |
| `pytest` with `SPENDLY_TEST_DATABASE_URL` unset or empty | Run stops before `app` is imported and before any test; output has `SPENDLY_TEST_DATABASE_URL must be set, e.g. SPENDLY_TEST_DATABASE_URL=postgresql://USER:PASSWORD@HOST:5432/spendly_test`; no real password appears |
| Import `app` when the PostgreSQL server is down or the database does not exist | `psycopg.OperationalError` at import; the app does not start; the URL's password is not printed by our code |
| `POST /register` with an email that already exists (any case, any surrounding spaces) | HTTP 400, "An account with this email already exists." (unchanged) |
| `create_user()` with an email that is not lowercase | `psycopg.errors.CheckViolation` propagates (unreachable through `/register`, which lowercases) |
| `create_user()` with an existing email | `psycopg.errors.UniqueViolation` propagates |
| Insert an expense for a user id that does not exist | `psycopg.errors.ForeignKeyViolation` |
| Insert an expense with amount `0`, `-5`, or `0.004` | `psycopg.errors.CheckViolation` |
| Insert an expense with amount `≥ 10,000,000,000` | `psycopg.errors.NumericValueOutOfRange` (a `psycopg.DataError`) |
| Insert an expense with category `Groceries` | `psycopg.errors.CheckViolation` |
| Insert a user with name `""`, `"   "`, `"\t\n"` | `psycopg.errors.CheckViolation` |
| Insert an expense dated `2026-02-30`, `2026-04-31`, `2026-13-01` | a `psycopg.DataError` subclass (e.g. `DatetimeFieldOverflow`) |
| Set `created_at` to `"garbage"` or `""` | `psycopg.errors.InvalidDatetimeFormat` (a `psycopg.DataError`) |
| `seed_db()` with a bad demo row (amount 0) | `psycopg.errors.CheckViolation`; nothing from that call is stored (0 users, 0 expenses) |
| `pytest` with a test URL whose database is not `spendly_test` | Run stops before any test; nothing dropped |
| `pytest` with `spendly_test` missing or server down | Run stops once with a message naming `docker start spendly-pg` and `docker exec spendly-pg psql -U postgres -d postgres -c "CREATE DATABASE spendly_test"` |
| Any other database error in a route | Not caught; HTTP 500 (unchanged) |

## Edge cases

- **Non-ASCII email case** (`É@x.com` then `é@x.com` or `É@X.COM`): still a duplicate, because `/register` and `/login` lowercase in Python before the database sees the value, and the unique index compares the lowercased strings. Unchanged from today.
- **Python vs PostgreSQL `lower()`**: the CHECK uses the database's `lower()`. The value written is always Python-lowercased, and the CHECK only needs `lower()` to leave an already-lowercase string unchanged. If a rare character ever made them disagree, `/register` returns 500 rather than a wrong "already exists" message (only `UniqueViolation` is caught).
- **Whitespace in email**: stripped in Python, unchanged.
- **Duplicate registration / double submit**: second insert raises `UniqueViolation` → 400 "already exists", still exactly one row.
- **Zero expenses**: `total` and `month_total` are `Decimal("0")`, `count` is `0`; the page shows `₹0.00` and `0 expenses`; `category_share` is never asked to divide by zero.
- **Float sums**: `0.1` and `0.2` are stored as `0.10` and `0.20`; their sum is exactly `Decimal("0.30")`, so the old float error cannot happen any more, and the page still shows `₹0.30`.
- **Amounts with more than two decimals**: rounded by PostgreSQL to two; a value that rounds to `0.00` is rejected by `amount > 0`.
- **Month boundaries**: `date >= month_start AND date < next_month_start` on `DATE` values; first and last day of the month counted, first day of next month not.
- **`created_at` near midnight UTC**: `2026-04-01 04:00 +05:30` is `2026-03-31 22:30 UTC` → "March 2026", whatever the connection's `TimeZone` setting.
- **Loose date strings**: PostgreSQL's `DATE` input accepts some forms SQLite's CHECK rejected (`2026-1-5`, `2026-02-28 10:00`, and possibly `20-10-2026` depending on `DateStyle`). Nothing can insert expenses through the app until Step 7; Step 7 must validate the date format in Python before inserting. This step does not add a text CHECK on a `DATE` column.
- **Session `user_id` that is a very large int**: `get_user_by_id` returns `None` (no row), the hook clears the session; no exception.
- **Signed-out access to `/profile`**, wrong-type `user_id`, garbage cookie, logout, repeated logout: unchanged.
- **Running `init_db()` / `seed_db()` repeatedly**: no-op after the first run (still one demo user, eight expenses).
- **Demo user created earlier by another connection**: `seed_db()` adds no expenses (still `(1, 0)`).

## Existing tests that encode SQLite behaviour

These are every test (and helper) in the current 172 that depends on SQLite's API, types or catalog. Each keeps its intent; the "new AC" column says what it asserts after this step. All other tests pass unchanged.

**Helpers (no test of their own; the tests using them are otherwise unchanged)**

| Helper | SQLite dependency | Change |
| --- | --- | --- |
| `tests/test_database.py::_insert_user` | `?` placeholders, `cur.lastrowid` | `%s`, `RETURNING id` |
| `tests/test_profile.py::_add_expense` | `?`, `cur.lastrowid`, `with conn:` | `%s`, `RETURNING id`, no `with conn:` needed (autocommit) |
| `tests/test_profile.py::_set_created_at` | `?`; stores any text | `%s`; value must be a valid timestamp |
| `tests/test_database.py` raw queries using `?` (`test_delete_user_cascades_to_expenses`, `test_demo_password_is_hashed_and_verifiable`, `test_seed_db_noop_when_demo_user_exists_from_other_connection`) | `?` placeholders | `%s`; assertions unchanged |

**Tests**

| Existing test | What is SQLite-specific | New AC |
| --- | --- | --- |
| `test_database.py::test_database_isolation_env_var_set_and_real_db_untouched` | `SPENDLY_DB` set; `spendly.db` mtime unchanged | AC-1 |
| `test_database.py::test_resolve_db_path_falls_back_to_project_root` | `_resolve_db_path()` default file | Replaced by AC-2, AC-3, AC-4 (`resolve_database_url`) |
| `test_database.py::test_get_db_returns_row_with_foreign_keys_on` | `PRAGMA foreign_keys`, `sqlite3.Row` | AC-5 |
| `test_database.py::test_init_db_creates_tables_and_index` | `sqlite_master` | AC-6 |
| `test_database.py::test_expense_with_missing_user_id_raises` | `sqlite3.IntegrityError` | AC-7 |
| `test_database.py::test_expense_amount_and_category_constraints` | `sqlite3.IntegrityError`; relied on autocommit after a failure | AC-8 |
| `test_database.py::test_blank_name_variants_raise` (3 cases) | `sqlite3.IntegrityError` | AC-9 |
| `test_database.py::test_date_constraint_rejects_invalid_accepts_valid` | text CHECK with `date()`; rejects loose formats | AC-10 (loose formats dropped; see Edge cases) |
| `test_database.py::test_seed_db_dates_and_categories` | dates come back as `str` | AC-11 |
| `test_database.py::test_duplicate_email_case_insensitive_raises` | `COLLATE NOCASE` + `sqlite3.IntegrityError` | AC-12 |
| `test_database.py::test_seed_db_rolls_back_on_bad_row` | `sqlite3.IntegrityError`, `BEGIN IMMEDIATE` rollback | AC-13 |
| `test_database.py::test_startup_skips_seed_in_production` | `SPENDLY_DB=prod.db`, `sqlite_master` | AC-14 |
| `test_registration.py::test_ac15_integrity_error` | monkeypatched `sqlite3.IntegrityError` | AC-15 |
| `test_login_logout.py::test_ac23_production_import_without_key_fails_before_db_work` | "no db file or directory created" via `SPENDLY_DB` | AC-16 |
| `test_profile.py::test_summary_month_bounds_ac8` | float sums (`pytest.approx`) | AC-17 |
| `test_profile.py::test_recent_expenses_limit_and_order_ac11` | dates compared as `str` | AC-18 |
| `test_profile.py::test_profile_never_sends_hash_ac18` | `fetchone()[0]` on `sqlite3.Row` | AC-19 |
| `test_profile.py::test_profile_member_since_ac24` | `created_at` stored as naive UTC text | AC-20 |
| `test_profile.py::test_profile_bad_created_at_ac25` (`"garbage"`, `""`) | text column accepts garbage via `UPDATE` | AC-21 |

Count: 19 test functions (22 collected test cases, counting parametrised cases) change; the other 150 collected cases pass unchanged. After this step the suite collects at least 172 + the new cases below (AC-22 to AC-35); the replaced `test_resolve_db_path_falls_back_to_project_root` becomes three tests.

## Acceptance criteria and tests

Tests use the `spendly_test` PostgreSQL database through the conftest-forced `DATABASE_URL`; each test starts with no tables (autouse `isolated_db`), and tests never touch the developer's `spendly` database or the `spendly.db` file. Database errors are asserted with the exact psycopg class named.

**Rewritten from SQLite tests**

- **AC-1** Given the test session, when `os.environ["DATABASE_URL"]` is parsed with `conninfo_to_dict`, then its `dbname` is `spendly_test`; and `spendly.db` in the project root has the same existence and mtime as before the test module was imported. (`test_database.py`)
- **AC-2** Given `resolve_database_url({"DATABASE_URL": "postgresql://u@h/db"})`, when called, then it returns that string unchanged. (`test_database.py`)
- **AC-3** Given `resolve_database_url` with `SPENDLY_ENV=production` and `DATABASE_URL` missing, and again with it set to `""`, when called, then `RuntimeError` is raised and its message contains `DATABASE_URL`. (`test_database.py`, parametrised)
- **AC-4** Given `resolve_database_url({})`, `resolve_database_url({"SPENDLY_ENV": "development"})` and `resolve_database_url({"SPENDLY_ENV": "development", "DATABASE_URL": ""})`, when called, then each raises `RuntimeError` (there is no development default). (`test_database.py`, parametrised)
- **AC-5** Given `get_db()`, when a `TEMP` table is created, a row inserted with `%s` and selected, then the row is a `dict` with `row["col"] == "value"`, `conn.autocommit` is `True`, and a `SELECT` after a failed statement on the same connection succeeds. (`test_database.py`)
- **AC-6** Given `init_db()` called twice, when `to_regclass` is queried for `users`, `expenses`, `idx_expenses_user_date` and `idx_users_email`, then all four exist and `idx_users_email` is unique (`pg_index.indisunique`). (`test_database.py`)
- **AC-7** Given an expense insert with `user_id` 999 that does not exist, when it runs, then `psycopg.errors.ForeignKeyViolation` is raised. (`test_database.py`)
- **AC-8** Given one connection and a user, when expenses with amount `0`, amount `-5` and category `Groceries` are inserted in turn, then each raises `psycopg.errors.CheckViolation`. (`test_database.py`)
- **AC-9** Given a user insert with name `""`, `"   "` or `"\t\n"`, when it runs, then `psycopg.errors.CheckViolation` is raised. (`test_database.py`, parametrised, 3 cases)
- **AC-10** Given expense dates `2026-02-30`, `2026-04-31` and `2026-13-01`, when each is inserted, then each raises a `psycopg.DataError`; and `2026-02-28` and `2028-02-29` insert, giving exactly 2 rows. (`test_database.py`)
- **AC-11** Given `seed_db(date(2026, 10, 20))`, when the expense dates are read back, then they are the set of `datetime.date` values for 2026-10-01, 03, 05, 08, 12, 15, 18, 22, and the categories are the seven allowed values. (`test_database.py`)
- **AC-12** Given the seeded demo user, when a raw insert uses `DEMO@SPENDLY.COM`, then `psycopg.errors.CheckViolation` is raised; and when a raw insert uses `demo@spendly.com`, then `psycopg.errors.UniqueViolation` is raised. (`test_database.py`)
- **AC-13** Given `_demo_expenses` monkeypatched so the fifth row has amount `0`, when `seed_db()` runs, then `psycopg.errors.CheckViolation` is raised and the database holds 0 users and 0 expenses. (`test_database.py`)
- **AC-14** Given `SPENDLY_ENV=production` and the test `DATABASE_URL`, when `app.startup()` runs, then `users` and `expenses` exist (catalog query) and there is no `demo@spendly.com` row. (`test_database.py`)
- **AC-15** Given `create_user` monkeypatched to raise `psycopg.errors.UniqueViolation`, when `POST /register` is sent with valid data, then the status is 400 and the page shows "An account with this email already exists." (`test_registration.py`)
- **AC-16** Given a subprocess `import app` with `SPENDLY_ENV=production`, no `SPENDLY_SECRET_KEY` and `DATABASE_URL=postgresql://spendly@db.invalid/nowhere`, when it runs, then it exits non-zero, stderr contains `RuntimeError` and `SPENDLY_SECRET_KEY`, and stderr does not contain `psycopg` or `OperationalError` (no connection was attempted). (`test_login_logout.py`)
- **AC-17** Given expenses of 10 on 2026-10-01, 2026-10-31, 2026-11-01 and 2026-09-30, when `get_expense_summary(uid, "2026-10-01", "2026-11-01")` is called, then `month_total == Decimal("20.00")`, `total == Decimal("40.00")` and `count == 4` (exact, no `approx`). (`test_profile.py`)
- **AC-18** Given seven expenses dated 2026-10-01 to 2026-10-07, when `get_recent_expenses(uid)` is called, then the five `date` values are `date(2026, 10, 7)` down to `date(2026, 10, 3)`. (`test_profile.py`)
- **AC-19** Given a signed-in user, when the stored hash is read with `fetchone()["password_hash"]` and `/profile` is requested, then neither the hash nor the text `password_hash` is in the body. (`test_profile.py`)
- **AC-20** Given `created_at` set to `2026-03-05 10:20:30+00`, when the signed-in user requests `/profile`, then the page contains `Member since March 2026`. (`test_profile.py`)
- **AC-21** Given `get_user_profile` monkeypatched to return a row whose `created_at` is `"garbage"` or `""`, when `/profile` is requested, then the status is 200, the name and email are shown, "Member since" is absent and no exception is raised. (`test_profile.py`, parametrised, replaces the `UPDATE`-based cases)

**New**

- **AC-22** Given a user, when `created_at` is set to `"garbage"` by a raw `UPDATE`, then `psycopg.errors.InvalidDatetimeFormat` is raised. (`test_database.py`)
- **AC-23** Given an expense inserted with amount `0.004`, then `psycopg.errors.CheckViolation` is raised; given `12.345`, then it is stored and read back as `Decimal("12.35")`; given `10000000000`, then `psycopg.errors.NumericValueOutOfRange` is raised. (`test_database.py`)
- **AC-24** Given a user with expenses `100.00`, `250.50`, `49.50` (one in this month), when `get_expense_summary`, `get_category_totals` and `get_recent_expenses` are called, then `total`, `month_total`, each category `total` and each `amount` are `Decimal` instances, `count` values are `int`, each `date` is a `datetime.date`, and `get_user_profile(uid)["created_at"]` is a timezone-aware `datetime`. (`test_profile.py`)
- **AC-25** Given a user with no expenses, when `get_expense_summary` is called, then `total` and `month_total` are `Decimal` equal to 0 and `count` is the `int` 0. (`test_profile.py`)
- **AC-26** Given `format_amount`, when called with `Decimal("12345678.90")`, `Decimal("0")`, `Decimal("0.30")` and `Decimal("400.00")`, then it returns `₹12,345,678.90`, `₹0.00`, `₹0.30`, `₹400.00`. (`test_profile.py`)
- **AC-27** Given `category_share`, when called with `(Decimal("400.00"), Decimal("600.00"))`, `(Decimal("12.50"), Decimal("100.00"))`, `(Decimal("0"), Decimal("0"))`, `(Decimal("1.00"), Decimal("3.00"))` and the mixed `(Decimal("5.00"), 10)`, then it returns the `int`s 67, 13, 0, 33, 50 with no `TypeError`. (`test_profile.py`)
- **AC-28** Given `member_since`, when called with `datetime(2026, 3, 5, 10, 20, 30, tzinfo=timezone.utc)`, with the naive `datetime(2026, 3, 5, 10, 20, 30)`, and with `datetime(2026, 4, 1, 4, 0, tzinfo=timezone(timedelta(hours=5, minutes=30)))`, then each returns `"March 2026"`. (`test_profile.py`)
- **AC-29** Given `member_since` called with `date(2026, 3, 5)` or `12345`, then it returns `None` without raising. (`test_profile.py`, parametrised)
- **AC-30** Given a subprocess `import app` with `SPENDLY_ENV=production`, `SPENDLY_SECRET_KEY` set and `DATABASE_URL` removed from the environment, when it runs, then it exits non-zero and stderr contains `RuntimeError` and `DATABASE_URL must be set, e.g. DATABASE_URL=postgresql://USER:PASSWORD@HOST:5432/spendly`, and not `OperationalError`. (`test_login_logout.py`)
- **AC-31** Given a user registered through `POST /register`, when `get_user_by_email` returns their row, then `session["user_id"]` after `POST /login` is that row's `id` and `isinstance(..., int)` holds; and `GET /profile` then returns 200. (`test_login_logout.py`)
- **AC-32** Given two calls to `seed_db(date(2026, 10, 20))` after `init_db()`, then there is exactly one demo user and eight expenses, and the sum of their amounts is `Decimal("6498.00")`. (`test_database.py`)
- **AC-33** Missing-variable message. Given `resolve_database_url({"SPENDLY_TEST_DATABASE_URL": "postgresql://u:s3cret@h/spendly_test"})`, when called, then the `RuntimeError` message is exactly `DATABASE_URL must be set, e.g. DATABASE_URL=postgresql://USER:PASSWORD@HOST:5432/spendly` and does not contain `s3cret`. (`test_database.py`)
- **AC-35** Missing test-URL message. Given a subprocess running `[sys.executable, "-m", "pytest", "-q", "tests"]` with `cwd` set to the project root (the directory holding `app.py`, i.e. `Path(__file__).resolve().parent.parent`), `SPENDLY_TEST_DATABASE_URL` removed from its environment and `DATABASE_URL=postgresql://u:s3cret@h/spendly`, when it runs, then it exits non-zero with no test executed, its combined stdout and stderr contain `SPENDLY_TEST_DATABASE_URL must be set, e.g. SPENDLY_TEST_DATABASE_URL=postgresql://USER:PASSWORD@HOST:5432/spendly_test`, and that output does not contain `s3cret`. (`test_database.py`)
- **AC-34** Given a session cookie validly signed with the app's secret key whose `user_id` is `10**30`, when `GET /profile` is requested, then the status is 302 with `Location` ending in `/login`, and no 500 or exception occurs. (`test_profile.py`)

## Open questions

- Dev default when `DATABASE_URL` is unset outside production? Decided: none. `DATABASE_URL` is required in every environment and `SPENDLY_TEST_DATABASE_URL` is required for tests. The developer's PostgreSQL runs in Docker with a password, so a password-less local-socket default would not work anyway; a missing variable fails with a message that shows only the URL shape, never a real password.
- Should conftest create `spendly_test` automatically if it is missing? Recommended default: no — stop with a message to run `docker exec spendly-pg psql -U postgres -d postgres -c "CREATE DATABASE spendly_test"`; creating databases needs extra privileges and hides setup mistakes.
- Migrate existing rows from `spendly.db`? Recommended default: no — it holds only seed data and throwaway dev accounts, and `seed_db()` recreates the demo user. Leave the file on disk for the developer to delete.
- Should `member_since` keep accepting the `"YYYY-MM-DD HH:MM:SS"` string? Recommended default: yes — it keeps the pure-helper tests (`test_member_since_valid`, `test_member_since_invalid_returns_none`) unchanged and costs one branch; it can be dropped later.
- Catch only `UniqueViolation` in `/register`, or any `psycopg.IntegrityError` as today's code catches any `sqlite3.IntegrityError`? Recommended default: `UniqueViolation` only, so a lowercase-CHECK failure surfaces as a 500 instead of a misleading "already exists".
- `BIGINT` identity ids or `INTEGER`? Recommended default: `BIGINT GENERATED ALWAYS AS IDENTITY` (standard choice; Python sees an `int` either way).

## Note for the deploy step

Not part of this step. `get_db()` opens a new connection per call with no pool, which is fine for local development but not for a hosted database with a connection limit: the deploy step should add connection pooling (`psycopg_pool`, or the provider's pooler such as PgBouncer). The production `DATABASE_URL` must also include `sslmode=require` (e.g. `postgresql://USER:PASSWORD@HOST:5432/spendly?sslmode=require`) so the connection is encrypted.

## Definition of done

- [ ] `docker exec spendly-pg psql -U postgres -d postgres -c "CREATE DATABASE spendly"` and `docker exec spendly-pg psql -U postgres -d postgres -c "CREATE DATABASE spendly_test"` were run once, and `.venv/bin/pip install -r requirements.txt` installs psycopg
- [ ] All acceptance criteria (AC-1 to AC-35) and every other existing test pass with `SPENDLY_TEST_DATABASE_URL=postgresql://postgres:PASSWORD@localhost:5432/spendly_test .venv/bin/pytest -q`; the collected count is at least 172 plus the new cases
- [ ] `grep -rn "sqlite" app.py database/ tests/` prints nothing
- [ ] `grep -rn "SPENDLY_DB" app.py database/ tests/ CLAUDE.md .claude/commands/` prints nothing
- [ ] `grep -nE "(SELECT|INSERT|UPDATE|DELETE)" app.py` finds no SQL, and `grep -n "connect(" app.py` finds nothing
- [ ] `shasum spendly.db` before and after `pytest -q` is identical, and before and after running the app by hand
- [ ] Running `pytest -q` with `SPENDLY_TEST_DATABASE_URL=postgresql://postgres:PASSWORD@localhost:5432/spendly` stops before any test and the `spendly` database still has its tables and demo user (`docker exec spendly-pg psql -U postgres -d spendly -c "select count(*) from users"`)
- [ ] `SPENDLY_ENV=production SPENDLY_SECRET_KEY=x .venv/bin/python3 -c "import app"` with `DATABASE_URL` unset exits with `RuntimeError: DATABASE_URL must be set, e.g. DATABASE_URL=postgresql://USER:PASSWORD@HOST:5432/spendly`
- [ ] `docker exec spendly-pg psql -U postgres -d spendly -c "\d users"` shows `created_at timestamp with time zone`, the `users_email_lowercase` CHECK and the unique index `idx_users_email`; `docker exec spendly-pg psql -U postgres -d spendly -c "\d expenses"` shows `amount numeric(12,2)` and `date date`
- [ ] The app was run by hand (`DATABASE_URL=postgresql://postgres:PASSWORD@localhost:5432/spendly SPENDLY_SECRET_KEY=dev-only-value .venv/bin/python3 app.py`) against `spendly` and verified in the browser:
  - [ ] Signing in as `demo@spendly.com` / `demo123` lands on the profile page with "Member since <current month and year>", total `₹6,498.00`, eight expenses, the category breakdown with percentages, and five recent expenses with `YYYY-MM-DD` dates, newest first
  - [ ] Registering a new user with an upper-case email succeeds, signing in with a different letter case works, and registering the same email again shows "An account with this email already exists."
  - [ ] A freshly registered user sees the empty state (`₹0.00`, `0 expenses`, "No expenses yet.")
  - [ ] Signing out returns to the landing page; `/profile` then redirects to `/login`
  - [ ] Restarting the app does not create a second demo user (`docker exec spendly-pg psql -U postgres -d spendly -c "select count(*) from users where email='demo@spendly.com'"` prints 1)
- [ ] `CLAUDE.md` describes PostgreSQL, `DATABASE_URL`, `SPENDLY_TEST_DATABASE_URL` and the Docker `CREATE DATABASE` setup, uses only placeholder passwords in its examples, and no longer mentions `SPENDLY_DB` or `sqlite3`
