# Tasks: Step 6 — Add Expense Backend

Companion to `06-add-expense-backend.md` (spec) and `06-add-expense-backend.design.md` (design). Planning only; no code here.

**How to work through this list**
- Do the tasks in order. T0 to T4 are one commit each. T5 (validate) has no commit of its own, only one commit per fix batch I approve. T6 is a read-only sweep with no commit.
- Red, then green: write the listed tests, run them and see them fail, write the code, run them and see them pass, then run the full suite.
- All new tests go in `tests/test_add_expense.py`, named `test_..._acN` as in design §5, with the local helpers from design §5 (`_make_user`, `login_as`, `_rows`, `_valid_form`, `_today`) copied from the `tests/test_profile.py` pattern. `conftest.py` is not changed.
- Tests use only the `spendly_test` database through the existing fixtures. Never print, echo or hard-code `DATABASE_URL`, `SPENDLY_TEST_DATABASE_URL`, a password from the environment or any secret. The only passwords in tests are throwaway literals such as `"password123"` passed to `generate_password_hash`.
- Route tests assert the status code first, so a test cannot pass by accident against the old GET-only placeholder (which answers `POST` with 405).
- Test counts: the baseline is **192** collected. AC-5 is one parametrised test with 17 cases; every other AC is one test. Step 6 adds 43, so the planned count after T4 is **235**. The 17 is checked against the spec in T0; if it differs, the spec wins and every expected count here is corrected. T5 may add tests, which raises T6's count. Check with `.venv/bin/pytest --collect-only -q | tail -1`.
- Before the first full run of each task, and again after it, run `shasum spendly.db` (if the file exists). The two hashes must match.
- Commit messages follow the repo's `type: summary` style. The `Co-Authored-By` trailer is added at commit time.

**Mutation check for guard tests** (a test that passes on its first run). Every time:
1. Apply the one-off mutation named in the task.
2. Run the named test and see it go red.
3. Delete bytecode before reverting: `find . -name __pycache__ -not -path './.venv/*' -exec rm -rf {} +`
4. Revert the mutation by hand (undo exactly that edit). Do not use `git checkout` on a file that holds the task's uncommitted work.
5. Run the test again and see it go green. `git diff` must show no trace of the mutation. Never commit a mutation.

---

## T0: expense constants and pure validation helpers

**Model:** Opus (validation).

First run `git branch --show-current`; stop if it says `main`.

**ACs:** AC-5, AC-6, AC-7, AC-8, AC-9, AC-10, AC-11, AC-25.

**Files:** `app.py`, `tests/test_add_expense.py` (new).

**Red:**
- Create `tests/test_add_expense.py` with the helpers and the eight pure tests: `test_invalid_amount_format_ac5` (parametrised over the 17 amounts in AC-5), `test_amount_bounds_ac6`, `test_category_ac7`, `test_date_rules_ac8`, `test_date_year_rollover_ac9`, `test_description_length_ac10`, `test_check_order_ac11`, `test_clean_expense_ac25` (werkzeug `MultiDict`). Import `clean_expense` and `validate_expense` from `app`. Pure tests pass `today` explicitly and never call the clock.
- `.venv/bin/pytest tests/test_add_expense.py -q`: the import fails and the file errors at collection. That is the red.

**Check the AC-5 cases against the spec** (right after the red run, before any app code). Keep the AC-5 values in a module-level list `AC5_AMOUNTS` that the parametrise uses. Because the file cannot be imported yet, read the list with `ast` instead of collecting:

```bash
.venv/bin/python3 - <<'PY'
import ast, re
src = open("tests/test_add_expense.py", encoding="utf-8").read()
node = next(n for n in ast.walk(ast.parse(src))
            if isinstance(n, ast.Assign) and getattr(n.targets[0], "id", "") == "AC5_AMOUNTS")
plan = eval(compile(ast.Expression(node.value), "AC5_AMOUNTS", "eval"))
spec_line = next(l for l in open(".claude/specs/06-add-expense-backend.md", encoding="utf-8")
                 if l.startswith("- **AC-5**"))
spec = [eval(m) for m in re.findall(r'`("[^`]*"(?: \* \d+)?)`', spec_line.split("is each of", 1)[1])
        if not m.startswith('"Enter')]
print("test:", len(plan), [repr(v) for v in plan])
print("spec:", len(spec), [repr(v) for v in spec])
print("only in test:", [repr(v) for v in plan if v not in spec])
print("only in spec:", [repr(v) for v in spec if v not in plan])
PY
```

