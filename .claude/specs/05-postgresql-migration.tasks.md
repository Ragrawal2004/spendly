# Tasks: Step 5 — PostgreSQL Migration

Companion to `05-postgresql-migration.md` (spec) and `05-postgresql-migration.design.md` (design). Planning only; no code here. The tasks are the design's build order (§9), T0 to T6, plus T7, a read-only final sweep.

**How to work through this list**
- Do the tasks in order. Each task from T0 to T6 is one commit, and the suite is green before every commit. T7 makes no commit.
- Red, green, commit: write the listed test first and watch it fail, make it pass, then run the full suite before committing. Each task's **Red then green** block says exactly what fails first and what makes it pass.
- When a test passes before the code exists, say so; it is a regression guard. For a guard, the task names a one-off mutation that proves the test can fail: apply it, see red, revert it, see green. Never commit a mutation.
- Suite command: T0 to T2 run `.venv/bin/pytest -q` (still SQLite; `SPENDLY_TEST_DATABASE_URL` is ignored). From T3 on, the same command runs against `spendly_test` and needs `SPENDLY_TEST_DATABASE_URL` set.
- Expected collected count after each task (`.venv/bin/pytest --collect-only -q | tail -1`): T0 172, T1 177, T2 185, T3 184, T4 190, T5 192, T6 192, T7 192. A different number means a test was lost or duplicated; stop and find it.
- New tests go into the existing file next to the behaviour they cover (spec "Files to create": none). Database errors are asserted with the exact psycopg class the spec names.
- No `with conn:` anywhere in code or tests (design C2, C3); multi-statement writes use `conn.transaction()`.
- Commit messages follow the repo's `type: summary` style. The `Co-Authored-By` trailer is added at commit time.
- `spendly.db` is never modified or deleted (spec Rules). From T3 on, `shasum spendly.db` before and after each suite run must match.

**Never print `DATABASE_URL` or `SPENDLY_TEST_DATABASE_URL`** (either may hold the real password):
- Both variables are exported in the developer's shell profile, outside the repo, so every Bash call has them. Commands refer to them only by name (`$DATABASE_URL`); no command, file, commit message or test contains a literal URL with a real password.
- Never run `echo`/`printf` on them, `env`, `printenv`, `set`, `export -p`, or `pytest -l` / `--showlocals`.
- To check a variable is set: `test -n "$SPENDLY_TEST_DATABASE_URL" && echo set || echo missing`.
- To check which database it names, print only the dbname: `.venv/bin/python3 -c 'import os; from psycopg.conninfo import conninfo_to_dict as c; print(c(os.environ["SPENDLY_TEST_DATABASE_URL"]).get("dbname"))'`.
- Tests never put a URL into an assertion message: AC-1 extracts the dbname into a local first and compares that; the subprocess tests (AC-16, AC-30, AC-35) only ever see fake URLs (`db.invalid`, `s3cret`). conftest and `resolve_database_url` messages are fixed strings.
- Database checks go through `docker exec spendly-pg psql -U postgres -d <db> ...`, which needs no URL.

---

## T0: environment and dependency

**Goal:** PostgreSQL is running with both databases, and psycopg is installed and pinned, while the app still runs on SQLite.

**Model:** Sonnet

**Change:**
- One-time setup (not committed): `docker start spendly-pg`; `docker exec spendly-pg psql -U postgres -d postgres -c "CREATE DATABASE spendly"`; the same for `spendly_test`.
- Pick the newest `psycopg-binary` 3.x with a `cp314` macOS arm64 wheel; confirm with `.venv/bin/pip download "psycopg-binary==3.X.Y" --only-binary :all: --no-deps -d <scratchpad dir>` (design §3, risk §8).
- `requirements.txt`: add `psycopg[binary]==3.X.Y`. `.venv/bin/pip install -r requirements.txt`.
- Shell profile (done by the developer outside Claude Code, before starting `claude`): export `DATABASE_URL` (dbname `spendly`) and `SPENDLY_TEST_DATABASE_URL` (dbname `spendly_test`). Claude Code never edits the shell profile and never handles the password; it only verifies with the set/dbname checks above, never by printing them.

**ACs satisfied:** none.

