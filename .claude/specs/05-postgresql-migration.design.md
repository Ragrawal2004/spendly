# Design: Step 5 — PostgreSQL Migration

Companion to `05-postgresql-migration.md`. Design only; no code. All open questions take the spec's recommended defaults: no dev default URL, conftest does not create `spendly_test`, `spendly.db` is not migrated, `member_since` keeps the string branch, `/register` catches `UniqueViolation` only, ids are `BIGINT GENERATED ALWAYS AS IDENTITY`.

## 1. `database/db.py`

**Imports:** drop `sqlite3`; add `psycopg` and `from psycopg.rows import dict_row`. Keep `os`, `closing`, `date/datetime/timezone`, `generate_password_hash`.

**Schema:** `_SCHEMA` becomes a tuple of four statement strings (not one script). psycopg has no `executescript`; a multi-statement string only works with no parameters and hides which statement failed. Statements, in order:
1. `CREATE TABLE IF NOT EXISTS users (id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY, name TEXT NOT NULL CHECK (btrim(name, E' \t\n\r') <> ''), email TEXT NOT NULL CONSTRAINT users_email_lowercase CHECK (email = lower(email)), password_hash TEXT NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now())`
2. `CREATE TABLE IF NOT EXISTS expenses (id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY, user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE, amount NUMERIC(12,2) NOT NULL CHECK (amount > 0), category TEXT NOT NULL CHECK (category IN ('Food','Transport','Bills','Health','Entertainment','Shopping','Other')), date DATE NOT NULL, description TEXT, created_at TIMESTAMPTZ NOT NULL DEFAULT now())`
3. `CREATE UNIQUE INDEX IF NOT EXISTS idx_users_email ON users (email)`
4. `CREATE INDEX IF NOT EXISTS idx_expenses_user_date ON expenses (user_id, date)`

The `E' \t\n\r'` literal must reach PostgreSQL as written, so the Python string holding it is a raw string (or the backslashes are doubled); otherwise Python turns `\t` into a real tab inside SQL, which still works but no longer matches the spec text.

**`resolve_database_url(env) -> str`** (pure, shaped like `resolve_secret_key`): `url = env.get("DATABASE_URL")`; return it if truthy, else `raise RuntimeError(_MISSING_URL_MESSAGE)` where the module constant is exactly `"DATABASE_URL must be set, e.g. DATABASE_URL=postgresql://USER:PASSWORD@HOST:5432/spendly"`. It ignores `SPENDLY_ENV` entirely (no default in any environment) and never formats any env value into the message (AC-33).

**`get_db() -> psycopg.Connection`:** `return psycopg.connect(resolve_database_url(os.environ), row_factory=dict_row, autocommit=True)`. `_resolve_db_path()` is deleted. The URL is resolved on every call (cheap), so `startup()` → `init_db()` → `get_db()` raises the `RuntimeError` at import before any connection attempt.

**`init_db()`:** `with closing(get_db()) as conn, conn.transaction():` then execute each `_SCHEMA` statement. Running it twice is a no-op (`IF NOT EXISTS`).

**`create_user(name, email, password_hash) -> int`:** `INSERT INTO users (name, email, password_hash) VALUES (%s, %s, %s) RETURNING id`, return `fetchone()["id"]`. No `with conn:`; autocommit commits the single statement. `UniqueViolation` / `CheckViolation` propagate untouched.

**Read functions:** bodies unchanged except `?` → `%s`; return hints `sqlite3.Row | None` → `dict | None`, `list[sqlite3.Row]` → `list[dict]`, `get_expense_summary` → `dict`. Only one SQL change: `get_expense_summary` uses `CASE WHEN date >= %s::date AND date < %s::date THEN amount END`. No rounding, no `ORDER BY` change (`total` and `count` are legal output-column aliases in PostgreSQL; `date` is a non-reserved keyword, legal as a column name).

