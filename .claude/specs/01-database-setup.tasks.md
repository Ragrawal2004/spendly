# Tasks: Database Setup (Spec 01, Design v1)

Source: `.claude/specs/01-database-setup.md` (v3) + the approved design (function signatures, `seed_db` order of operations, `startup()` wiring, test isolation).

Build order below respects dependencies (gitignore/deps/test-harness first, then `db.py` functions bottom-up, then `app.py`, then the remaining cross-cutting tests). Per the spec's workflow: write the test for a task first, then the code; one commit per task.

---

## Task 1 — `.gitignore`: ignore the database file

Append `spendly.db` and `*.db`. Leave the existing `expense_tracker.db` line as-is.

- No test (not testable via pytest).
- Commit: `chore: gitignore spendly.db`

---

## Task 2 — `requirements-dev.txt`

Create with the versions already pinned in `requirements.txt`:
```
pytest==8.3.5
pytest-flask==1.3.0
```

- No test.
- Commit: `chore: add requirements-dev.txt`

---

## Task 3 — `tests/conftest.py`: database isolation harness

- Module-level: `os.environ.setdefault("SPENDLY_DB", <session temp file>)`, set **before** anything imports `app.py`, so the first (incidental) import never touches the real `spendly.db`.
- Autouse, function-scoped fixture `isolated_db(tmp_path, monkeypatch)`: points `SPENDLY_DB` at a fresh `tmp_path / "test.db"` for every test.

Satisfies: **AC-11** (real `spendly.db` never created/modified by tests).

- Test: a trivial test in `tests/test_database.py` asserting `os.environ["SPENDLY_DB"]` is set and the path doesn't equal the project's real `spendly.db` path, and that the real file doesn't exist on disk after the test session. (This can be folded into Task 9's AC-11 test once that file exists — write the fixture now, assert it later.)
- Commit: `test: add database test isolation fixture`

---

## Task 4 — `database/db.py`: `get_db()`

- Resolves the DB path fresh on every call (`os.environ.get("SPENDLY_DB")`, falling back to a path built from `__file__`, never cached at module level).
- Opens `sqlite3.connect(path)`, sets `row_factory = sqlite3.Row`, `isolation_level = None`, runs `PRAGMA foreign_keys = ON`.
- Returns the connection; caller closes it.

Satisfies: **AC-8**.

- Test: `test_get_db_returns_row_with_foreign_keys_on` — open a connection, assert `PRAGMA foreign_keys` returns `1`, insert/select a row and confirm `row["col"]` access works.
- Commit: `feat(db): implement get_db`

---

## Task 5 — `database/db.py`: `init_db()` + schema constraints

- Implements the `CREATE TABLE IF NOT EXISTS` / `CREATE INDEX IF NOT EXISTS` statements from spec section 4.C verbatim (users, expenses, index), using `with closing(get_db()) as conn:` / `with conn:`.
- Safe to call repeatedly.

Satisfies: **AC-1**, and the schema-enforced constraints checked directly against a freshly-`init_db()`'d connection: **AC-6, AC-7, AC-9, AC-13, AC-14**.

- Tests:
  - `test_init_db_creates_tables_and_index` (AC-1)
  - `test_expense_with_missing_user_id_raises` (AC-6)
  - `test_expense_amount_and_category_constraints` (AC-7: amount 0, negative, bad category)
  - `test_delete_user_cascades_to_expenses` (AC-9)
  - `test_blank_name_variants_raise` (AC-13: `""`, `"   "`, `"\t\n"`)
  - `test_date_constraint_rejects_invalid_accepts_valid` (AC-14: all 6 invalid dates + `2026-02-28` + `2028-02-29` accepted)
- Commit: `feat(db): implement init_db and verify schema constraints`

---

## Task 6 — `database/db.py`: `_demo_expenses(today)`

- Module-level helper, single source of the 8 seed rows (section 5.C table), returns `(category, amount, date_str, description)` tuples built from `today.replace(day=offset)`.

- Test: `test_demo_expenses_shape` — given `date(2026, 10, 20)`, returns exactly 8 tuples, dates `2026-10-01/03/05/08/12/15/18/22`, all 7 categories present (Food twice). (Covers the data half of AC-3; AC-3's full assertion lands in Task 7's test once `seed_db` exists.)
- Commit: `feat(db): implement _demo_expenses helper`

---

## Task 7 — `database/db.py`: `seed_db(today=None)`

- Implements the order of operations from the design: `BEGIN IMMEDIATE` → existence check inside the transaction → quiet return if the demo user exists → insert user → insert each `_demo_expenses()` row via a per-row `execute()` loop (not `executemany`) → `commit()`; any exception → `rollback()` then re-raise; `finally: conn.close()`.
- Defaults `today` to `datetime.now(timezone.utc).date()` when not given.

Satisfies: **AC-2, AC-3, AC-4, AC-5, AC-10, AC-15**.

- Tests:
  - `test_seed_db_is_idempotent` (AC-2: run `init_db`+`seed_db` three times total, still 1 user / 8 expenses)
  - `test_seed_db_dates_and_categories` (AC-3, using `_demo_expenses` + inserted rows)
  - `test_demo_password_is_hashed_and_verifiable` (AC-4)
  - `test_duplicate_email_case_insensitive_raises` (AC-5)
  - `test_seed_db_rolls_back_on_bad_row` (AC-10: monkeypatch `db._demo_expenses` to make row 5 `amount=0`, assert `IntegrityError` propagates and 0 users / 0 expenses remain)
  - `test_seed_db_noop_when_demo_user_exists_from_other_connection` (AC-15: insert the demo user via a separate `get_db()` connection first, then call `seed_db()`, assert no exception and counts unchanged)
- Commit: `feat(db): implement seed_db`

---

## Task 8 — `app.py`: `startup()` wiring

- Add `import os` and `from database.db import init_db, seed_db`.
- Add `startup()` (per design section 3) and call it at module level, right after `app = Flask(__name__)`, before the route decorators.

Satisfies: **AC-12**.

- Test: `test_startup_skips_seed_in_production` — `monkeypatch.setenv("SPENDLY_ENV", "production")`, point `SPENDLY_DB` at a fresh temp file, call `app.startup()` directly, assert the `users`/`expenses` tables exist and the demo user does not.
- Commit: `feat(app): wire up database startup`

---

## Task 9 — close out `tests/test_database.py`

By this point every AC-1…AC-15 test already exists (written alongside its task above). This task is just final cleanup: confirm `tests/test_database.py` contains all 15, run `pytest -q` and fix anything that only surfaces once the whole file runs together (ordering/fixture leakage between tests).

- Commit: `test: finish AC-1 through AC-15 coverage`

---

## Definition of Done (carried over from spec section 15)

- [ ] All 9 tasks above committed individually
- [ ] `pytest -q` passes, AC-1 through AC-15
- [ ] `python app.py` and `flask run` both start cleanly and produce `spendly.db` with the demo user + 8 expenses
- [ ] `SPENDLY_ENV=production python app.py` produces schema only, no demo user
- [ ] `spendly.db` is git-ignored