- Both lists must be equal, with no entries only in one. If they differ, fix `AC5_AMOUNTS` to match the spec. Never edit the spec.
- If the spec's count N is not 17, correct this plan to match: every expected count from T0 onward shifts by N − 17 (T0 216, T1 218, T2 232, T3 235, T4 235, plus T5 and T6), and so do the header's 43 and 235. Never change the spec to fit the plan.

**Green:**
- `app.py`: add the `re`, `unicodedata`, `date` and `timedelta` imports; add `CATEGORIES`, `MAX_AMOUNT`, `MIN_EXPENSE_DATE`, `MAX_DESCRIPTION`, `_AMOUNT_RE`, `_DATE_RE` after `_DUMMY_PASSWORD_HASH` (design §1); add `clean_expense(form)` and `validate_expense(amount, category, date, description, today)` above the add-expense placeholder, with the check order and messages of design §2 and the description rule of design §3. Use `[0-9]` and `fullmatch`, `Decimal` and never `float`, and `datetime.strptime(date, "%Y-%m-%d").date()` after the regex (design C5; flag R6 for review). The route is not touched.
- `.venv/bin/pytest tests/test_add_expense.py -q`, then `.venv/bin/pytest -q`.

**Expected count:** 192 + 24 = **216**.

**Commit:** `feat: add expense validation helpers`

Do not commit until I have reviewed the diff.

---

## T1: `create_expense()` in db.py

**Model:** Sonnet.

First run `git branch --show-current`; stop if it says `main`.

**ACs:** AC-23, AC-24.

**Files:** `database/db.py`, `tests/test_add_expense.py`.

**Red:**
- Add `create_expense` to the `database.db` import in the test file, and add `test_create_expense_roundtrip_ac23` and `test_create_expense_constraints_ac24`. Both use the `client` fixture or call `init_db()` first (design C4). AC-24 uses `pytest.raises(psycopg.errors.CheckViolation)` for `Decimal("0")` and `"Groceries"`, `pytest.raises(psycopg.errors.ForeignKeyViolation)` for an unknown `user_id`, and then checks that `expenses` is empty.
- `.venv/bin/pytest tests/test_add_expense.py -q`: the import fails, so the whole file errors (the T0 tests included). That is the red.

**Green:**
- `database/db.py`: add `from decimal import Decimal`, and add `create_expense(user_id, amount, category, date, description) -> int` after `create_user()`, exactly as in design §1. It is one parameterised `INSERT ... RETURNING id` inside `with closing(get_db()) as conn:`, with no `conn.transaction()`, no `try` and no validation.
- `.venv/bin/pytest tests/test_add_expense.py -q`, then `.venv/bin/pytest -q`.

**Expected count:** 216 + 2 = **218**.

**Commit:** `feat: add create_expense to db`

Do not commit until I have reviewed the diff.

---

## T2: the `/expenses/add` route

**Model:** Opus (the route, security-sensitive).

First run `git branch --show-current`; stop if it says `main`.

**ACs:** AC-1, AC-2, AC-3, AC-4, AC-12, AC-13, AC-14, AC-15, AC-18, AC-19, AC-20, AC-21, AC-22, AC-27.

**Files:** `app.py`, `tests/test_add_expense.py`.

**Red:**
- Add the 14 route tests from design §5. The valid form uses `date=_today()` (UTC). AC-21 monkeypatches `app.create_expense` to raise `psycopg.errors.ForeignKeyViolation("x")` (design R5). AC-22 asserts the status (303, then 400) before `"Set-Cookie" not in resp.headers`. AC-27 covers all six descriptions plus the `"Lunch\n"` case.
- `.venv/bin/pytest tests/test_add_expense.py -q`: 13 of the new tests fail, because the old placeholder is public and GET-only and returns the old text.
- **Guard that passes on the first run:** `test_other_methods_405_ac19`, because the old placeholder is already GET-only. Mutation, applied after green: change the route's `methods=["GET", "POST"]` to `methods=["GET", "POST", "PUT", "DELETE"]`, and AC-19 goes red. Then follow the mutation steps above.