**Red then green:**
- Red: `.venv/bin/python3 -c "import psycopg"` fails with `ModuleNotFoundError`. `docker exec spendly-pg psql -U postgres -d postgres -Atc "select datname from pg_database where datname in ('spendly','spendly_test') order by 1"` prints fewer than two names.
- Green: `.venv/bin/python3 -c "import psycopg; print(psycopg.__version__)"` prints the pinned version; the query prints `spendly` and `spendly_test`; both dbname checks print the right name.
- Suite: `.venv/bin/pytest -q` green on SQLite (psycopg installed, unused); collected 172.

**Commit:** `build: add psycopg dependency`

---

## T1: type-safe pure helpers in app.py

**Goal:** the profile helpers accept `Decimal` and `datetime` before the database starts returning them, so the switch in T3 cannot break `/profile` (design C7).

**Model:** Sonnet

**Change:** `app.py` (design §2) —
- Add `from decimal import Decimal, ROUND_HALF_UP`; remove `import math`.
- `member_since(created_at)`: `datetime` first (naive treated as UTC via `replace(tzinfo=timezone.utc)`, aware converted with `astimezone(timezone.utc)`), then `strftime("%B %Y")`; `str` keeps today's `strptime` path with `ValueError` → `None`; anything else → `None`.
- `_to_decimal(x)` (`x` if already `Decimal`, else `Decimal(str(x))`) next to `category_share`; `category_share` returns `0` if `not overall`, else `int((t * 100 / o).quantize(Decimal("1"), rounding=ROUND_HALF_UP))`.
- `format_amount` unchanged (design C6).

**ACs satisfied:** AC-26, AC-27, AC-28, AC-29.

**Test first** (`tests/test_profile.py`, one test per AC, in order):
- AC-26: `Decimal("12345678.90")`, `Decimal("0")`, `Decimal("0.30")`, `Decimal("400.00")` → `₹12,345,678.90`, `₹0.00`, `₹0.30`, `₹400.00`.
- AC-27: `(Decimal("400.00"), Decimal("600.00"))` → 67, `(Decimal("12.50"), Decimal("100.00"))` → 13, `(Decimal("0"), Decimal("0"))` → 0, `(Decimal("1.00"), Decimal("3.00"))` → 33, `(Decimal("5.00"), 10)` → 50; each result `isinstance(..., int)`.
- AC-28: aware UTC, naive, and `+05:30` `2026-04-01 04:00` datetimes each → `"March 2026"`.
- AC-29 (parametrised): `date(2026, 3, 5)` and `12345` → `None`.

**Red then green:**
- Red: AC-27 fails with `TypeError` (`Decimal + float` in the current `category_share`); AC-28 fails because the current `member_since` returns `None` for a `datetime`.
- Guards: AC-26 passes already (C6) — mutation: expect `₹0.3` for `Decimal("0.30")`, see red, revert. AC-29 passes already (current code catches `TypeError`) — mutation: expect `"March 2026"` for `date(2026, 3, 5)`, see red, revert.
- Green: all four pass; the existing helper tests (`test_member_since_valid`, `test_member_since_invalid_returns_none`, the `category_share` and `format_amount` tests) still pass unchanged. Suite green on SQLite; collected 177.

**Commit:** `feat: make profile helpers Decimal and datetime safe`

---

## T2: backend-neutral prep

**Goal:** everything that works on both drivers lands before the switch, so T3 is as small as possible.

**Model:** Sonnet

**Change:**
- `database/db.py`: add `_MISSING_URL_MESSAGE` (exactly `DATABASE_URL must be set, e.g. DATABASE_URL=postgresql://USER:PASSWORD@HOST:5432/spendly`) and pure `resolve_database_url(env)`: return `env.get("DATABASE_URL")` if truthy, else `raise RuntimeError(_MISSING_URL_MESSAGE)`. It ignores `SPENDLY_ENV` and never formats an env value into the message. Not yet called by anything.
- `create_user()`: `INSERT ... RETURNING id`, return the fetched row's `id` inside the connection block; no `with conn:`. Placeholders stay `?` (SQLite ≥ 3.35 supports `RETURNING`; check `.venv/bin/python3 -c "import sqlite3; print(sqlite3.sqlite_version)"`).
- `tests/test_database.py::_insert_user` and `tests/test_profile.py::_add_expense`: the same `RETURNING id` pattern, row fetched inside `closing(...)`, no `with conn:` (C2).
- `tests/test_profile.py`: rewrite AC-19 to `fetchone()["password_hash"]`; rewrite AC-21 (`test_profile_bad_created_at_ac25`, `"garbage"` and `""`) to monkeypatch `app.get_user_profile`, modelled on `test_profile_null_created_at_ac25`.