**`seed_db(today=None)`:** keep the signature, `_DEMO_EXPENSES_TABLE`, `_demo_expenses()` (still returns ISO strings and floats; `test_demo_expenses_shape` is unchanged) and `round(amount, 2)`. New body:
```
with closing(get_db()) as conn, conn.transaction():
    row = conn.execute("INSERT INTO users (name, email, password_hash) VALUES (%s, %s, %s) "
                       "ON CONFLICT (email) DO NOTHING RETURNING id", (...)).fetchone()
    if row is None:
        return                       # demo user already exists; transaction commits nothing
    for ... in _demo_expenses(today):
        conn.execute("INSERT INTO expenses (...) VALUES (%s, %s, %s, %s, %s)", (...))
```
`generate_password_hash("demo123")` is computed before the `INSERT` regardless (it is cheap enough, and computing it first keeps hashing out of the open transaction). Any exception inside the block rolls the transaction back and re-raises (AC-13). `ON CONFLICT (email)` infers the unique index `idx_users_email`; it does not suppress the CHECK.

**Type adaptation notes (verify during build):** ISO date strings and timestamp strings are passed as Python `str`; psycopg dumps `str` with the "unknown" OID so PostgreSQL casts them to the target column type (`DATE`, `TIMESTAMPTZ`). Floats are dumped as `float8` and assignment-cast to `NUMERIC(12,2)`. Python ints above the `bigint` range (AC-34) are dumped as `numeric`, and `id = numeric` compares without error and finds no row.

## 2. `app.py`

**Imports:** drop `import sqlite3`; add `import psycopg`; add `from decimal import Decimal, ROUND_HALF_UP`. `math` is no longer used once `category_share` changes — remove it. No SQL and no `connect(` anywhere (DoD greps).

**`register()`:** `except psycopg.errors.UniqueViolation:` replaces `except sqlite3.IntegrityError:`. Nothing else changes. A `CheckViolation` (lowercase CHECK) is no longer caught and gives 500 — this is a deliberate behaviour narrowing versus today's "any IntegrityError → already exists".

**`member_since(created_at)`:**
- `isinstance(created_at, datetime)`: if `tzinfo` is `None`, treat as UTC (`replace(tzinfo=timezone.utc)`), else `astimezone(timezone.utc)`; return `strftime("%B %Y")`.
- `isinstance(created_at, str)`: today's `strptime(..., "%Y-%m-%d %H:%M:%S")` path, catching `ValueError` → `None`.
- anything else → `None`. Because `datetime` is checked first and `date` is not a `datetime`, `date(2026, 3, 5)` and `12345` fall through to `None` (AC-29). No exception escapes.

**`format_amount(value)`:** **no code change needed.** `f"{Decimal('12345678.90'):,.2f}"` already gives `12,345,678.90`; `Decimal` supports the `,` and `.2f` format spec. AC-26 is a new test against the existing function. (Decimal formatting rounds half-even, float formatting is binary; values from the database already have exactly two decimals, so the difference cannot show.)

**`category_share(total, overall)`:** must change — `Decimal / Decimal * 100 + 0.5` raises `TypeError` (Decimal + float), and `Decimal / float` also raises. New body: return `0` if `not overall`; convert both with `_to_decimal(x)` = `x if isinstance(x, Decimal) else Decimal(str(x))` (`str()` so `12.5` becomes `Decimal("12.5")`, not a binary expansion); return `int((t * 100 / o).quantize(Decimal("1"), rounding=ROUND_HALF_UP))`. Checks: (400,600)→67, (12.5,100)→13, (0,0)→0, (1,3)→33, (Decimal 5, int 10)→50. `_to_decimal` is a private helper next to it.

**`profile()`, `load_current_user`, `authenticate`, `login`:** unchanged. They only use `row["key"]`, `g.current_user` truthiness and `user["id"]` (an `int` from `BIGINT`), all of which hold for `dict` rows.

## 3. `requirements.txt`

