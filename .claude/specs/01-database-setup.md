# Spec 01: Database Setup (Spendly)

Status: v3 (second review applied, SQLite behavior verified on 3.45.1)
Branch: `feature/database-setup`

## 1. Overview

Replace the stub in `database/db.py` with a working SQLite implementation.

This step establishes the **data layer foundation** for Spendly. Authentication, profile and expense tracking all depend on it being correct, so this step also adds the tests that prove it.

---

## 2. Depends on

Nothing. This is the first step.

---

## 3. Routes

- No new routes.
- Existing placeholder routes in `app.py` remain unchanged.

---

## 4. Database Schema

Database file: `spendly.db` in the project root. This is the only database name used anywhere. The path is built from the location of `database/db.py`, not from the current working directory, and can be overridden with the `SPENDLY_DB` environment variable (tests rely on this).

### A. users

| Column | Type | Constraints |
| --- | --- | --- |
| id | INTEGER | Primary key, autoincrement |
| name | TEXT | Not null, must not be blank (spaces, tabs and newlines do not count as content) |
| email | TEXT | Unique (case-insensitive, ASCII only, see note), not null |
| password_hash | TEXT | Not null |
| created_at | TEXT | Not null, default `datetime('now')` (UTC) |

### B. expenses

| Column | Type | Constraints |
| --- | --- | --- |
| id | INTEGER | Primary key, autoincrement |
| user_id | INTEGER | Not null, foreign key to `users.id`, `ON DELETE CASCADE` |
| amount | REAL | Not null, must be greater than 0 |
| category | TEXT | Not null, must be one of the fixed categories (section 10) |
| date | TEXT | Not null, must be a real calendar date in `YYYY-MM-DD` format |
| description | TEXT | Nullable |
| created_at | TEXT | Not null, default `datetime('now')` (UTC) |

Index: `idx_expenses_user_date` on `expenses(user_id, date)`.

### C. Reference SQL

```sql
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    name          TEXT NOT NULL
                  CHECK (length(trim(name, ' ' || char(9) || char(10) || char(13))) > 0),
    email         TEXT NOT NULL UNIQUE COLLATE NOCASE,
    password_hash TEXT NOT NULL,
    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS expenses (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    amount      REAL NOT NULL CHECK (amount > 0),
    category    TEXT NOT NULL CHECK (category IN
                  ('Food','Transport','Bills','Health','Entertainment','Shopping','Other')),
    date        TEXT NOT NULL CHECK (date(date) IS NOT NULL AND date(date) = date),
    description TEXT,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_expenses_user_date ON expenses(user_id, date);
```

Notes (each verified by running it on SQLite 3.45.1):

- A `CHECK` that evaluates to NULL passes in SQLite, which is why the date check tests `IS NOT NULL` explicitly.
- `date('2026-02-30')` does not return NULL. SQLite normalizes it to `2026-03-02`. The `date(date) = date` comparison is what rejects it. Both halves of the check are needed: the first catches unparseable input (`2026-13-01`, `20-10-2026`), the second catches overflow dates (`2026-02-30`, `2026-04-31`) and values with a time part (`2026-02-28 10:00`).
- `trim(x)` strips spaces only, so a name of `"\t\n"` would pass a plain `trim(name)` check. The explicit character list fixes this. SQL string literals do not interpret `\t`, hence `char(9)`, `char(10)`, `char(13)`.
- `COLLATE NOCASE` folds ASCII letters only. `a@x.com` and `A@X.COM` collide, but `é@x.com` and `É@x.com` do not. This step accepts that limit. The signup step must lowercase and strip the email in application code before inserting.

---

## 5. Functions to Implement (`database/db.py`)

### A. `get_db()`

- Opens a new connection to the database path described in section 4.
- Sets `row_factory = sqlite3.Row`.
- Runs `PRAGMA foreign_keys = ON` on every connection it opens.
- Returns the connection.
- The caller is responsible for closing it. Inside this module use `with closing(get_db()) as conn:` and `with conn:` for transactions.

### B. `init_db()`

- Creates both tables and the index using `CREATE TABLE IF NOT EXISTS` / `CREATE INDEX IF NOT EXISTS`.
- Safe to call any number of times.
- Closes its connection when done.

### C. `_demo_expenses(today)`

- Module-level helper, the single source of the seed rows. Returns a list of 8 tuples `(category, amount, date_str, description)` built from the table below and the `today` date (1st of that month plus the day offset).
- It exists as its own function so tests can replace it (AC-10).

### D. `seed_db(today=None)`

- `today` is a `datetime.date`. When `None`, it defaults to `datetime.now(timezone.utc).date()`. Tests always pass a fixed `today`.
- Takes the write lock first with `BEGIN IMMEDIATE`, then does the demo-user check inside that same transaction. Because the lock is held, a second process cannot insert between the check and the insert; it waits (default 5 second timeout) and then finds the user already there.
- Guard: if a user with email `demo@spendly.com` already exists, commit/rollback the empty transaction and return without inserting anything. No exception is raised.
- On any error the whole transaction is rolled back, so there is never partial data.
- Inserts one demo user:
  - name: `Demo User`
  - email: `demo@spendly.com`
  - password: `demo123`, stored only as a hash from `werkzeug.security.generate_password_hash`