**ACs satisfied:** AC-2, AC-3, AC-4, AC-19, AC-21, AC-31, AC-33.

**Test first** (one test per AC, in order):
- AC-2 (`test_database.py`): `{"DATABASE_URL": "postgresql://u@h/db"}` returned unchanged.
- AC-3 (parametrised ×2): `SPENDLY_ENV=production` with `DATABASE_URL` missing, and set to `""` → `RuntimeError` mentioning `DATABASE_URL`.
- AC-4 (parametrised ×3): `{}`, `{"SPENDLY_ENV": "development"}`, `{"SPENDLY_ENV": "development", "DATABASE_URL": ""}` → `RuntimeError`.
- AC-33: `{"SPENDLY_TEST_DATABASE_URL": "postgresql://u:s3cret@h/spendly_test"}` → message exactly equal to the fixed string, `"s3cret"` not in it.
- AC-19, AC-21: the rewrites above.
- AC-31 (`test_login_logout.py`): register through `POST /register`, `POST /login`, then `session["user_id"] == get_user_by_email(...)["id"]` and is an `int`; `GET /profile` is 200.

**Red then green:**
- Red: AC-2, AC-3, AC-4, AC-33 fail at import (`ImportError: cannot import name 'resolve_database_url'`). `grep -rn "lastrowid" database/ tests/` prints matches.
- Guards: AC-19, AC-21 and AC-31 pass on SQLite (`sqlite3.Row` supports `["password_hash"]`; ids are already `int`). Mutations: AC-19 — assert the hash *is* in the body, see red, revert; AC-21 — return `"2026-03-05 10:20:30"` from the monkeypatch and expect no "Member since", see red, revert; AC-31 — assert `isinstance(..., str)`, see red, revert.
- Green: all pass; `grep -rn "lastrowid" database/ tests/` prints nothing; the existing `create_user` and profile tests stay green. Suite green on SQLite; collected 185.

**Commit:** `refactor: add resolve_database_url and RETURNING id inserts`

---

## T3: the switch (one atomic commit)

**Goal:** the data layer runs on PostgreSQL. `?` vs `%s` and `sqlite3.Row` vs `dict` flip together, so this cannot be split: driver, conftest, `app.py`'s except clause and every driver-dependent test land in one commit.

**Model:** Opus

**Change:**
- `database/db.py` (design §1): drop `sqlite3` and `_resolve_db_path`; `get_db()` = `psycopg.connect(resolve_database_url(os.environ), row_factory=dict_row, autocommit=True)`; `_SCHEMA` as a tuple of four statements (raw string for `E' \t\n\r'`), run by `init_db()` inside `conn.transaction()`; `%s` everywhere; `get_expense_summary` uses `%s::date`; return hints `dict` / `list[dict]`; `seed_db()` with `ON CONFLICT (email) DO NOTHING RETURNING id` inside one `conn.transaction()`, password hashed before the transaction opens.
- `tests/conftest.py` (design §4): module level assigns `os.environ["DATABASE_URL"] = _TEST_URL` and sets the secret key default; `pytest_sessionstart` stops on missing URL, dbname other than `spendly_test` (including an unparsable URL), and unreachable server, each with its fixed message; `isolated_db` sets `lock_timeout = '5s'` and drops `expenses, users CASCADE`; `client` unchanged in meaning.
- `app.py`: drop `import sqlite3`, add `import psycopg`, `except psycopg.errors.UniqueViolation:` in `register()` (C9).
- `tests/test_database.py`: drop `sqlite3`, add `psycopg`, `Decimal`, `conninfo_to_dict`; `_insert_user` to `%s`; AC-1 replaces the `SPENDLY_DB` isolation test; delete `test_resolve_db_path_falls_back_to_project_root`; AC-5 to AC-14; `?` → `%s` in `test_delete_user_cascades_to_expenses`, `test_demo_password_is_hashed_and_verifiable` and `test_seed_db_noop_when_demo_user_exists_from_other_connection` (the last also drops its inner `with conn:`, C3).
- `tests/test_profile.py`: `_add_expense` and `_set_created_at` to `%s`; AC-17, AC-18, AC-20.
- `tests/test_registration.py`: `import sqlite3` → `import psycopg`; AC-15.

**ACs satisfied:** AC-1, AC-5, AC-6, AC-7, AC-8, AC-9, AC-10, AC-11, AC-12, AC-13, AC-14, AC-15, AC-17, AC-18, AC-20.