Add one line, `psycopg[binary]==3.X.Y`, where `3.X.Y` is the newest 3.x release whose `psycopg-binary` ships a `cp314` macOS arm64 wheel (the venv runs Python 3.14.2). Confirm at build time with `.venv/bin/pip download "psycopg-binary==3.X.Y" --only-binary :all: --no-deps -d <scratch>` before pinning. The `[binary]` extra pins `psycopg-binary` to the same version. `requirements-dev.txt` is unchanged.

## 4. `tests/conftest.py`

Rewritten. Two phases, so that every early stop happens before collection imports `app` (test modules import `app` at module top, i.e. during collection):

**Module level (runs at conftest import, no connection):**
- `_TEST_URL = os.environ.get("SPENDLY_TEST_DATABASE_URL", "")`.
- `os.environ["DATABASE_URL"] = _TEST_URL` — **assigned**, not `setdefault`, so a developer's own `DATABASE_URL` can never reach the app under test, even when the test URL is missing.
- `os.environ.setdefault("SPENDLY_SECRET_KEY", "test-only-secret-key")` (unchanged).
- The `tempfile` / `SPENDLY_DB` lines are deleted.

**`pytest_sessionstart(session)` hook** (runs after conftest import, before collection, and pytest handles `pytest.exit` there cleanly; raising `pytest.exit` at conftest import time would instead be wrapped as "ImportError while loading conftest"):
1. `_TEST_URL` empty → `pytest.exit("SPENDLY_TEST_DATABASE_URL must be set, e.g. SPENDLY_TEST_DATABASE_URL=postgresql://USER:PASSWORD@HOST:5432/spendly_test")`.
2. `conninfo_to_dict(_TEST_URL).get("dbname") != "spendly_test"` → `pytest.exit` with a fixed message ("SPENDLY_TEST_DATABASE_URL must point at a database named spendly_test; refusing to run"). A malformed URL (`psycopg.ProgrammingError` from the parser) gets the same fixed message. No connection has been made, nothing is dropped.
3. Probe: `psycopg.connect(_TEST_URL, connect_timeout=5).close()`; on `psycopg.OperationalError` → `pytest.exit` with a fixed message naming `docker start spendly-pg` and `docker exec spendly-pg psql -U postgres -d postgres -c "CREATE DATABASE spendly_test"`. The exception text is not included (no URL fragments in output). The run stops once, not 172 times.

All three messages are fixed strings; none interpolates an environment value (AC-35).

**`isolated_db` (autouse):** `with closing(db.get_db()) as conn: conn.execute("SET lock_timeout = '5s'"); conn.execute("DROP TABLE IF EXISTS expenses, users CASCADE")`, then `yield`. Import `database.db` lazily inside the fixture (it imports nothing from `app`, so importing it is safe either way). The `lock_timeout` makes a leaked open transaction fail the next test fast instead of hanging the run. Nothing yields a path any more; no current test uses the yielded value (checked).

**`client`:** unchanged in body (`init_db()`, `TESTING = True`, `test_client()`), still depends on `isolated_db`.

Note: the first `import app` (during collection) runs `startup()` → `init_db()` + `seed_db()` against `spendly_test`; the first test's `isolated_db` drops those tables, so every test still starts from no tables. Tests are not run in parallel (no `pytest-xdist`; nothing to change).

## 5. Test migrations

### 5a. Dict-row audit (what breaks because a row is a `dict`, not `sqlite3.Row`)