**Green:**
- `app.py`: replace the placeholder and move it just after `profile()` (design §1, C1). Use `@app.route("/expenses/add", methods=["GET", "POST"])` with `@login_required` below it, and keep the endpoint name `add_expense` (C2). Follow design §4: GET returns `"Add expense form — coming in Step 7"`. POST runs `clean_expense(request.form)`, then `validate_expense(..., today=datetime.now(timezone.utc).date())`. An error returns `error, 400, {"Content-Type": "text/plain; charset=utf-8"}`. Success calls `create_expense(g.current_user["id"], **values)`, catching only `psycopg.errors.ForeignKeyViolation` (which runs `session.clear()` and redirects to `login`), and then returns `redirect(url_for("profile"), code=303)`. The route never reads `session[...]` and never writes the session on the success or 400 paths.
- `.venv/bin/pytest tests/test_add_expense.py -q`, then `.venv/bin/pytest -q`. The existing `test_profile_nav_and_add_expense_links_ac20` must still pass unchanged.
- **Mutations for guard assertions** (these only become meaningful once the route exists, so run them after green):
  - AC-13: make the error return `f"{error} {amount}"`. AC-13 goes red.
  - AC-14: pass `request.form.get("user_id", g.current_user["id"])` as the owner. AC-14 goes red.
  - AC-22: add `session["touched"] = 1` before the 303. AC-22 goes red.
  - AC-27: delete the control-character check in `validate_expense`. AC-27 goes red, and `\x00` should show up as a 500.

**Expected count:** 218 + 14 = **232**.

**Commit:** `feat: handle POST /expenses/add behind login`

Do not commit until I have reviewed the diff.

---

## T3: profile and end-to-end tests

**Model:** Sonnet.

First run `git branch --show-current`; stop if it says `main`.

**ACs:** AC-16, AC-17, AC-26.

**Files:** `tests/test_add_expense.py`.

**Red:** none expected. All three tests are guards over code that already exists (T2 plus Step 4), so they should pass on the first run. Each one is proven able to fail with a mutation, using the steps above:
- `test_profile_totals_exact_ac16` (`0.10` Food + `0.20` Transport, so `₹0.30`, `2 expenses`, both categories, both descriptions). Mutation: in the route, call `create_expense(g.current_user["id"], **{**values, "category": "Food"})`. Transport disappears from the profile, and the test goes red.
- `test_description_escaped_on_profile_ac17`. Mutation: in `templates/profile.html`, add `|safe` to the recent-expense description output. The raw `<script>` appears, and the test goes red.
- `test_end_to_end_login_add_profile_ac26` (sign in through `POST /login` with `create_user` + `generate_password_hash("password123")`, post the form, `follow_redirects=True`). Mutation: change the success redirect to `redirect("/", code=303)`. The final page no longer lists the expense, and the test goes red.

**Green:** no app code changes. Run `.venv/bin/pytest tests/test_add_expense.py -q`, then `.venv/bin/pytest -q`.

**Expected count:** 232 + 3 = **235**.

**Commit:** `test: cover add expense on profile and end to end`

Do not commit until I have reviewed the diff.

---

## T4: CLAUDE.md docs

**Model:** Sonnet.

First run `git branch --show-current`; stop if it says `main`.

**ACs:** none (Definition of done: the CLAUDE.md items).

**Files:** `CLAUDE.md`.

