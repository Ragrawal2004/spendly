# Design: Database Setup (Spec 01, v3)

## Context

`.claude/specs/01-database-setup.md` (v3) is already highly prescriptive — it fixes the schema SQL, function list, and most of the implementation rules after two review passes. What's left to design is the handful of things the spec states as requirements but doesn't fully pin down mechanically: exact transaction/rollback handling inside `seed_db()`, how `get_db()`'s connection is configured so explicit `BEGIN IMMEDIATE` doesn't collide with Python's own transaction handling, and how `tests/conftest.py` guarantees isolation given that `app.py` runs `startup()` as a side effect of being imported.

Current repo state (confirmed via explore): `database/` is already a proper package (`__init__.py` exists), `database/db.py` is a stub, `app.py` has no DB wiring, `tests/` doesn't exist, no pytest config exists, `.gitignore` has `venv/` and `expense_tracker.db` (stale name) but not `spendly.db`, and `requirements.txt` already has `pytest==8.3.5` + `pytest-flask==1.3.0`. Per your choice, a separate `requirements-dev.txt` will still be created with those two pins, matching spec section 8 exactly even though it duplicates `requirements.txt`.

No code is written in this step — this is the design to carry into `TASKS.md`.

---

## 1. Function signatures (`database/db.py`)

```python
def get_db() -> sqlite3.Connection: ...

def init_db() -> None: ...

def _demo_expenses(today: date) -> list[tuple[str, float, str, str | None]]: ...
    # (category, amount, date_str, description)

def seed_db(today: date | None = None) -> None: ...
```

Key detail not spelled out in the spec: **path resolution must happen inside `get_db()` on every call**, never cached as a module-level constant. If `db.py` computed `DB_PATH = os.environ.get("SPENDLY_DB", default)` once at import time, a test's `monkeypatch.setenv("SPENDLY_DB", ...)` after that first import would be silently ignored — this is exactly the AC-11/AC-12 isolation the spec depends on. So:

```python
def _resolve_db_path() -> str:
    return os.environ.get("SPENDLY_DB") or os.path.join(
        os.path.dirname(__file__), "..", "spendly.db"
    )
```

called fresh inside `get_db()` only. `init_db()` and `seed_db()` never open connections directly — they always go through `get_db()`, so they automatically inherit this.

**Connection configuration in `get_db()`:**
- `row_factory = sqlite3.Row`
- `PRAGMA foreign_keys = ON`
- `conn.isolation_level = None` — this is the detail the spec's prose doesn't mention but the design needs: Python's `sqlite3` default (legacy) isolation mode auto-opens an implicit transaction before the first DML statement. `seed_db()` needs to issue its own `BEGIN IMMEDIATE` to take the write lock before the existence check (section 5D), and that only works reliably if the connection is in autocommit mode (`isolation_level = None`) so Python never tries to auto-begin one itself. Without this, `seed_db()` risks "cannot start a transaction within a transaction" under concurrent access.

---

## 2. Order of operations in `seed_db(today=None)`

```
1. today = today or datetime.now(timezone.utc).date()
2. conn = get_db()
3. try:
4.     conn.execute("BEGIN IMMEDIATE")        # takes the write lock; blocks (default 5s busy_timeout) if another process holds it
5.     exists = conn.execute(
6.         "SELECT 1 FROM users WHERE email = ?", ("demo@spendly.com",)
7.     ).fetchone()
8.     if exists:
9.         conn.commit()                       # release the lock on the no-op transaction; return quietly (AC-15)
10.        return
11.    password_hash = generate_password_hash("demo123")
12.    cur = conn.execute(
13.        "INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
14.        ("Demo User", "demo@spendly.com", password_hash),
15.    )
16.    user_id = cur.lastrowid
17.    for category, amount, date_str, description in _demo_expenses(today):
18.        conn.execute(
19.            "INSERT INTO expenses (user_id, amount, category, date, description) "
20.            "VALUES (?, ?, ?, ?, ?)",
21.            (user_id, round(amount, 2), category, date_str, description),
22.        )
23.    conn.commit()
24. except Exception:
25.    conn.rollback()
26.    raise
27. finally:
28.    conn.close()
```