| Location | Usage | Breaks? |
| --- | --- | --- |
| `tests/test_profile.py:330` (`test_profile_never_sends_hash_ac18`) | `.fetchone()[0]` on a DB row | **Yes** — `KeyError: 0`. Becomes `["password_hash"]` (AC-19). Already in the spec. |
| `tests/test_profile.py:129`, `tests/test_login_logout.py:52` | `row.keys()` | No — `dict.keys()` works. |
| `tests/test_registration.py:45,50,56,141,156,162` | `rows()[0]["name"]` | No — `[0]` indexes the `fetchall()` list, then a key. |
| `tests/test_login_logout.py:473,525` | `dict(sess)` | No — that is the Flask session, not a DB row. |
| `tests/test_database.py:190-217`, `tests/test_profile.py:496` | `row[0]`, `row[2]` | No — tuples from `_demo_expenses()` / `_DEMO_EXPENSES_TABLE`, not DB rows. |
| `app.py` | only `row["key"]`, `user["id"]`, truthiness of `g.current_user` | No. |
| `templates/profile.html`, `templates/base.html` | only `x["key"]`, `summary["count"] == 1`, `{{ e["date"] }}` | No. No `[0]`, `dict()`, `.keys()`, `.items()` in any template. `str(date)` prints `YYYY-MM-DD` as today. |

Value-type comparisons that still pass without edits: `test_category_totals_order_ac10` (`Decimal("400.00") == 400`), `test_summary_empty_user` (`(Decimal("0"), 0, Decimal("0")) == (0, 0, 0)`), `test_queries_do_not_leak_other_users` (`fetchall()` returns `[]`), `test_get_user_profile_hit_and_miss` (aware `datetime` is truthy), `test_profile_demo_user_ac19` (`format_amount(6498.0)` and the Decimal sum both render `₹6,498.00`).

### 5b. Changes per file