**Test first** (rewrites, one per AC, in order):
- AC-1: `dbname = conninfo_to_dict(os.environ["DATABASE_URL"]).get("dbname")`, then `assert dbname == "spendly_test"` (only the dbname can appear in a failure); `spendly.db` existence and mtime unchanged (module-level `_REAL_DB_*` capture stays).
- AC-5: `TEMP` table, `%s` insert, row is a `dict` with `row["col"] == "value"`, `conn.autocommit is True`, `SELECT 1/0` raises `psycopg.errors.DivisionByZero`, then `SELECT 1` on the same connection succeeds.
- AC-6: `init_db()` twice; `to_regclass` finds `users`, `expenses`, `idx_expenses_user_date`, `idx_users_email`; `pg_index.indisunique` is true for `idx_users_email`.
- AC-7: `ForeignKeyViolation` for `user_id` 999.
- AC-8: one connection, amount `0`, `-5`, category `Groceries` → `CheckViolation` each.
- AC-9 (×3): names `""`, `"   "`, `"\t\n"` → `CheckViolation`.
- AC-10: `2026-02-30`, `2026-04-31`, `2026-13-01` → `psycopg.DataError`; `2026-02-28` and `2028-02-29` insert, 2 rows. The loose-format assertions are removed, not inverted (C10).
- AC-11: seeded dates are the set of `datetime.date` values for 2026-10-01, 03, 05, 08, 12, 15, 18, 22; categories within the seven.
- AC-12: `DEMO@SPENDLY.COM` → `CheckViolation`; `demo@spendly.com` → `UniqueViolation`.
- AC-13: fifth demo row amount `0` → `CheckViolation`; counts `(0, 0)`.
- AC-14: `SPENDLY_ENV=production`, `app.startup()`; `to_regclass` finds both tables; no demo user.
- AC-15: `create_user` monkeypatched to raise `psycopg.errors.UniqueViolation("x")` → 400 and "An account with this email already exists."
- AC-17: exact `Decimal("20.00")`, `Decimal("40.00")`, `count == 4`; no `pytest.approx`.
- AC-18: five dates `date(2026, 10, 7)` down to `date(2026, 10, 3)`.
- AC-20: `_set_created_at(uid, "2026-03-05 10:20:30+00")` → `Member since March 2026`.

**Red then green:**
- Red, in this order and only this way: rewrite the **test files only** (`test_database.py`, `test_profile.py`, `test_registration.py`) and keep the old conftest and old `db.py`. Run just the rewritten tests on SQLite (`.venv/bin/pytest -q tests/test_database.py tests/test_profile.py tests/test_registration.py`): they fail — `%s` is a syntax error in SQLite, `sqlite3.IntegrityError` is not a psycopg class, rows are not `dict`, dates come back as `str`, AC-1's dbname is `None`.
- **Never run any test with the new conftest and the old `db.py`**: the new conftest no longer sets `SPENDLY_DB`, so the old `db.py` would fall back to the real `spendly.db`. Rewrite `conftest.py`, `db.py` and `app.py` together, then run.
- Green: `shasum spendly.db` → `.venv/bin/pytest -q` → `shasum spendly.db`: suite green against `spendly_test`, both hashes identical, collected 184.
- Guard checks (conftest `pytest_sessionstart`, by hand, no test):
  - `env -u SPENDLY_TEST_DATABASE_URL .venv/bin/pytest -q` stops before any test with the fixed `SPENDLY_TEST_DATABASE_URL must be set, ...` message.
  - Wrong dbname, against a throwaway database: `docker exec spendly-pg psql -U postgres -d postgres -c "CREATE DATABASE spendly_scratch"`; `SPENDLY_TEST_DATABASE_URL="$(.venv/bin/python3 -c 'import os; from psycopg.conninfo import conninfo_to_dict as c, make_conninfo as m; d = c(os.environ["DATABASE_URL"]); d["dbname"] = "spendly_scratch"; print(m(**d))')" .venv/bin/pytest -q` (dbname `spendly_scratch`; the URL goes only into the variable, never to the terminal) stops before any test with the "must point at a database named spendly_test" message; `docker exec spendly-pg psql -U postgres -d spendly_scratch -Atc "select count(*) from pg_tables where schemaname='public'"` is the same before and after; `docker exec spendly-pg psql -U postgres -d postgres -c "DROP DATABASE spendly_scratch"`. The same check against `spendly` itself is left to T7.
  - `docker stop spendly-pg`, `.venv/bin/pytest -q` stops once with the message naming `docker start spendly-pg` and the `CREATE DATABASE spendly_test` command (not 184 failures); `docker start spendly-pg`.
  - None of the three outputs contains a URL or password.