**Red/green:** docs only, so there are no tests.
- In the Architecture `app.py` bullet, change the placeholder example to an edit/delete one (C3), and add an `/expenses/add` (Step 6) entry: GET placeholder `"Add expense form — coming in Step 7"`; POST behind `@login_required`; `clean_expense` and `validate_expense` (order, messages, the constants `CATEGORIES`, `MAX_AMOUNT`, `MIN_EXPENSE_DATE`, `MAX_DESCRIPTION`, `[0-9]` with `fullmatch`, no `float`, the `Cc` rule); a plain-text 400 that never echoes input; a 303 to `/profile`; `ForeignKeyViolation` clears the session and redirects to `/login`; the owner is always `g.current_user["id"]`.
- In the `database/db.py` bullet, document `create_expense()`: its signature, `int` return, no validation, and that `CheckViolation` and `ForeignKeyViolation` propagate.
- In the Sessions known gaps: only `/expenses/<id>/edit` and `/expenses/<id>/delete` stay public placeholders (until Steps 8-9). `POST /expenses/add` has no CSRF token yet, only `SameSite=Lax`. CSRF is deferred to Step 7, which must add a token with acceptance criteria for a missing, a wrong and a valid token. **Do not deploy** (`SPENDLY_ENV=production` or any public host) before Step 7 ships it.
- No env values, URLs or passwords in the text.
- Verify: `.venv/bin/pytest --collect-only -q | tail -1` still shows **235**, and `grep -n "CSRF\|Step 7\|create_expense" CLAUDE.md` shows the new lines.

**Expected count:** **235** (unchanged).

**Commit:** `docs: document add expense backend and CSRF gap`

Do not commit until I have reviewed the diff.

---

## T5: validate (no commit of its own)

**Model:** Opus (security and quality validation).

First run `git branch --show-current`; stop if it says `main`.

**ACs:** all of AC-1 to AC-27 (review and test coverage).

**Files:** none by default. A fix batch touches only the files its approved findings name.

**Steps:**
1. Run `/code-review-feature 06-add-expense-backend`. It reviews `git diff main...HEAD` plus any uncommitted work, using the security and quality reviewers. It is read-only. Stop and show me the combined findings.
2. Run `/test-feature 06-add-expense-backend`. Stop and show me the result.
3. Apply only the fixes I approve, in batches I name. For each batch:
   - First run `git branch --show-current`; stop if it says `main`.
   - Red first, where the fix can be tested: a failing test, then the fix, then `.venv/bin/pytest tests/test_add_expense.py -q` and `.venv/bin/pytest -q`. A new test that passes on its first run gets a mutation check (steps above).
   - Keep tests on `spendly_test` only. Never print or hard-code DB URLs, passwords or secrets.
   - One commit per batch, with a conventional message (`fix: ...`, `test: ...`, `docs: ...`).
   - Do not commit until I have reviewed the diff.
4. Tests added by `/test-feature` that I approve go in their own batch commit (`test: ...`). Ones I reject are removed before any commit.

**Expected count:** 235 + A, where A is the number of collected tests added in approved batches (0 if none). Record the actual number here when T5 ends. T6 uses it.

**Commit:** none of its own; one per approved fix batch.

Do not commit until I have reviewed the diff.

---

## T6: final read-only sweep (no commit)

**Model:** Opus (security-sensitive review).

First run `git branch --show-current`; stop if it says `main`.

**ACs:** all of AC-1 to AC-27 (confirmation only).

**Files:** none are edited. Read-only.

**Commands:**
- `shasum spendly.db` (if present), `.venv/bin/pytest -q`, then `shasum spendly.db` again. Expect all tests passing, a count of **235 + A** (A from T5), and identical hashes.
- `grep -nE "(SELECT|INSERT|UPDATE|DELETE)" app.py`: no SQL.
- `grep -n "float(" app.py database/db.py`: no float conversion of amounts.
- `grep -n "session\[" app.py`: no new reads outside `load_current_user`.
- `grep -n "_ac[0-9]*" tests/test_add_expense.py`: every AC from 1 to 27 appears exactly once.
- `git diff main...HEAD --stat`: only `app.py`, `database/db.py`, `tests/test_add_expense.py`, `CLAUDE.md` (plus the spec, design and tasks docs, and any files named by the fix batches approved in T5) changed.
- `git diff main...HEAD | grep -niE "postgresql://|password=|secret"`: no real URL, password or key.
- `git status`: clean (no leftover mutations or `__pycache__` noise tracked).
- List the manual checks from the spec's Definition of done (signed-out redirect, demo-user placeholder and link, devtools `fetch` POST, `amount=abc` 400) for me to run with `SPENDLY_SECRET_KEY=dev-only-value .venv/bin/python3 app.py`.
- Report the open review flags: R4 (`Cf` characters still stored) and R6 (`strptime` instead of `date.fromisoformat`).

**Expected count:** **235 + A** (A from T5).

**Commit:** none.

Do not commit until I have reviewed the diff.