**`tests/test_database.py`** — drop `import sqlite3`; add `import psycopg`, `from decimal import Decimal`, `from psycopg.conninfo import conninfo_to_dict`.
- `_insert_user`: `%s`, `RETURNING id`, `fetchone()["id"]`.
- Replace `test_database_isolation_env_var_set_and_real_db_untouched` with AC-1 (dbname is `spendly_test`; `spendly.db` existence and mtime unchanged — the module-level `_REAL_DB_*` capture stays).
- Delete `test_resolve_db_path_falls_back_to_project_root`; AC-2, AC-3 (parametrised ×2), AC-4 (parametrised ×3), AC-33 replace it.
- `test_get_db_returns_row_with_foreign_keys_on` → AC-5: `CREATE TEMP TABLE t (col TEXT)`, `%s` insert, `isinstance(row, dict)`, `conn.autocommit is True`, then a failing statement (e.g. `SELECT 1/0` in `pytest.raises(psycopg.errors.DivisionByZero)`) followed by a successful `SELECT 1`.
- AC-6 (`to_regclass` for four names + `pg_index.indisunique` for `idx_users_email`), AC-7 (`ForeignKeyViolation`), AC-8 (`CheckViolation` ×3 on one connection), AC-9 (`CheckViolation`, 3 cases), AC-10 (only the three impossible dates, each `pytest.raises(psycopg.DataError)`; the three loose formats are removed per the spec's edge case), AC-11 (sets of `date(...)`), AC-12 (`CheckViolation` for `DEMO@SPENDLY.COM`, then `UniqueViolation` for `demo@spendly.com`), AC-13 (`CheckViolation`, counts `(0, 0)`), AC-14 (catalog query via `to_regclass`, no `SPENDLY_DB`).
- `test_delete_user_cascades_to_expenses`, `test_demo_password_is_hashed_and_verifiable`, `test_seed_db_noop_when_demo_user_exists_from_other_connection`: `?` → `%s` only. In the last one also drop the inner `with conn:` (see conflict C3).
- New: AC-22, AC-23, AC-32, AC-35.

**`tests/test_profile.py`** — `_add_expense`: `%s`, `RETURNING id`, return `fetchone()["id"]` **inside** the `closing` block, no `with conn:`. `_set_created_at`: `%s`, no `with conn:`. AC-17 (exact `Decimal`), AC-18 (`date(...)` objects), AC-19 (`["password_hash"]`), AC-20 (`"2026-03-05 10:20:30+00"`), AC-21 (monkeypatch `app.get_user_profile`, modelled on the existing `test_profile_null_created_at_ac25`). New: AC-24, AC-25, AC-26, AC-27, AC-28, AC-29 (×2), AC-34 (set `sess["user_id"] = 10**30` via `client.session_transaction()`, which signs it with the app key).

**`tests/test_registration.py`** — `import sqlite3` → `import psycopg`; `test_ac15_integrity_error` raises `psycopg.errors.UniqueViolation("x")` (AC-15; psycopg error classes can be instantiated with a message).

**`tests/test_login_logout.py`** — rewrite `test_ac23_production_import_without_key_fails_before_db_work` as AC-16 (`DATABASE_URL=postgresql://spendly@db.invalid/nowhere`; assert `RuntimeError`, `SPENDLY_SECRET_KEY`, and no `psycopg` / `OperationalError` in stderr; no `SPENDLY_DB`, no `tmp_path`). New: AC-30 (copy `os.environ`, **pop `DATABASE_URL`** — the parent's conftest set it — set production + key) and AC-31.

Expected count: 172 − 1 (old resolve test) + 7 (AC-2 ×1, AC-3 ×2, AC-4 ×3, AC-33 ×1) + 14 (AC-22 to AC-28 one each, AC-29 ×2, AC-30, 31, 32, 34, 35) = **192 collected**. Rewritten tests keep their case counts (AC-10 drops loose formats inside one test function).

## 6. `CLAUDE.md` and other docs

**`CLAUDE.md`:**
- Commands: add the one-time setup (`docker start spendly-pg`; `docker exec spendly-pg psql -U postgres -d postgres -c "CREATE DATABASE spendly"`, same for `spendly_test`). Dev server: `DATABASE_URL=postgresql://postgres:PASSWORD@localhost:5432/spendly SPENDLY_SECRET_KEY=dev-only-value .venv/bin/python3 app.py`. Tests: `SPENDLY_TEST_DATABASE_URL=postgresql://postgres:PASSWORD@localhost:5432/spendly_test .venv/bin/pytest`. Placeholder password only.
- Environment variables: `DATABASE_URL` (required everywhere, never logged) and `SPENDLY_TEST_DATABASE_URL` (required for tests; conftest forces `DATABASE_URL` to it and refuses any dbname other than `spendly_test`) replace `SPENDLY_DB`.
- `/register` bullet: catches `psycopg.errors.UniqueViolation` only.
- `member_since` bullet: accepts aware/naive `datetime` (UTC month) and the legacy string.
- `database/db.py` bullet: "all PostgreSQL access", `resolve_database_url`, `get_db()` = autocommit + `dict_row`, `RETURNING id`, `seed_db` with `ON CONFLICT DO NOTHING` in `conn.transaction()`, return types (`Decimal`, `int`, `date`, aware `datetime`), the lowercase CHECK as the reason emails are lowercased in Python, and that multi-statement writes use `conn.transaction()` (not `with conn:`).
- Last line: "No ORM — raw `psycopg` access through `database/db.py`."
- Fix the stale `.gitignore` remark only if still accurate (it is; leave it).

**`.claude/commands/create-spec.md` (lines 140-142):** "Tests use the `spendly_test` PostgreSQL database (reset before every test) and never touch the developer's `spendly` database or `spendly.db`."

## 7. Spec conflicts and resolutions

- **C1 — `.claude/commands/seed-user.md` and `seed-expenses.md` are not in the spec's file list but break.** Both tell the agent to use `?` placeholders and `with closing(get_db()) as conn:` + `with conn:` "so everything rolls back if any insert fails". With psycopg, `?` is a syntax error, and with `autocommit=True` `with conn:` opens **no** transaction (each insert commits on its own) and closes the connection on exit — the rollback promise silently becomes false. Resolution: add both files to this step — `%s` placeholders and `with closing(get_db()) as conn, conn.transaction():`. (Recommended; small doc-only change. If the user prefers strict spec scope, note it as a known break for the next step instead.)
- **C2 — `with conn:` semantics change everywhere.** In sqlite3, `with conn:` is a transaction and leaves the connection open; in psycopg 3 it commits/rolls back and **closes** the connection. `tests/test_profile.py::_add_expense` reads `cur.lastrowid` *after* `with conn:` exits — with psycopg the `RETURNING` row must be fetched inside the block. Resolution: no `with conn:` anywhere in code or tests; transactions are always `conn.transaction()`.
- **C3 — `test_seed_db_noop_when_demo_user_exists_from_other_connection`** keeps an inner `with conn:` inside `closing(...)`. It would still pass (psycopg's `close()` is idempotent), but it reads as a transaction when it isn't one. The spec lists only `?` → `%s`; this design also drops the `with conn:` for clarity (intent and assertions unchanged).
- **C4 — `init_db()` uses `executescript`, which psycopg does not have.** Not mentioned in the spec. Resolution: `_SCHEMA` becomes a tuple of statements executed in one `conn.transaction()` (§1).
- **C5 — AC-34 fails on SQLite today.** `get_user_by_id(10**30)` raises `OverflowError` in `sqlite3` (500), so AC-34 is a real behaviour fix delivered by the migration, not a regression guard. It can only be added after the switch (build order T4).
- **C6 — `format_amount` needs no change**, although the spec lists it under `app.py` changes. Only `member_since` and `category_share` change. AC-26 is a new test against unchanged code.
- **C7 — `category_share` mixes types today.** `Decimal + 0.5` and `Decimal / float` both raise `TypeError`; the profile page would 500 for any user with expenses as soon as the database returns `Decimal`. Resolution: `Decimal` arithmetic with `ROUND_HALF_UP` (§2), and it must land **before** the driver switch (T1).
- **C8 — "conftest stops before `app` is imported."** `pytest.exit` raised at conftest import time is reported by pytest 8 as "ImportError while loading conftest" (exit code 4) rather than a clean exit. Resolution: module level only sets env vars; all three checks run in `pytest_sessionstart`, which runs before collection (the first `import app`). This satisfies the spec's ordering requirement and AC-35.
- **C9 — `/register` narrows what it catches.** Today any `sqlite3.IntegrityError` (including a blank-name CHECK, unreachable through validation) becomes "already exists"; after the step only `UniqueViolation` does. Intended by the spec; recorded so a reviewer doesn't read it as a regression.
- **C10 — loose date strings.** AC-10 drops `20-10-2026`, `2026-1-5`, `2026-02-28 10:00` because `DATE` accepts some of them. The existing test asserts they are rejected; that assertion is removed, not inverted. Step 7 must validate dates in Python (spec edge case).
- **C11 — the old AC-23 subprocess test keeps passing after the switch** (it fails on the secret key before any DB work, and the forced test `DATABASE_URL` is in the copied env), so its rewrite is not urgent; it is rewritten in T5 only to remove `SPENDLY_DB` for the DoD grep.
- **C12 — spec typo:** AC-35 is listed before AC-34. No impact.

## 8. Risks

- **psycopg wheel for Python 3.14:** if no pinned 3.x `psycopg-binary` has a `cp314` wheel, `pip install` falls back to source and needs libpq. Mitigation: check with `pip download --only-binary :all:` before pinning (T0).
- **`str` → `DATE`/`TIMESTAMPTZ` adaptation:** relies on psycopg dumping `str` as unknown OID. If it ever were `text`, inserts of ISO strings into `DATE` would fail with "expression is of type text". The seed, `_add_expense` and AC-10 exercise this immediately in T3, so a problem surfaces at once; fix would be explicit `%s::date` casts in the inserts.
- **Leaked connections blocking `DROP TABLE`:** autocommit means no transaction stays open after a statement, and `lock_timeout = '5s'` turns any leak into a fast failure.
- **Suite speed:** each test now opens several TCP connections and recreates the schema; expect the run to be noticeably slower than SQLite but still seconds, not minutes.
- **Recursive pytest in AC-35:** the subprocess runs the whole suite; it is safe only because `SPENDLY_TEST_DATABASE_URL` is removed, so it stops at `pytest_sessionstart`. The test must pop that variable (and set a `timeout=` on `subprocess.run`).

## 9. Build order

Each task ends with `SPENDLY_TEST_DATABASE_URL=... .venv/bin/pytest -q` green (before T3 the variable is simply ignored). The driver switch cannot be split — `?` vs `%s` and `sqlite3.Row` vs `dict` flip together — so everything backend-neutral is done before it and everything that needs PostgreSQL after it, keeping T3 as small as possible.

- **T0 — Environment and dependency.** Start `spendly-pg`, create `spendly` and `spendly_test`. Pick and verify the psycopg version (cp314 wheel), add `psycopg[binary]==3.X.Y` to `requirements.txt`, `.venv/bin/pip install -r requirements.txt`. Suite green on SQLite (psycopg installed, unused).
- **T1 — Type-safe pure helpers in `app.py`.** New `member_since` and `category_share` (+ `_to_decimal`), drop `math`. Add AC-26, AC-27, AC-28, AC-29. Existing helper tests still pass. Green on SQLite.
- **T2 — Backend-neutral test and code prep.** Add `resolve_database_url` to `db.py` (unused) with AC-2, AC-3, AC-4, AC-33. Switch `create_user`, `_insert_user` and `_add_expense` to `INSERT ... RETURNING id` with the row fetched inside the connection block and no `with conn:` (SQLite 3.54 supports `RETURNING`; placeholders stay `?`). Rewrite AC-19 (`["password_hash"]` works on `sqlite3.Row` too) and AC-21 (monkeypatch). Add AC-31. Green on SQLite.
- **T3 — The switch (atomic).** `database/db.py` fully converted (§1, removes `_resolve_db_path` and `sqlite3`); `tests/conftest.py` rewritten (§4); `app.py` `except psycopg.errors.UniqueViolation`; and every remaining driver-dependent test from §5b: AC-1, delete old resolve test, AC-5 through AC-15, AC-17, AC-18, AC-20, the three `?`-only tests in `test_database.py`, `_set_created_at`, and `test_registration.py` imports. Run the suite against `spendly_test`; green.
- **T4 — New PostgreSQL behaviour tests.** AC-22, AC-23, AC-24, AC-25, AC-32, AC-34. Green (they test behaviour T3 already delivered).
- **T5 — Startup subprocess tests.** Rewrite old AC-23 as AC-16; add AC-30 and AC-35. Green.
- **T6 — Docs and final checks.** `CLAUDE.md` (§6), `.claude/commands/create-spec.md`, `seed-user.md`, `seed-expenses.md` (C1). Run the DoD greps (`sqlite`, `SPENDLY_DB`, SQL / `connect(` in `app.py`), `shasum spendly.db` before/after, the wrong-dbname guard, the missing-`DATABASE_URL` import, `\d users` / `\d expenses`, and the manual browser checks from the spec's Definition of done. Suite green.

## 10. Verification

- Full suite: `SPENDLY_TEST_DATABASE_URL=postgresql://postgres:PASSWORD@localhost:5432/spendly_test .venv/bin/pytest -q`, collected count ≥ 172 + new cases.
- Guards: same command without the variable (stops with the fixed message); with `.../spendly` (stops, `spendly` still has its demo user); with the container stopped (stops once with the Docker message).
- Startup: `SPENDLY_ENV=production SPENDLY_SECRET_KEY=x .venv/bin/python3 -c "import app"` without `DATABASE_URL` → the fixed `RuntimeError`.
- Manual: run the app against `spendly` and walk the spec's browser checklist (demo profile `₹6,498.00`, upper-case registration, duplicate message, empty state, sign-out, restart does not duplicate the demo user).