- Gets rows from `_demo_expenses(today)` and inserts them one at a time with a parameterized `execute()` in a loop (not `executemany`), so a failure on any single row is reproducible and the rollback is testable.

| Day of month | Category | Amount | Description |
| --- | --- | --- | --- |
| 1 | Food | 450.00 | Weekly groceries |
| 3 | Transport | 120.00 | Metro card recharge |
| 5 | Bills | 1800.00 | Electricity bill |
| 8 | Health | 650.00 | Pharmacy |
| 12 | Entertainment | 499.00 | Streaming subscription |
| 15 | Shopping | 2299.00 | Headphones |
| 18 | Other | 300.00 | Gift |
| 22 | Food | 380.00 | Dinner with friends |

Every category in section 10 appears at least once (Food twice).

---

## 6. Changes to `app.py`

- Import `init_db` and `seed_db` (and `get_db` if routes already use it).
- Add a function:

  ```python
  def startup():
      with app.app_context():
          init_db()
          if os.environ.get("SPENDLY_ENV") != "production":
              seed_db()
  ```

- Call `startup()` once at module level, right after `app` is created and before routes are served. Do not put it inside `if __name__ == "__main__":`, because `flask run` imports the module and never executes that block.
- The app must not start serving requests until `startup()` has finished.
- Under the Werkzeug debug reloader, the module is imported twice, so `startup()` runs twice. This is harmless because both calls are idempotent (AC-2).

---

## 7. Files to Change

- `database/db.py`: implement the functions in section 5.
- `app.py`: add imports and `startup()`.
- `.gitignore`: add `spendly.db` (and `*.db`).

## 8. Files to Create

- `tests/conftest.py`: fixture that points `SPENDLY_DB` at a temporary file for each test. It must set the variable before `app` is first imported.
- `tests/test_database.py`: the tests in section 14.
- `requirements-dev.txt`: contains `pytest`.

---

## 9. Dependencies

- No new runtime packages.
- Runtime uses `sqlite3` (standard library) and `werkzeug.security` (already installed).
- `pytest` is a development-only dependency.

---

## 10. Categories (Fixed List)

Use exactly these values, with this spelling and capitalization:

- Food
- Transport
- Bills
- Health
- Entertainment
- Shopping
- Other

---

## 11. Rules for Implementation

- No ORMs (no SQLAlchemy).
- Parameterized queries only. Never build SQL with string formatting or concatenation. (The fixed schema SQL in section 4 is the only multi-statement SQL and contains no user input.)
- `PRAGMA foreign_keys = ON` on every connection.
- `amount` is stored as REAL. Round to 2 decimals (`round(value, 2)`) before writing and when displaying.
- Passwords are hashed with:

  ```python
  from werkzeug.security import generate_password_hash
  ```

- `seed_db()` must never create duplicate rows and must never raise because another process seeded first.
- Dates are always `YYYY-MM-DD`. Seed dates come from the injected or UTC `today`, never from a second clock read.
- Demo data must never be seeded when `SPENDLY_ENV=production`.
- Never print or log password hashes or passwords.

---

## 12. Expected Behavior

- `get_db()` returns a working connection with dictionary-like row access (`row["email"]`) and foreign keys enforced.
- `init_db()` creates the schema safely and does nothing on repeated runs.
- `seed_db()` inserts the demo user and 8 expenses once, and does nothing on later runs, including when two processes start together.
- The database itself enforces: ASCII case-insensitive unique email, valid foreign keys, positive amounts, the fixed categories, real calendar dates, non-blank names, and cascade delete of a user's expenses.

---

## 13. Error Handling Expectations

| Action | Required result |
| --- | --- |
| Insert a user with an existing email differing only in ASCII letter case | `sqlite3.IntegrityError` |
| Insert an expense with a `user_id` that does not exist | `sqlite3.IntegrityError` |
| Insert an expense with `amount <= 0` | `sqlite3.IntegrityError` |
| Insert an expense with a category outside the fixed list | `sqlite3.IntegrityError` |
| Insert an expense with an invalid date such as `2026-02-30`, `2026-04-31`, `2026-13-01`, `20-10-2026` or `2026-02-28 10:00` | `sqlite3.IntegrityError` |
| Insert a user whose name is empty or only spaces, tabs or newlines | `sqlite3.IntegrityError` |
| Delete a user who has expenses | Their expenses are deleted too |
| Seed fails halfway | Transaction rolled back; database unchanged |
| `seed_db()` called when the demo user already exists | Returns quietly, no exception |

Do not catch and hide these errors inside `db.py`; let them propagate so callers and tests can see them.

---

## 14. Acceptance Criteria and Tests