- `grep -rn sqlite3 app.py database/ tests/` prints nothing. (`SPENDLY_DB` still appears in `test_login_logout.py` until T5; that is expected, C11.)

**Commit:** `feat: switch data layer from SQLite to PostgreSQL`

---

## T4: new PostgreSQL behaviour tests

**Goal:** lock in the behaviour T3 delivered: exact money, real dates and timestamps, idempotent seeding, and no crash on huge session ids.

**Model:** Sonnet

**Change:** tests only.

**ACs satisfied:** AC-22, AC-23, AC-24, AC-25, AC-32, AC-34.

**Test first** (one test per AC, in order):
- AC-22 (`test_database.py`): raw `UPDATE users SET created_at = %s` with `"garbage"` → `psycopg.errors.InvalidDatetimeFormat`.
- AC-23 (`test_database.py`): amount `0.004` → `CheckViolation`; `12.345` stored and read back as `Decimal("12.35")`; `10000000000` → `psycopg.errors.NumericValueOutOfRange`.
- AC-24 (`test_profile.py`): expenses `100.00`, `250.50`, `49.50` (one this month): `total`, `month_total`, every category `total` and every `amount` are `Decimal`; every `count` is `int`; every `date` is `datetime.date`; `get_user_profile(uid)["created_at"]` is a `datetime` with `tzinfo` not `None`.
- AC-25 (`test_profile.py`): no expenses → `total` and `month_total` are `Decimal` equal to 0, `count` is the `int` 0.
- AC-32 (`test_database.py`): `init_db()`, `seed_db(date(2026, 10, 20))` twice → one demo user, eight expenses, amounts sum to `Decimal("6498.00")`.
- AC-34 (`test_profile.py`): `client.session_transaction()` sets `user_id = 10**30`; `GET /profile` → 302, `Location` ends in `/login`, no 500.

**Red then green:**
- All six pass on first run: the behaviour arrived in T3. Record them as regression guards. (AC-34 would have been red on SQLite — `OverflowError` → 500 — C5.)
- Mutations, one each, apply → red → revert: AC-22 update with a valid `"2026-03-05 10:20:30+00"`; AC-23 expect `Decimal("12.34")`; AC-24 expect `amount` to be `float`; AC-25 expect `count` to be `Decimal`; AC-32 expect two demo users; AC-34 expect status 200.
- Green: suite green, `shasum spendly.db` unchanged, collected 190.

**Commit:** `test: cover PostgreSQL types, constraints and seeding`

---

## T5: startup subprocess tests

**Goal:** prove that a process without a database URL refuses to start, with a message that never leaks a password, and remove the last `SPENDLY_DB` use.

**Model:** Sonnet

**Change:** tests only (`test_login_logout.py`, `test_database.py`).

**ACs satisfied:** AC-16, AC-30, AC-35.

**Test first** (one test per AC, in order):
- AC-16 (`test_login_logout.py`): rewrite `test_ac23_production_import_without_key_fails_before_db_work`: subprocess `import app` with `SPENDLY_ENV=production`, no `SPENDLY_SECRET_KEY`, `DATABASE_URL=postgresql://spendly@db.invalid/nowhere`; non-zero exit; stderr has `RuntimeError` and `SPENDLY_SECRET_KEY`, and neither `psycopg` nor `OperationalError`. No `SPENDLY_DB`, no `tmp_path`.
- AC-30 (`test_login_logout.py`): copy `os.environ`, **pop `DATABASE_URL`** (conftest set it), set `SPENDLY_ENV=production` and a secret key; non-zero exit; stderr has `RuntimeError` and the exact `DATABASE_URL must be set, ...` message, not `OperationalError`.
- AC-35 (`test_database.py`): subprocess `[sys.executable, "-m", "pytest", "-q", "tests"]`, `cwd=Path(__file__).resolve().parent.parent`, `SPENDLY_TEST_DATABASE_URL` popped, `DATABASE_URL=postgresql://u:s3cret@h/spendly`, with a `timeout=`; non-zero exit, no test run, combined output has the exact `SPENDLY_TEST_DATABASE_URL must be set, ...` message and not `s3cret`. Popping the variable is what stops the recursion (risk §8); never write this test without the pop.

