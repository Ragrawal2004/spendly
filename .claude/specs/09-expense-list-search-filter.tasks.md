# Tasks: Step 9 — Expense List with Search and Filter

Companion to `09-expense-list-search-filter.md` (spec) and `09-expense-list-search-filter.design.md` (design). This file is only the plan. It has no code, and the spec and design are not edited.

**How to work through this list**
- Run the tasks in this order: **1 → 2 → 3a → 3b → 3c → 4 → 5 → V → S → Ship**. Tasks 1 to 5 are design §8 tasks 1 to 5 under the same numbers. S carries out design §8 task 6 (the Definition of done).
- Tasks 1 to 5 are one commit each, with a conventional message (`type: summary`). The `Co-Authored-By` trailer is added at commit time. V has no commit of its own, only one commit per fix batch I approve. S and Ship make no commits.
- Every task starts with `git branch --show-current`; stop if it says `main`.
- Red, then green. Write the listed tests, run them and watch them fail for the stated reason, write the code, run them and watch them pass, then run the full suite.
- **Built up in stages.** The `expense_list` view reaches its final design §1 form over 3a, 3b and 3c, so each group starts red. A test that passes on its first run is a **guard test** and gets a mutation check. A test that passes early only because an earlier stage ignores a parameter (AC-10, 14, 19 and 31 in 3b; AC-22 and 26 in 3c) is proven with a mutation in the stage where its feature lands, never earlier.
- All new tests go in `tests/test_expense_list.py`, named exactly as in design §5, one test per AC, with no `parametrize`. Looping ACs (AC-10, 14, 19, 21, 26) use a plain `for` loop with the value in each assert message (`f"page={value!r}"`). The file does `import app` at module top. `tests/conftest.py`, `tests/helpers.py` and every existing test file are never changed. Check at the end of each task that `git diff main --stat -- tests/` lists only `tests/test_expense_list.py`.
- **Local helpers** in the new file, written in task 1 and extended as needed: `_make_user(email=...)` (`create_user` with `generate_password_hash("password123")`), `login_as(client, uid)` (sets `session["user_id"]`, then calls `csrf_token(client)` from `helpers`), `_add(uid, amount="100.00", category="Food", day="2026-03-01", description=None)` (`create_expense` with `Decimal` and `date.fromisoformat`, returns the id), `_rows()`, `_text(body)` (tags stripped, `html.unescape`, whitespace collapsed to single spaces), `_listed(body)` (the `<bdi>` texts inside `<tbody>`, in order, unescaped), `_link(body, label)` (the unescaped `href` of the `<a>` whose text is `label`, or `None`), `_query(href)` (`parse_qs` of the query string, `keep_blank_values=True`), `_empty_block(body)` (`<div class="empty-state">(.*?)</div>`, DOTALL), `_input_value(body, name)` and `_selected_option(body)`.
- Requests whose values contain `%`, `&`, `#`, `+`, `<`, `>`, `\`, quotes, spaces, non-ASCII or control characters use `client.get("/expenses", query_string={...})`. Backslash values are raw strings (`r"C:\temp"`), and control characters are Python escapes (`"a\x00b"`, `"\x7f"`, `"\u202e"`), never literal characters in the source.
- **Secrets:** tests use only `spendly_test` through the existing fixtures. Never print, echo or hard-code `DATABASE_URL`, `SPENDLY_TEST_DATABASE_URL`, a password from the environment or a CSRF token. Never run pytest with `-l`/`--showlocals` or `-s`, and never add `print` to a test or to app code.
- **`spendly.db`:** before the first full run of each task and again after it, run `shasum spendly.db`. The two hashes must match.
- **Counts:** the baseline is **273** collected (checked at planning time with `.venv/bin/pytest --collect-only -q | tail -1`). The planned counts are 1: 275, 2: 277, 3a: 285, 3b: 301, 3c: 309, 4: 309, 5: 309. V may add tests (A of them), which moves S and Ship to 309 + A.
- **`expense-tracker-frontend/`** is never read, modified or staged.

**Mutation check** (for every guard test, and for the listed property checks). Every time:
1. Save the current diff: `git diff > "$SCRATCH/pre-mutation.diff"`, where `$SCRATCH` is the session scratchpad directory. Also record the hash of the file about to be mutated: `shasum <file> > "$SCRATCH/pre-mutation.sha"`.
2. Apply exactly the one mutation named in the task, by hand.
3. Delete bytecode right away: `find . -name __pycache__ -not -path './.venv/*' -not -path './expense-tracker-frontend/*' -exec rm -rf {} +`
4. Run the named test and watch it go red for the stated reason: `.venv/bin/pytest -q tests/test_expense_list.py::<test>`.
5. Delete bytecode again (same command) before reverting.
6. Revert the mutation by hand (undo exactly that edit). Never use `git checkout`, `git restore` or `git stash` on a file that holds the task's uncommitted work.
7. Run the test again and watch it go green. `git diff | cmp - "$SCRATCH/pre-mutation.diff"` must report no difference, and `shasum -c "$SCRATCH/pre-mutation.sha"` must print `OK`, so the mutation leaves no trace. Both checks are needed: `git diff` does not show untracked files, so a mutation left behind in a new file (for example `templates/expenses.html` in task 3a, or `tests/test_expense_list.py` before its first commit) would pass the diff comparison unseen. Never commit a mutation.

---

## Task 1: filtered reads in `database/db.py`

**Model:** Opus (SQL, `LIKE` escaping, per-user filtering).

First run `git branch --show-current`; stop if it says `main`.

**ACs:** AC-23, AC-36.

**Files:** `database/db.py`, `tests/test_expense_list.py` (new).

**Red:**
- Create `tests/test_expense_list.py` with `import app` at the top, the local helpers from the header, and `from database.db import _like_pattern, create_expense, create_user, get_db, get_filtered_summary`.
- `test_filtered_summary_types_ac23`: user A has `0.10` and `0.20`, and user B has `5.00`. `get_filtered_summary(a, None, None, None, None)` gives `count == 2` with `type(...) is int`, and `total == Decimal("0.30")` with `isinstance(..., Decimal)`. With `category="Bills"` it gives `count == 0` and `total == Decimal("0")`, which is still a `Decimal`.
- `test_like_pattern_ac36`: `_like_pattern(r"50%_\x") == r"%50\%\_\\x%"`.
- Run `.venv/bin/pytest -q tests/test_expense_list.py`. **Expected red:** a collection error, `ImportError: cannot import name '_like_pattern'` (or `get_filtered_summary`) `from 'database.db'`, so both tests error.

**Green** (design §2):
- After `get_recent_expenses` and before `_DEMO_EXPENSES_TABLE`, add `_EXPENSE_FILTER`, `_FILTERED_SUMMARY_SQL`, `_FILTERED_EXPENSES_SQL`, `_like_pattern`, `_filter_params`, `get_filtered_summary` and `get_filtered_expenses`, exactly as in design §2. No new import (`date` is already imported at `db.py:3`). `_SCHEMA`, `init_db` and `seed_db` are not touched.
- The SQL text is fixed: string literals joined once at import time, named placeholders only, and `ESCAPE '\\'` in Python, which reaches PostgreSQL as `'\'`.