Each criterion is one test in `tests/test_database.py`. Tests use a temporary database file via `SPENDLY_DB`, never the real `spendly.db`. Tests that seed pass a fixed `today` (for example `date(2026, 10, 20)`).

- **AC-1** Given no database file, when `init_db()` runs, then the file exists with tables `users` and `expenses` and the index `idx_expenses_user_date`.
- **AC-2** Given an initialized database, when `init_db()` and `seed_db(today)` run twice more, then there is exactly 1 user and 8 expenses.
- **AC-3** Given `seed_db(date(2026, 10, 20))`, then all 7 categories appear at least once and the dates are exactly `2026-10-01, 03, 05, 08, 12, 15, 18, 22`.
- **AC-4** Given the demo user, then `password_hash` is not `demo123` and `check_password_hash(hash, "demo123")` is true.
- **AC-5** Given a user with email `demo@spendly.com`, when a user with `DEMO@SPENDLY.COM` is inserted, then `IntegrityError` is raised.
- **AC-6** Given a `user_id` that does not exist, when an expense is inserted, then `IntegrityError` is raised.
- **AC-7** Given invalid expenses (amount 0, negative amount, category `Groceries`), when each is inserted, then each raises `IntegrityError`.
- **AC-8** Given `get_db()`, then `PRAGMA foreign_keys` returns 1 and a row can be read by column name.
- **AC-9** Given a user with expenses, when the user is deleted, then no expenses remain for that user.
- **AC-10** Given `db._demo_expenses` is monkeypatched to return 8 rows where the 5th has amount `0`, when `seed_db(today)` runs, then `IntegrityError` propagates and the database contains 0 users and 0 expenses.
- **AC-11** Given `SPENDLY_DB` pointing at a temp file, when tests run, then the real project `spendly.db` is not created or modified.
- **AC-12** Given `SPENDLY_DB` is a fresh temp file and `SPENDLY_ENV=production` (monkeypatched), when `app.startup()` is called, then the schema exists and the demo user does not.
- **AC-13** Given names `""`, `"   "`, and `"\t\n"`, when each is inserted as a user name, then each raises `IntegrityError`.
- **AC-14** Given dates `2026-02-30`, `2026-04-31`, `2026-13-01`, `20-10-2026`, `2026-1-5` and `2026-02-28 10:00`, when each is inserted, then each raises `IntegrityError`; and `2026-02-28` and `2028-02-29` are accepted.
- **AC-15** Given the demo user already exists (inserted by a separate connection), when `seed_db(today)` runs, then it returns without raising and the counts are unchanged.

---

## 15. Definition of Done

- [ ] `spendly.db` is created on app startup in the project root
- [ ] Both tables and the index exist with the constraints in section 4
- [ ] Demo user exists with a hashed password (outside production)
- [ ] The 8 sample expenses exist and cover all 7 categories
- [ ] Running startup repeatedly creates no duplicate data
- [ ] The app starts with both `flask run` and `python app.py`
- [ ] Foreign key enforcement and cascade delete work
- [ ] All SQL with variable data is parameterized
- [ ] All tests AC-1 to AC-15 pass with `pytest -q`
- [ ] `spendly.db` is in `.gitignore`

---

## 16. Workflow for This Step (Spec -> Review -> Design -> Review -> Tasks -> Build -> Validate)

1. `git pull origin main`, then `git checkout -b feature/database-setup`
2. Spec: this file.
3. Review: new Claude Code session, "review `@.claude/specs/01-database-setup.md` as a skeptic; list gaps and contradictions".
4. Design: plan mode; note the choices in `DESIGN.md` (short).
5. Review: check the design against this spec.
6. Tasks: `TASKS.md`, one task per function plus the tests.
7. Build: write the test for a task first, then the code; one commit per task.
8. Validate: `pytest -q`, start the app, open `spendly.db` and check the rows by hand.
9. `git push -u origin feature/database-setup`, open and merge the PR, delete the branch, switch back to main.

---

## 17. Changes from v2

| v2 | v3 |
| --- | --- |
| Concern that `date()` accepts `2026-02-30` | Tested: it normalizes to `2026-03-02`, so `date(date) = date` rejects it. CHECK kept, reasoning documented, AC-14 added |
| Demo-user check separate from insert | Check runs inside `BEGIN IMMEDIATE`; a losing process returns quietly (AC-15) |
| `executemany`, so AC-10 could not fail on row 5 | Row source `_demo_expenses(today)` plus a per-row `execute()` loop; AC-10 injects a real bad row |
| Startup in `if __name__` / untestable | `startup()` function called at module level, works with `flask run`; AC-12 calls it directly |
| `trim(name)` strips spaces only | Explicit space, tab, newline, carriage return list; AC-13 |
| Seed date from an unspecified clock | `seed_db(today=None)`, default UTC date, tests inject a fixed date; AC-3 asserts exact dates |
| NOCASE scope unstated | Documented as ASCII only; signup step must lowercase emails |
| Reloader double-run unstated | One-line note in section 6 |