This is what makes AC-10 work: the loop inserts rows one at a time via `execute()` (not `executemany()`), so when the test monkeypatches `_demo_expenses` to return a bad 5th row (`amount=0`), rows 1–4 insert successfully *inside the open transaction*, row 5 raises `IntegrityError` on its `CHECK (amount > 0)`, the `except` block rolls back the whole transaction (undoing rows 1–4 and the user insert too), then re-raises — leaving 0 users and 0 expenses, exactly as AC-10 requires.

---

## 3. Wiring `startup()` in `app.py`

```python
import os
from database.db import init_db, seed_db

app = Flask(__name__)

def startup():
    with app.app_context():
        init_db()
        if os.environ.get("SPENDLY_ENV") != "production":
            seed_db()

startup()   # module level, right after app is created, before route decorators
```

Both `init_db()`/`seed_db()` re-read `os.environ` fresh each call (no caching), so calling `startup()` again later — which AC-12 does explicitly, after `monkeypatch.setenv("SPENDLY_ENV", "production")` and pointing `SPENDLY_DB` at a new temp file — produces the correct result against the new target: schema created, no demo user. This only works because of the "no module-level caching" rule in section 1 above; it's the same mechanism, applied twice (once implicitly at import, once explicitly in the AC-12 test).

Works under both `flask run` (imports the module, never hits `if __name__ == "__main__"`) and `python app.py` (also imports the module first, then hits the `__main__` block to call `app.run()`), matching the spec's Definition-of-Done line "the app starts with both `flask run` and `python app.py`."

---

## 4. Test isolation (`tests/conftest.py`)

The subtlety: `app.py` runs `startup()` as an import side effect. The *first* time anything imports `app` (which could be pytest's own collection, or the first test module), that automatic call must not touch the real `spendly.db`. Design:

```python
# tests/conftest.py — module level, runs before any test file is collected/imported
import os, tempfile

os.environ.setdefault("SPENDLY_DB", tempfile.mkstemp(suffix=".db")[1])
```

This guarantees `SPENDLY_DB` is already pointed at a throwaway file *before* pytest imports `app.py` for the first time (satisfying AC-11 unconditionally, regardless of import order).

Then a function-scoped autouse fixture gives each test its own clean file:

```python
import pytest

@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    db_path = tmp_path / "test.db"
    monkeypatch.setenv("SPENDLY_DB", str(db_path))
    yield db_path
```

Because `get_db()` resolves the path fresh on every call (section 1), each test transparently gets a fresh, empty SQLite file the moment it calls `init_db()`/`seed_db()`/`get_db()` directly — no need to reimport `database.db` or `app` per test. Most tests (AC-1–AC-11, AC-13–AC-15) call `database.db` functions directly against this per-test file. Only AC-12 needs to re-invoke `app.startup()` itself (with `SPENDLY_ENV` also monkeypatched to `"production"`), which is safe for the reasons in section 3.

---

## Files touched

- `database/db.py` — implement `get_db`, `init_db`, `_demo_expenses`, `seed_db` per sections 1–2 above.
- `app.py` — add `startup()` and the module-level call per section 3.
- `.gitignore` — append `spendly.db` and `*.db` (existing `expense_tracker.db` line left as-is; `*.db` covers it going forward).
- `tests/conftest.py` — new, per section 4.
- `tests/test_database.py` — new, AC-1 through AC-15.
- `requirements-dev.txt` — new: `pytest==8.3.5` / `pytest-flask==1.3.0` (matches versions already pinned in `requirements.txt`, per your choice to follow spec section 8 literally).

## Verification

- `pytest -q` — all AC-1…AC-15 pass.
- `python app.py`, then separately `flask run` — both start without error, create `spendly.db` in the project root, and it contains the demo user + 8 expenses (`sqlite3 spendly.db "select * from users; select * from expenses;"`).
- Re-run `python app.py` a second time — row counts unchanged (idempotency, AC-2's premise extended to real startup).
- `SPENDLY_ENV=production python app.py` — schema exists, demo user does not.