**Guard tests:** none. Both tests start red.

**Property checks** (the tests went red on the import, not on the property, so prove the property):
- AC-23, the user filter: in `_EXPENSE_FILTER`, change `"WHERE user_id = %(user_id)s "` to `"WHERE %(user_id)s::bigint IS NOT NULL "`. AC-23 goes red (count 3, B's row counted). Revert.
- AC-36, escape order: in `_like_pattern`, move `.replace("\\", "\\\\")` to the end of the chain. AC-36 goes red (the escapes for `%` and `_` get doubled). Revert.

**Commands:**
```bash
shasum spendly.db; .venv/bin/pytest -q; shasum spendly.db
.venv/bin/pytest --collect-only -q | tail -1                       # 275
grep -n "execute(f" database/db.py                                  # nothing
git diff -- database/db.py | grep -nE '^[-+].*(_SCHEMA|def init_db|def seed_db)'   # nothing
git diff -- database/db.py | grep '^+' | grep -nE 'float\(|print\(|logging'        # nothing
```

**Expected count:** 273 + 2 = **275**.

**Commit:** `feat: add filtered expense reads with a shared filter clause`

Do not commit until I have reviewed the diff.

---

## Task 2: pure helpers in `app.py`

**Model:** Opus (the input gate for the SQL filters: the `Cc`/NUL guard on `q` prevents a 500, and `_PAGE_RE` bounds the offset).

First run `git branch --show-current`; stop if it says `main`.

**ACs:** AC-34, AC-35.

**Files:** `app.py`, `tests/test_expense_list.py`.

**Red:**
- Add `from app import clean_expense_filters, page_window` and `from werkzeug.datastructures import MultiDict`.
- `test_clean_expense_filters_ac34`: each case from the spec, and every result's `set(keys) == {"category", "date_from", "date_to", "q", "page"}`. The cases are:
  - `MultiDict()`, which gives all `None` and page 1;
  - `MultiDict([("category", " Food "), ("category", "Bills")])`, which gives `"Food"`;
  - `date_from="2026-04-01"`, which gives `date(2026, 4, 1)`;
  - a `q` of 100 `"x"`s is kept, while 101 `"x"`s and `"a\x00b"` give `None`;
  - `page="3"` gives 3, while `"0"`, `"٣"` and `"1234567890"` give 1.
- `test_page_window_ac35`: the six cases from the spec, each compared with `==` against the full dict, so the key set is checked too.
- Run `.venv/bin/pytest -q tests/test_expense_list.py`. **Expected red:** a collection error, `ImportError: cannot import name 'clean_expense_filters' from 'app'`, so the whole file errors (task 1's tests included). That is expected.

**Green** (design §1):
- Under `_DATE_RE` (line 64), add `PAGE_SIZE = 20`, `MAX_SEARCH = 100` and `_PAGE_RE = re.compile(r"[0-9]{1,9}")`.
- After `add_expense()` and before the "Placeholder routes" banner, add `_filter_date`, `clean_expense_filters` and `page_window`, exactly as in design §1. No route yet.

**Guard tests:** none. Both tests start red.

**Property checks:**
- AC-34, the `Cc` guard: delete `or any(unicodedata.category(c) == "Cc" for c in q)`. AC-34 goes red (`"a\x00b"` is kept). Revert.
- AC-34, the ASCII page regex: change `_PAGE_RE` to `re.compile(r"\d{1,9}")`. AC-34 goes red (`"٣"` gives 3). Revert.
- AC-35, the clamp: in `page_window`, delete `page = min(max(page, 1), pages)`. AC-35 goes red (`(25, 99)` gives offset 1960). Revert.

**Commands:**
```bash
shasum spendly.db; .venv/bin/pytest -q; shasum spendly.db
.venv/bin/pytest --collect-only -q | tail -1                       # 277
git diff -- app.py | grep '^+' | grep -nE 'float\(|print\(|logging|request\.'   # nothing (pure helpers: no request)
```

**Expected count:** 275 + 2 = **277**.

**Commit:** `feat: add expense list filter and page helpers`

Do not commit until I have reviewed the diff.

---

## Task 3a: the view with no filters, the template and the nav link

**Model:** Opus (a new signed-in route: `login_required`, per-user reads, no-store, escaping).

First run `git branch --show-current`; stop if it says `main`.

**ACs:** AC-1 to AC-8.

**Files:** `app.py`, `templates/expenses.html` (new), `templates/base.html`, `tests/test_expense_list.py`.

**Red:**
- `test_signed_out_redirects_ac1`, `test_no_expenses_empty_state_ac2`, `test_rows_newest_first_ac3`, `test_only_own_rows_ac4`, `test_vanished_user_redirects_ac5`, `test_other_methods_405_ac6`, `test_nav_expenses_link_ac7` and `test_read_only_page_ac8`, written to the spec text. Notes:
  - **AC-2** looks for the `Add expense` link inside `_empty_block`, so the nav's `Add Expense` does not count. It asserts `"Set-Cookie" not in resp.headers` and `Cache-Control == "no-store"`.
  - **AC-4** checks only `_listed(body)` and `_text(body)` for `Showing … of Z` and `Total:`, never the whole body.
  - **AC-5** sets `user_id` to a deleted id with `session_transaction`.
  - **AC-6** uses `client.post`, `client.put` and `client.delete` with no token, checks `_rows()` is unchanged, and checks that `GET /expenses/` is a 404.
  - **AC-7** matches `<a\b[^>]*\bhref="/expenses"[^>]*>Expenses</a>`, never the bare word, because `profile.html` has an "Expenses" stat label.
  - **AC-8** finds forms with a `method="(GET|POST)"` regex (case-insensitive), checks there is no `name="csrf_token"` inside the GET form, and checks the option list is `["", *CATEGORIES]` with the first label `All categories`.
- Run `.venv/bin/pytest -q tests/test_expense_list.py`. **Expected red:** all eight fail, because `/expenses` has no route yet.
  - AC-1, AC-5 and AC-6 get 404 where they expect 302 or 405.
  - AC-2, AC-3, AC-4 and AC-8 get 404 where they expect 200.
  - AC-7 finds no link on `/profile`.

**Green** (design §1, §3, the 3a stage):
- `app.py`: add `get_filtered_expenses` and `get_filtered_summary` to the `database.db` import list (alphabetical, after `get_expense_summary`). Add `@app.route("/expenses")` and `@login_required` (below the route) on `expense_list`, after `page_window`. In this stage the view:
  - sets `filters = clean_expense_filters({})`, so query parameters are ignored until 3b;
  - builds `criteria` from `filters`;
  - calls `summary = get_filtered_summary(uid, *criteria)` and `pager = page_window(summary["count"], 1, PAGE_SIZE)`;
  - calls `get_filtered_expenses(uid, *criteria, PAGE_SIZE, pager["offset"])` only when the count is above 0;
  - sets `has_expenses = summary["count"] > 0`, with no second count yet;
  - passes `prev_url=None` and `next_url=None`;
  - returns through `no_store(render_template("expenses.html", ...))` with the template variables from design §1.

  `uid` comes only from `g.current_user["id"]`.
- `templates/expenses.html`: the full template from design §3, including the pagination block and the "no matches" empty state, which cannot be reached until 3b and 3c.
- `templates/base.html`: `<a href="{{ url_for('expense_list') }}" class="nav-expenses">Expenses</a>` on its own line directly above the `nav-add` link, signed-in branch only.
- Run the file's tests, then the full suite. `test_nav_add_expense_link_ac32`, `test_every_post_form_has_token_ac31` and `test_profile_nav_and_add_expense_links_ac20` must still pass unchanged.

**Guard tests:** none. All eight start red.

**Property checks** (these tests went red on the 404, so prove each property separately):
- AC-1, login gate: remove `@login_required` from `expense_list`. AC-1 goes red (500 or 200 instead of 302). Revert.
- AC-2, no-store: in `expense_list`, replace `return no_store(render_template(...))` with `return render_template(...)`. AC-2 goes red. Revert.
- AC-4, per-user reads: in the view, pass `request.args.get("user_id", type=int) or uid` instead of `uid` to `get_filtered_summary` and `get_filtered_expenses`. AC-4 goes red on `?user_id=<B>`. Revert.
- AC-8, no token in the GET form: add `<input type="hidden" name="csrf_token" value="{{ csrf_token() }}">` inside the filter form. AC-8 goes red. Revert.
- AC-3, the `<bdi>` cell: remove `<bdi>` and `</bdi>` from the description cell. AC-3 goes red. Revert.

**Commands:**
```bash
shasum spendly.db; .venv/bin/pytest -q; shasum spendly.db
.venv/bin/pytest --collect-only -q | tail -1                                          # 285
grep -nE '\|safe|Markup|autoescape false|style=|<style' templates/expenses.html        # nothing
git diff -- templates/base.html                                                       # one added line
sed -n '/def expense_list/,/^def \|^@app/p' app.py | grep -n 'session\|request.form'  # nothing
```

**Expected count:** 277 + 8 = **285**.

**Commit:** `feat: list all expenses on /expenses with a nav link`

Do not commit until I have reviewed the diff.

---

## Task 3b: filters, empty states and escaping

**Model:** Opus (search escaping, SQL filters, HTML escaping, injection strings).

First run `git branch --show-current`; stop if it says `main`.

**ACs:** AC-9 to AC-21, AC-31, AC-32, AC-33.

**Files:** `app.py`, `tests/test_expense_list.py`.

**Red:**
- `test_category_filter_ac9` to `test_injection_strings_harmless_ac21` (AC-9 to AC-21), `test_no_expenses_beats_no_match_ac31`, `test_no_match_empty_state_ac32` and `test_escaping_ac33`, written to the spec text. Notes:
  - **AC-17** creates `r"C:\temp"` and `r"100\%"`.
  - **AC-18** builds its 100-character description in the setup.
  - **AC-21** gives user B unique tokens such as `zq-b-7781`. It checks the `users` and `expenses` row counts and `to_regclass('public.expenses')` before and after, and that `<script>alert(1)` is absent from every body.
  - **AC-33** writes the bidi override as `\u202e`.
- Run `.venv/bin/pytest -q tests/test_expense_list.py`. **Expected red:** AC-9, 11, 12, 13, 15, 16, 17, 18, 20, 21, 32 and 33 fail, because the view still uses `clean_expense_filters({})`, so every filter is ignored and all rows are listed.
  - AC-13 and AC-32 see the table instead of `No expenses match these filters.`
  - AC-21 lists all of A's rows for `q=%`.
  - AC-33 finds an empty search `value`.
- **Early passes, not guards of 3a:** AC-10, AC-14, AC-19 and AC-31 pass on the first run, because 3a ignores every parameter. They are proven by the mutations below, after this task's code is in.

**Green** (design §1, the 3b stage):
- In `expense_list`, change `clean_expense_filters({})` to `clean_expense_filters(request.args)`.
- Add the `elif any(value is not None for value in criteria):` branch that sets `has_expenses` from `get_filtered_summary(uid, None, None, None, None)["count"] > 0`, with its comment from design §1.
- No template change (3a added the full template).

**Mutations for the early passes** (after green, the steps in the header):

| Test | How to apply | What must go red | How to revert |
|---|---|---|---|
| AC-10 `test_invalid_category_ignored_ac10` | In `clean_expense_filters`, change `category if category in CATEGORIES else None` to `category or None` | `food` and `Food' OR '1'='1` reach SQL and match nothing, so 0 rows instead of 3, and `All categories` is not selected | Restore `category if category in CATEGORIES else None` |
| AC-14 `test_invalid_dates_ignored_ac14` | In `_filter_date`, delete the two lines `if not _DATE_RE.fullmatch(value):` / `return None` | `strptime` accepts `2026-4-1` and `２０２６-04-01`, so the filter applies (3 rows, not 4) and the input's `value` is not empty | Re-add the two lines above the `try` |
| AC-19 `test_search_control_chars_ac19` | In `clean_expense_filters`, delete `or any(unicodedata.category(c) == "Cc" for c in q)` | `q="a\x00b"` reaches PostgreSQL and raises `DataError`, so 500 | Re-add the condition at the end of the `if` |
| AC-31 `test_no_expenses_beats_no_match_ac31` | In `expense_list`, replace `get_filtered_summary(uid, None, None, None, None)["count"] > 0` with `True` | A user with no expenses and active filters sees `No expenses match these filters.` | Restore the original expression |

**Property checks:**
- AC-16 and AC-17, literal search: in `_like_pattern`, delete `.replace("%", "\\%")`. AC-16 goes red (`500 rupees` and `Paid 50` match). AC-36 also goes red, which is expected. Revert.
- AC-33, escaping: change the search input to `value="{{ (filters["q"] or "")|safe }}"`. AC-33 goes red (raw `<b>x</b>`). Revert.

**Commands:**
```bash
shasum spendly.db; .venv/bin/pytest -q; shasum spendly.db
.venv/bin/pytest --collect-only -q | tail -1                                # 301
git diff -- app.py | grep '^+' | grep -nE 'request\.args'                   # only clean_expense_filters(request.args)
git diff -- app.py | grep '^+' | grep -nE 'print\(|logging|app\.logger'     # nothing
```

**Expected count:** 285 + 16 = **301**.

**Commit:** `feat: filter the expense list by category, dates and search`

Do not commit until I have reviewed the diff.

---

## Task 3c: totals and pagination

**Model:** Opus (URL building with user text, `&amp;` escaping, bounded offsets).

First run `git branch --show-current`; stop if it says `main`.

**ACs:** AC-22, AC-24 to AC-30.

**Files:** `app.py`, `tests/test_expense_list.py`.

**Red:**
- `test_total_covers_all_pages_ac22`, `test_first_page_ac24`, `test_last_page_ac25`, `test_invalid_page_ac26`, `test_page_clamped_ac27`, `test_twenty_rows_one_page_ac28`, `test_next_link_keeps_filters_ac29` and `test_next_link_drops_junk_ac30`, written to the spec text. Notes:
  - Link checks take the raw `href` for AC-29's `&amp;` assertion, then `html.unescape` and `_query(href)` for the dict comparison.
  - AC-24, AC-25 and AC-27 assert the listed rows with `_listed(body)`, not only the `Showing` text:
    - AC-24 checks that page 1 lists exactly the 20 newest descriptions, newest first;
    - AC-25 checks that `?page=2` lists exactly the 5 oldest, and that pages 1 and 2 together give the 25 distinct descriptions;
    - AC-27 checks that `?page=99` lists exactly the same 5 oldest.

    Without this, the AC-27 offset mutation below would stay green, because `Showing 21-25 of 25` comes from the clamped `pager` even when the rows are wrong.
- Run `.venv/bin/pytest -q tests/test_expense_list.py`. **Expected red:** AC-24, 25, 27, 28, 29 and 30 fail, because the view always uses page 1 and passes `next_url=None`.
  - AC-24, AC-28 (after the 21st row) and AC-29 find no Next link.
  - AC-25 and AC-27 see `Showing 1-20 of 25`.
  - AC-30 finds no Next link to compare.
- **Early passes, not guards of 3a/3b:** AC-22 passes, because the total has come from `get_filtered_summary` since 3a. AC-26 passes, because every page has been page 1 until now. Both are proven by the mutations below.

**Green** (design §1, the final view):
- Pass `filters["page"]` (instead of `1`) to `page_window`.
- Build `active` (category and `q` as-is, dates as `.isoformat()`, only when not `None`) and `prev_url` / `next_url` with `url_for("expense_list", page=..., **active)`, exactly as in design §1, with the D7 comment. Pass them to the template in place of the `None`s.
- The view now matches design §1 line for line. Diff it against the design by reading it.

**Mutations for the early passes:**

| Test | How to apply | What must go red | How to revert |
|---|---|---|---|
| AC-22 `test_total_covers_all_pages_ac22` | In `expense_list`, directly after the `expenses = get_filtered_expenses(...)` line, add `summary = dict(summary, total=sum((e["amount"] for e in expenses), Decimal("0")))` | The page shows the total of the first 20 rows only, not `Total: ₹25,234.60` | Delete the added line |
| AC-26 `test_invalid_page_ac26` | In `clean_expense_filters`, change `max(int(page), 1) if _PAGE_RE.fullmatch(page) else 1` to `int(page) if page else 1` | `page=abc` and `page=1.5` raise `ValueError` (500), and `page=٢` shows page 2 | Restore the original expression |

**Property checks:**
- AC-29, attribute escaping: change the Next link to `href="{{ next_url|safe }}"`. AC-29 goes red (bare `&`). Revert.
- AC-30, only effective filters: replace the `active = ...` block with `active = request.args.to_dict()` and `active.pop("page", None)`. AC-30 goes red (`user_id`, `foo` and `category=food` are carried). Revert.
- AC-27, the clamped offset is used: in the `get_filtered_expenses` call, change `pager["offset"]` to `(filters["page"] - 1) * PAGE_SIZE`. AC-27 goes red (`?page=99` lists no rows). Revert.

**Commands:**
```bash
shasum spendly.db; .venv/bin/pytest -q; shasum spendly.db
.venv/bin/pytest --collect-only -q | tail -1                                         # 309
grep -c "_ac[0-9]*(" tests/test_expense_list.py                                       # 36
grep -n "parametrize" tests/test_expense_list.py                                      # nothing
grep -nE 'query_string|request\.args' templates/expenses.html                         # nothing
git diff main --stat -- tests/                                                        # only tests/test_expense_list.py
```

**Expected count:** 301 + 8 = **309**.

**Commit:** `feat: paginate the expense list and show the filtered total`

Do not commit until I have reviewed the diff.

---

## Task 4: CSS

**Model:** Sonnet (CSS).

First run `git branch --show-current`; stop if it says `main`.

**ACs:** none (spec "Files to change" for `style.css`, design §4).

**Files:** `static/css/style.css`.

**Red/green:** CSS only, so there are no new tests. The full suite must stay at 309 and green.
- Apply design §4 rules 1 to 17, rule by rule, with existing variables only and no hex:
  - rules 1-2 group `.nav-expenses` with `.nav-add`;
  - rules 3-11 go in a new "Expense list" section after line 781;
  - rules 12-16 go in the `max-width: 600px` block;
  - rule 17 goes in the `min-width: 900px` block.

**Grep checks:**
```bash
grep -n "nav-expenses" static/css/style.css                                     # exactly 3 lines: rule 1, rule 2, the mobile rule (rule 12)
git diff HEAD -- static/ | grep '^+' | grep -nE '#[0-9a-fA-F]{3,8}\b'           # nothing (no new hex outside :root)
git diff HEAD -- templates/ | grep '^+' | grep -n 'style='                       # nothing
grep -n 'style=' templates/expenses.html templates/base.html                    # nothing
grep -o "var(--[a-z0-9-]*)" static/css/style.css | sort -u                      # each one defined in :root
shasum spendly.db; .venv/bin/pytest -q; shasum spendly.db
```

**Manual checks** (I run these; you list them and wait). Start the app with `SPENDLY_SECRET_KEY=dev-only-value .venv/bin/python3 app.py` and use the browser's device toolbar at **360px** wide. On every page check that:
- every nav item is visible or wrapped onto a second line;
- the navbar's bottom edge does not overlap the page content;
- there is no horizontal scroll.

The pages:
- [ ] `/` signed out (brand, "Get started") and signed in (Expenses, Add Expense, user name, Sign out)
- [ ] `/login` signed out; signed in it redirects to `/profile`, so check `/profile` instead
- [ ] `/register` signed out; signed in it redirects to `/profile`
- [ ] `/profile` signed in; signed out it redirects to `/login`, so check `/login` instead
- [ ] `/expenses` signed in: the filter bar is one column, the table shows as cards, and the pagination wraps
- [ ] At desktop width: `/expenses`, with the "Expenses" nav link coloured like "Add Expense", the filter bar on one or two rows, and the sticky table header stopping below the navbar while scrolling

Rules 14 and 15 change the navbar on every page, which is why all four pages are checked, not just `/expenses`.

**Expected count:** **309** (unchanged).

**Commit:** `feat: style the expense list and keep every mobile nav link visible`

Do not commit until I have reviewed the diff.

---

## Task 5: docs

**Model:** Sonnet (docs).

First run `git branch --show-current`; stop if it says `main`.

**ACs:** none (spec Definition of done, CLAUDE.md item; design C5).

**Files:** `CLAUDE.md`.

**Red/green:** docs only, so there are no tests.
- **`app.py` route list:** add `/expenses` (Step 9, complete). Cover:
  - `GET` only, behind `@login_required`;
  - `clean_expense_filters(args)` and `page_window(count, page, page_size)` with their return contracts;
  - `PAGE_SIZE`, `MAX_SEARCH` and `_PAGE_RE`;
  - D1: invalid parameters are ignored, an out-of-range page is clamped, and the form is re-rendered from the effective values;
  - D3: the constants;
  - D4: the filtered `Decimal` total over every matching row;
  - D6: `no-store`, and no session write;
  - D7: `prev_url` and `next_url` built with `url_for` from the effective filters only;
  - the filter form is `GET` with no CSRF token;
  - the two empty states, chosen by the unfiltered count.
- **`database/db.py` paragraph:** add `get_filtered_summary`, `get_filtered_expenses`, the shared `_EXPENSE_FILTER` with its fixed SQL and named placeholders (D2a), and `_like_pattern` (D2: backslash first, then `%` and `_`, with `ESCAPE '\'`). Say that no index is added (D5).
- **`no_store` users:** add `/expenses`.
- **`templates/` list:** add `expenses.html`.
- **Nav:** note the `nav-expenses` link and the mobile `:not(...)` rule.
- **Roadmap:** "Steps 1-7 and 9 are built. Then: Step 8 dashboard UI, Step 10 edit expense, Step 11 delete expense, Step 12 deploy."
- **Keep:** "until Steps 10-11", the out-of-date `"coming in Step 8"` / `"coming in Step 9"` note, and "no rate limiting".
- **Step 12:** note that the production access log must not record query strings (spec, Later steps).
- No env values, URLs, passwords or tokens in the text.

**Commands:**
```bash
grep -n "/expenses\b\|clean_expense_filters\|page_window\|get_filtered_summary\|_like_pattern\|expenses.html" CLAUDE.md   # new lines present
grep -n "is this step" CLAUDE.md                                                       # nothing
grep -n "Steps 10-11\|rate limiting" CLAUDE.md                                         # still present
git diff -- CLAUDE.md | grep -niE "postgresql://|password=|secret_key ?="              # nothing
.venv/bin/pytest --collect-only -q | tail -1                                           # 309
```

**Expected count:** **309** (unchanged).

**Commit:** `docs: document the expense list (Step 9)`

Do not commit until I have reviewed the diff.

---

## V: validate (no commit of its own)

**Model:** Opus (security and quality validation).

First run `git branch --show-current`; stop if it says `main`.

**ACs:** all of AC-1 to AC-36 (review and test coverage).

**Files:** none by default. A fix batch touches only the files named in its approved findings.

**Steps:**
1. Run `/code-review-feature 09-expense-list-search-filter`. It reviews `git diff main...HEAD` plus any uncommitted work with the security and quality reviewers, and it is read-only. Stop and show me the combined findings.
2. Run `/test-feature 09-expense-list-search-filter`. Stop and show me the result.
3. Apply only the fixes I approve, in the batches I name. For each batch:
   - First run `git branch --show-current`; stop if it says `main`.
   - Red first wherever the fix can be tested: a failing test, then the fix, then the file's tests and `.venv/bin/pytest -q`. A new test that passes on its first run gets a mutation check (header steps). A fix to `_EXPENSE_FILTER`, `_like_pattern`, `clean_expense_filters` or the view re-runs the mutations above that touch it.
   - Tests stay on `spendly_test` only. Never print DB URLs, passwords or CSRF tokens.
   - One commit per batch, with a conventional message (`fix: ...`, `test: ...`, `docs: ...`).
   - Do not commit until I have reviewed the diff.
4. Tests added by `/test-feature` that I approve go in their own batch commit (`test: ...`). Tests I reject are removed before any commit. Approved extra tests change the spec's "309" Definition of done count, so record A here.

**Expected count:** 309 + A, where A is the number of collected tests added in approved batches (0 if none). **Recorded:** _(fill in when V ends)_.

**Commit:** none of its own; one per approved fix batch.

Do not commit until I have reviewed the diff.

---

## S: final sweep, Definition of done and browser checks (no commit)

**Model:** Opus (security-sensitive review).

First run `git branch --show-current`; stop if it says `main`.

**Precondition:** task 5 and every approved V batch are committed, and `git status` is clean. The Definition of done greps compare against `main` (`git diff main -- …`), so they run **only after the last task is committed**. Uncommitted work would hide hits or invent them. If `git status` is not clean, stop.

**ACs:** all of AC-1 to AC-36 (confirmation only), and the spec's Definition of done.

**Files:** none edited. The repository is read-only in this task. The only writes are the temporary dev-database rows below, which are removed by exact id before S ends.

**Automated sweep** (report each result; fix nothing. Any problem goes back to V as a new batch):
```bash
shasum spendly.db; .venv/bin/pytest -q; shasum spendly.db                                  # all pass, hashes match
.venv/bin/pytest --collect-only -q | tail -1                                               # 309 + A
grep -c "_ac[0-9]*(" tests/test_expense_list.py                                            # 36, AC-1..AC-36 each once
git diff main --stat -- tests/                                                             # only tests/test_expense_list.py
git diff main -- database/db.py                                                            # only the new reads and helpers; _SCHEMA, init_db, seed_db unchanged
git diff main -- templates/ | grep '^+' | grep -nE '\|safe|Markup|autoescape false|style=|<style'   # nothing
git diff main -- static/ | grep '^+' | grep -nE '#[0-9a-fA-F]{3,8}\b'                      # nothing
git diff main -- app.py database/db.py | grep '^+' | grep -nE 'float\('                    # nothing
git diff main -- app.py database/db.py templates/ | grep '^+' | grep -nE 'logging|print\(' # nothing
grep -n "execute(f" database/db.py                                                         # nothing
git diff main -- app.py | grep -n "coming in Step"                                         # nothing (placeholders untouched)
git diff main -- requirements.txt tests/conftest.py tests/helpers.py templates/profile.html static/js/main.js   # empty
grep -rn '<form' templates/                                                                # POST forms only in base, login, register, add_expense; expenses.html has one GET form
grep -nE "(SELECT|INSERT|UPDATE|DELETE)" app.py                                            # no SQL
git diff main...HEAD | grep -niE "postgresql://|password=|secret_key ?="                   # no real URL, password or key
git status --short --ignored | grep expense-tracker-frontend                               # still "!! expense-tracker-frontend/", nothing staged
git status                                                                                 # clean
```
Also read the `database/db.py` diff to confirm that no SQL includes a value through an f-string, `%`, `.format()` or `+`.

**Browser checks with Playwright, as the demo user.** These use the dev database `spendly`, and every row they add is removed by exact id:
1. **Fixture rows.** Run one `.venv/bin/python` script (connection from `get_db()`, parameterised queries, nothing printed except ids and counts). It:
   - looks up the demo user's id (`demo@spendly.com`) and records the demo user's expense count as the baseline;
   - inserts, with `create_expense`, 25 Food rows dated 2026-04-01 to 2026-04-25 with descriptions `S-sweep 50% & more NN`, plus one Bills row `<script>alert(1)</script> S-sweep` dated 2026-04-26;
   - creates one throwaway user `s-sweep-empty@example.com`, for the "No expenses yet." state. The literal password `s-sweep-pass-123` goes through `generate_password_hash` first, and only the hash is passed to `create_user`;
   - writes the returned expense ids and the user id to `$SCRATCH/s-sweep-ids.json`.

   Do not use `/seed-expenses` here (it does not return ids), and do not submit the add-expense form (that would create a row with no recorded id).
2. **Start the app in the background:** `SPENDLY_SECRET_KEY=dev-only-value .venv/bin/python3 app.py`.
3. **Sign in through `/login` as `demo@spendly.com` / `demo123`, then check:**
   - [ ] Desktop: the "Expenses" nav link is present and leads to `/expenses`. Rows are newest first. `Showing 1-20 of N` and `Total:` are shown.
   - [ ] Each filter alone, then all four together (`category=Food`, `2026-04-01` to `2026-04-30`, `q=50%`): only the S-sweep rows, `Showing 1-20 of 25`, and the form shows all four values. Following "Next" keeps all four in the URL and lists the last 5.
   - [ ] `?page=99` lands on the last page.
   - [ ] The `<script>` row shows as text inside the table. No dialog opens, and `browser_console_messages` shows no errors.
   - [ ] `q=<b>x</b>`: the search box shows the literal text, and "No expenses match these filters." appears with a "Clear filters" link.
   - [ ] `browser_network_request` for the `/expenses` document shows `Cache-Control: no-store` and no `Set-Cookie`.
   - [ ] Back button: go to `/expenses?page=2`, then `/profile`, then back. `browser_network_requests` shows a second `GET /expenses?page=2` (refetched, not cached).
   - [ ] Sign out, sign in as the throwaway user: `/expenses` shows "No expenses yet." with an "Add expense" link.
4. **At 360×740** (`browser_resize`), on `/`, `/login`, `/register`, `/profile` and `/expenses`, signed in and signed out (a page that redirects counts as its redirect target), check with `browser_evaluate` that:
   - `document.documentElement.scrollWidth <= window.innerWidth` (no horizontal scroll);
   - every nav item has a non-zero `getBoundingClientRect()` (`.nav-expenses`, `.nav-add`, `.nav-user`, `.nav-signout` signed in, and `.nav-cta` signed out);
   - `.navbar`'s bottom is at or above `main`'s top.

   Save a screenshot of each page to `$SCRATCH`.
5. **Clean up, always, even if a check failed:**
   - stop the app;
   - run one script that reads `$SCRATCH/s-sweep-ids.json` and, in one `conn.transaction()`, runs `DELETE FROM expenses WHERE user_id = %s AND id = ANY(%s)` with the demo id and the recorded ids, then `DELETE FROM users WHERE id = %s AND email = %s` with the throwaway id and email;
   - assert the expense rowcount equals the number of recorded ids and the user rowcount is 1;
   - re-count the demo user's expenses and confirm the count equals the baseline;
   - confirm `SELECT count(*) FROM expenses WHERE description LIKE '%%S-sweep%%'` is 0.

   Nothing is deleted except by those exact ids.

**Report:** the counts, each grep result, the hash check, each browser check (with screenshot paths) and the cleanup counts. Ship starts only after I confirm.

**Expected count:** **309 + A**.

**Commit:** none.

Do not commit until I have reviewed the diff.

---

## Ship: push and open the pull request (no commit)

**Model:** Sonnet (git and PR text).

First run `git branch --show-current`; stop if it says `main`.

**Precondition:** S has passed and I have confirmed it. `git status` is clean. If not, stop.

**ACs:** none.

**Files:** none.

**Steps:**
1. Show me `git log --oneline main..HEAD` and `git diff main --stat`. Then wait for my go-ahead before anything leaves this machine.
2. On my go-ahead: run `git push -u origin feature/expense-list-search-filter`, then `gh pr create --base main --head feature/expense-list-search-filter --title "feat: expense list with search and filter (Step 9)"`. The body covers:
   - **What:** `GET /expenses` with category, date range and search filters, the filtered total, pagination, and the nav link.
   - **Decisions:** D1-D7 in one line each.
   - **Tests:** 309 + A collected, all passing, with `spendly.db` untouched.
   - **Manual checks:** the S browser results.
   - **Later steps:** Step 8 restyle, Steps 10-11 Actions column, Step 12 access log without query strings.
   - It ends with `🤖 Generated with [Claude Code](https://claude.com/claude-code)`.
3. Report the PR URL. Do not merge. I merge.

**Expected count:** **309 + A** (unchanged).

**Commit:** none.

Do not commit until I have reviewed the diff.

---

## Summary

| Task | Design §8 | What | Model | Collected after |
|---|---|---|---|---|
| 1 | 1 | `_EXPENSE_FILTER`, `_like_pattern`, two filtered reads; AC-23, 36 | Opus | 275 |
| 2 | 2 | Constants, `_filter_date`, `clean_expense_filters`, `page_window`; AC-34, 35 | Opus | 277 |
| 3a | 3a | View with no filters, `expenses.html`, nav link; AC-1–8 | Opus | 285 |
| 3b | 3b | Filters, empty states, escaping; AC-9–21, 31–33 (mutations for AC-10, 14, 19, 31) | Opus | 301 |
| 3c | 3c | Totals and pagination; AC-22, 24–30 (mutations for AC-22, 26) | Opus | 309 |
| 4 | 4 | CSS rules 1–17, grep checks, 360px manual checks | Sonnet | 309 |
| 5 | 5 | CLAUDE.md | Sonnet | 309 |
| V | — | `/code-review-feature`, then `/test-feature`; approved fix batches | Opus | 309 + A |
| S | 6 | Read-only sweep, DoD greps (after the last commit), Playwright checks as the demo user, cleanup by exact id | Opus | 309 + A |
| Ship | — | Push and open the PR after my go-ahead; I merge | Sonnet | 309 + A |

**Deferred:** share the date parsing between `_filter_date` and `validate_expense` in Step 10.

**Manual check (review item 2):** the 360px mobile navbar check on `/`, `/login`, `/register`, `/profile` and `/expenses` was done by hand and passed.