**Red then green:**
- All three pass once written (T3 delivered the behaviour; C11 for AC-16). Real reds by withholding one step of the setup:
  - AC-16: also set `SPENDLY_SECRET_KEY` in the subprocess env → import reaches `init_db()`, stderr has `OperationalError` → red; remove it → green.
  - AC-30: leave out the `DATABASE_URL` pop → import succeeds against `spendly_test`, exit 0 → red; add the pop → green.
  - AC-35: mutation only (a red by omitting the pop would recurse): expect `SPENDLY_TEST_DATABASE_URL is required` → red; revert → green.
- Green: suite green, `shasum spendly.db` unchanged, collected 192. `grep -rn "SPENDLY_DB" app.py database/ tests/` prints nothing.

**Commit:** `test: cover startup without database URLs`

---

## T6: docs

**Goal:** the project guide and the slash-command docs match the code.

**Model:** Sonnet

**Change:**
- `CLAUDE.md` (design §6): PostgreSQL throughout; one-time Docker setup; dev server and test commands with `DATABASE_URL` / `SPENDLY_TEST_DATABASE_URL` (both required) and only placeholder passwords (`postgresql://postgres:PASSWORD@localhost:5432/...`); `SPENDLY_DB` removed; `/register` catches `UniqueViolation` only; `member_since` accepts `datetime`; the `database/db.py` bullet (`resolve_database_url`, autocommit + `dict_row`, `RETURNING id`, `seed_db` with `ON CONFLICT DO NOTHING` in `conn.transaction()`, return types, the lowercase CHECK as the reason emails are lowercased in Python, no `with conn:`); last line "No ORM — raw `psycopg` access through `database/db.py`."
- `.claude/commands/create-spec.md`: the acceptance-criteria paragraph says tests use the `spendly_test` database (reset before every test) and never touch `spendly` or `spendly.db`.
- `.claude/commands/seed-user.md`, `.claude/commands/seed-expenses.md` (design C1, outside the spec's file list but broken by the switch): `%s` placeholders and `with closing(get_db()) as conn, conn.transaction():`.

**ACs satisfied:** none.

**Red then green (docs):**
- Red: `grep -rn "SPENDLY_DB" CLAUDE.md .claude/commands/` and `grep -n "sqlite3" CLAUDE.md` print matches; `grep -nE "with conn:|\?" .claude/commands/seed-user.md .claude/commands/seed-expenses.md` shows the old placeholders and `with conn:`.
- Green: the first two print nothing; the third shows no SQL `?` placeholder and no `with conn:`. `grep -nE "postgresql://[^ ]*:[^ ]*@" CLAUDE.md` shows only `PASSWORD` / `USER:PASSWORD` placeholders.
- Re-read every changed line against the final code from T1 to T5.

**Commit:** `docs: document PostgreSQL setup`

---

## T7: final sweep (read-only)

**Goal:** the whole step meets the spec's Definition of Done.

**Model:** Opus

**Change:** none. Read-only: no file edits and no commits.

**ACs satisfied:** none new. All of AC-1 to AC-35 pass together (owners in the coverage table).

**Final sweep.** If it finds a gap, stop and report it; the fix (a failing test first, then the fix, committed separately as `fix: ...`) is follow-up work outside T7.

- [ ] `.venv/bin/pytest --collect-only -q | tail -1` reports **192 tests collected**
- [ ] All acceptance criteria (AC-1 to AC-35) and every other existing test pass with `.venv/bin/pytest -q` (`SPENDLY_TEST_DATABASE_URL` from the shell profile, never typed or printed)
- [ ] `docker exec spendly-pg psql -U postgres -d postgres -c "CREATE DATABASE spendly"` and the same for `spendly_test` were run once (T0), and `.venv/bin/pip install -r requirements.txt` installs psycopg
- [ ] `grep -rn "sqlite" app.py database/ tests/` prints nothing
- [ ] `grep -rn "SPENDLY_DB" app.py database/ tests/ CLAUDE.md .claude/commands/` prints nothing
- [ ] `grep -nE "(SELECT|INSERT|UPDATE|DELETE)" app.py` finds no SQL, and `grep -n "connect(" app.py` finds nothing
- [ ] `shasum spendly.db` before and after `pytest -q` is identical, and before and after running the app by hand
- [ ] `SPENDLY_TEST_DATABASE_URL="$DATABASE_URL" .venv/bin/pytest -q` stops before any test, and `spendly` still has its tables and demo user (`docker exec spendly-pg psql -U postgres -d spendly -c "select count(*) from users"`)
- [ ] `env -u DATABASE_URL SPENDLY_ENV=production SPENDLY_SECRET_KEY=x .venv/bin/python3 -c "import app"` exits with `RuntimeError: DATABASE_URL must be set, e.g. DATABASE_URL=postgresql://USER:PASSWORD@HOST:5432/spendly`
- [ ] `docker exec spendly-pg psql -U postgres -d spendly -c "\d users"` shows `created_at timestamp with time zone`, the `users_email_lowercase` CHECK and the unique index `idx_users_email`; `\d expenses` shows `amount numeric(12,2)` and `date date`
- [ ] The app was run by hand (`SPENDLY_SECRET_KEY=dev-only-value .venv/bin/python3 app.py`, `DATABASE_URL` from the shell profile, dbname `spendly`) and verified in the browser:
  - [ ] Signing in as `demo@spendly.com` / `demo123` lands on the profile page with "Member since <current month and year>", total `₹6,498.00`, eight expenses, the category breakdown with percentages, and five recent expenses with `YYYY-MM-DD` dates, newest first
  - [ ] Registering a new user with an upper-case email succeeds, signing in with a different letter case works, and registering the same email again shows "An account with this email already exists."
  - [ ] A freshly registered user sees the empty state (`₹0.00`, `0 expenses`, "No expenses yet.")
  - [ ] Signing out returns to the landing page; `/profile` then redirects to `/login`
  - [ ] Restarting the app does not create a second demo user (`docker exec spendly-pg psql -U postgres -d spendly -c "select count(*) from users where email='demo@spendly.com'"` prints 1)
- [ ] `CLAUDE.md` describes PostgreSQL, `DATABASE_URL`, `SPENDLY_TEST_DATABASE_URL` and the Docker `CREATE DATABASE` setup, uses only placeholder passwords, and no longer mentions `SPENDLY_DB` or `sqlite3`

**Extra checks from the design:**
- No output from any task contained either URL or a real password (scroll back through the session).
- `git status` shows changes only in the files the spec lists, plus `seed-user.md` and `seed-expenses.md` (C1).
- `spendly.db` is still on disk, unchanged.
- Known gaps stay as recorded: no CSRF token, no rate limiting, `/expenses/*` placeholders public until Steps 7-9, no connection pool and no `sslmode=require` until the deploy step, loose date strings accepted by `DATE` until Step 7 validates in Python (C10).

**Commit:** none (read-only).

---

## AC coverage

| AC | Task | AC | Task |
| --- | --- | --- | --- |
| AC-1 | T3 | AC-19 | T2 (guard) |
| AC-2 | T2 | AC-20 | T3 |
| AC-3 | T2 | AC-21 | T2 (guard) |
| AC-4 | T2 | AC-22 | T4 (guard) |
| AC-5 | T3 | AC-23 | T4 (guard) |
| AC-6 | T3 | AC-24 | T4 (guard) |
| AC-7 | T3 | AC-25 | T4 (guard) |
| AC-8 | T3 | AC-26 | T1 (guard) |
| AC-9 | T3 | AC-27 | T1 |
| AC-10 | T3 | AC-28 | T1 |
| AC-11 | T3 | AC-29 | T1 (guard) |
| AC-12 | T3 | AC-30 | T5 |
| AC-13 | T3 | AC-31 | T2 (guard) |
| AC-14 | T3 | AC-32 | T4 (guard) |
| AC-15 | T3 | AC-33 | T2 |
| AC-16 | T5 (guard, C11) | AC-34 | T4 (guard; fixed by T3, C5) |
| AC-17 | T3 | AC-35 | T5 (guard) |
| AC-18 | T3 | | |

All 35 criteria are covered. T0, T6 and T7 own no AC; T7 re-verifies all of them.

Collected count: 172 → T1 +5 (AC-26, 27, 28, 29 ×2) = 177 → T2 +8 (AC-2, AC-3 ×2, AC-4 ×3, AC-33, AC-31) = 185 → T3 −1 (old resolve test deleted) = 184 → T4 +6 = 190 → T5 +2 (AC-30, AC-35; AC-16 is a rewrite) = **192**.
