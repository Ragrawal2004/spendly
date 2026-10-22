# Tasks: Step 7 — Add Expense Form and CSRF

Companion to `07-add-expense-form-csrf.md` (spec) and `07-add-expense-form-csrf.design.md` (design). This file is only the plan. It has no code, and the spec and design are not edited.

**How to work through this list**
- Run the tasks in this order: **a → b → c → d → e → V → S → f**. Tasks a to f are design §8 tasks 1 to 6, in the same order. V (validate) and S (the read-only final sweep with the manual checks, including the tamper check) come between e and f, because design §8 task 6 may only run after the sweep and the manual tamper check have both passed.
- Tasks a to f are one commit each, with a conventional message (`type: summary`). The `Co-Authored-By` trailer is added at commit time. V has no commit of its own, only one commit per fix batch I approve. S is read-only and has no commit.
- Red, then green. Write the listed tests, run them and watch them fail, write the code, run them and watch them pass, then run the full suite.
- New tests go in `tests/test_add_expense_form_csrf.py`, named exactly as in design §5. Shared helpers go in `tests/helpers.py` and are imported with `from helpers import csrf_token, post_form`. `tests/conftest.py` is never changed. Check at the end of each task that `git diff main -- tests/conftest.py` is empty.
- The new test file has its own local helpers: `_page_token(body)` (regex `name="csrf_token" value="([^"]+)"`), `_make_user`, `login_as` (sets `user_id`, then calls `csrf_token(client)`), `_rows`, `_valid_form` (`amount=250`, `category=Food`, `date=<today UTC>`, `description=Lunch`) and `_today`. They follow the `tests/test_add_expense.py` pattern. The CSRF body is the spec literal, stored in the test file as `CSRF_BODY = "Invalid or missing form token. Reload the page and try again."` and not imported from `app`.
- "The CSRF 400" in a test always means three asserts in this order: status 400, then `Content-Type` starts with `text/plain`, then the body equals `CSRF_BODY`. Assert the status code first, so a test cannot pass by accident.
- **Secrets:** tests use only `spendly_test` through the existing fixtures. Never print, echo or hard-code `DATABASE_URL`, `SPENDLY_TEST_DATABASE_URL`, a password from the environment or a CSRF token. The only passwords are throwaway literals such as `"password123"` passed to `generate_password_hash`. Pytest prints both sides of a failed `==`, so a token comparison never goes in a bare `assert`. Compute `same = (page_token == session_token)` and then `assert same, "page token differs from session token"`, and use the same pattern for `!=`. Length and character-set checks assert on `len(...)` and on a `bool` such as `re.fullmatch(...) is not None`. Never run pytest with `-l`/`--showlocals` or `-s`, and never add `print` to a test.
- **`spendly.db`:** before the first full run of each task and again after it, run `shasum spendly.db` (if the file exists). The two hashes must match.
- **Counts:** the baseline is **236** collected (checked at planning time). Each AC is one test. The planned counts are a 236, b 248, c 261, d 270, e 271, f 271. V may add tests (A of them), which shifts S and f to 271 + A. Check with `.venv/bin/pytest --collect-only -q | tail -1`.

**Two deviations from the design's AC split** (the task order itself is unchanged):
1. **AC-21 moves from task c to task d.** AC-21 reads the token from two `GET /expenses/add` pages. Until task d that route returns the placeholder string, which has no token in it, so AC-21 cannot pass in task c with "no app changes". In task d it is written red first. As a result, task c adds 13 tests instead of 14, and task d adds 9 instead of 8.
2. **AC-31 is written in task c for `/login`, `/register` and `/profile`, and extended in task d with `/expenses/add`.** In task c the add page renders no forms, so a check of "every form on it has a token" would pass with nothing to check. The task c version asserts that each page has at least one `<form method="POST">` and that every such form holds the session token. Task d adds `/expenses/add` (exactly 2 POST forms: the nav sign-out and the add form) to the page list, red first. The test count does not change.

**Mutation check for guard tests** (a test that passes on its first run). Every time:
1. Apply the one-off mutation named in the task.
2. Run the named test and watch it go red: `.venv/bin/pytest -q tests/<file>::<test>`.
3. Delete bytecode before reverting: `find . -name __pycache__ -not -path './.venv/*' -exec rm -rf {} +`
4. Revert the mutation by hand (undo exactly that edit). Never use `git checkout` or `git stash` on a file that holds the task's uncommitted work.
5. Run the test again and watch it go green. `git diff` must show no trace of the mutation. Never commit a mutation.

---

## Task a: shared test helpers and token-sending call sites (no behaviour change)

**Model:** Sonnet (test migration).

First run `git branch --show-current`; stop if it says `main`.

**ACs:** none new. Prepares the existing suite for the spec's "Conflicts with existing tests" section (design §4, C12).

**Files:** `tests/helpers.py` (new), `tests/test_add_expense.py`, `tests/test_login_logout.py`, `tests/test_profile.py`, `tests/test_registration.py`.

**Red:** none possible. The app ignores the extra `csrf_token` field, so this is a test-only refactor that must stay green. Task b proves the migration works: once the hook is on, any call site left behind fails with the CSRF 400.

**Green:**
- Create `tests/helpers.py` with `csrf_token(client)` and `post_form(client, url, data=None, **kwargs)` exactly as in design §4: plain functions, no tests and no fixtures. `post_form` copies `data` and adds `csrf_token` only when the caller did not pass one.
- Switch all 31 call sites in the design §4 table to `post_form(client, url, data, ...)`, keeping every other kwarg (`follow_redirects=True` at `test_add_expense.py:475` and `test_profile.py:387`). `/logout` calls become `post_form(client, "/logout")`. The registration `post` helper passes its filtered data to `post_form`.
- In each of the three `login_as` helpers (`test_add_expense.py:53`, `test_login_logout.py:295`, `test_profile.py:36`), keep setting `user_id` and then call `csrf_token(client)`.
- Leave alone: `test_profile.py:259` (`getattr(client, "post")("/profile")`) and `test_add_expense.py:341-342` (`put`/`delete`).
- Do not change any assertion in this task. Step 3 AC-2 and AC-21 still pass, because login's `session.clear()` drops the planted token (design §8 task 1).

**Commands:**
```bash
grep -c "client.post(" tests/test_add_expense.py tests/test_login_logout.py tests/test_profile.py tests/test_registration.py   # expect 0 in each
grep -n "from helpers import" tests/*.py                                                                                    # the four files
.venv/bin/pytest --collect-only -q | tail -1                                                                                # 236
shasum spendly.db; .venv/bin/pytest -q; shasum spendly.db
git diff main -- tests/conftest.py                                                                                          # empty
git diff -- tests/ | grep '^-def test_'                                                                                     # empty
```

**Expected count:** **236** (unchanged).

**Commit:** `test: send CSRF tokens from existing form posts`

Do not commit until I have reviewed the diff.

---

## Task b: CSRF core — token, hook and protected routes

**Model:** Opus (CSRF hook, security-sensitive).

First run `git branch --show-current`; stop if it says `main`.

**ACs:** AC-8 to AC-19, plus the deliberate Step 3 AC-2 and AC-21 changes (design C2).

**Files:** `app.py`, `templates/base.html`, `templates/login.html`, `templates/register.html`, `tests/test_add_expense_form_csrf.py` (new), `tests/test_login_logout.py`.

**Red:**
- Create `tests/test_add_expense_form_csrf.py` with the local helpers from the header and the 12 tests `test_add_missing_token_ac8` to `test_logout_wrong_token_ac18` and `test_logout_valid_token_ac19` (design §5 names). Missing-token tests call `client.post` directly. Wrong-token tests pass `csrf_token=secrets.token_urlsafe(32)`. Every missing or wrong case also asserts `"Set-Cookie" not in resp.headers` where the AC says so (AC-8, 9, 11, 12, 17), and checks the database: no expense row (AC-8, 9), no user row for the email (AC-14, 15).
- In `test_login_logout.py`, change Step 3 AC-2 (`test_ac2_valid_login_redirects_to_profile_with_only_user_id`) and AC-21 (`test_ac21_login_discards_other_session_data`) to `assert set(sess) == {"user_id", "csrf_token"}` and `assert sess["user_id"] == uid`. Their names and their other assertions stay as they are.
- `.venv/bin/pytest -q tests/test_add_expense_form_csrf.py tests/test_login_logout.py`. Expect red on AC-8, 9, 11, 12, 14, 15, 17, 18 (no hook yet, so each request goes through) and on Step 3 AC-2 and AC-21 (no rotated token in the session yet).
- **Guards that pass on the first run:** AC-10, AC-13, AC-16 and AC-19 (the valid-token paths already work). Prove them after green with the mutations below.

**Green** (design §1, §2):
- `app.py`: add `CSRF_ERROR`, `get_csrf_token()` with `@app.template_global("csrf_token")`, and `check_csrf_token()` with `@app.before_request`. All three go directly after `startup()` (line 74) and **above** `load_current_user` (C5). Use the exact check from design §1: `request.method != "POST" or request.endpoint is None` gives a pass-through. Both values must be non-empty `str`. Compare with `secrets.compare_digest(submitted.encode("utf-8"), expected.encode("utf-8"))`. Read only `request.form`, and on failure return `CSRF_ERROR, 400, {"Content-Type": "text/plain; charset=utf-8"}` without touching the session.
- `app.py`: add `no_store(rv, status=200)` next to `login_required`. In `login()`, call `get_csrf_token()` right after `session["user_id"] = user["id"]`. The 400/401 paths stay as they are. GET `/login` 200 → `no_store(render_template("login.html", registered=...))`. GET `/register` 200 → `no_store(render_template("register.html"))`. Signed-in redirects stay as they are. `logout()` stays as it is.
- Templates: add `<input type="hidden" name="csrf_token" value="{{ csrf_token() }}">` as the first child of the sign-out form in `base.html`, the form in `login.html` and the form in `register.html`. No nav link yet (task d).
- Run `.venv/bin/pytest -q tests/test_add_expense_form_csrf.py tests/test_login_logout.py`, then the full suite. Every existing test must pass. A failure with the CSRF 400 means task a missed a call site; fix that in the test file, never in the hook.

**Mutations** (after green, the steps above):
- AC-10, AC-13, AC-16, AC-19: in `check_csrf_token`, delete the `return None` inside the passing `if`, so even a match falls through to the 400. All four go red.
- AC-8 (the "no `Set-Cookie`" half): add `session.pop("csrf_token", None)` just before the failure `return`. AC-8 goes red, because the response now sets a cookie.
- Task a's migration: in `tests/helpers.py`, make `post_form` skip adding the token (`return client.post(url, data=dict(data or {}), **kwargs)`). Run `.venv/bin/pytest -q tests/test_add_expense.py tests/test_login_logout.py tests/test_profile.py tests/test_registration.py` and watch many tests go red with the CSRF 400.

**Commands:**
```bash
shasum spendly.db; .venv/bin/pytest -q; shasum spendly.db
.venv/bin/pytest --collect-only -q | tail -1     # 248
sed -n '/def check_csrf_token/,/^def /p' app.py | grep -n "request.args\|request.headers"   # expect nothing (login() legitimately reads request.args for ?registered=1)
git diff main -- tests/conftest.py               # empty
```

**Expected count:** 236 + 12 = **248**.

**Commit:** `feat: require a CSRF token on every POST`

Do not commit until I have reviewed the diff.

---

## Task c: CSRF core — token lifecycle and checking-rule tests

**Model:** Opus (lifecycle tests, security-sensitive).

First run `git branch --show-current`; stop if it says `main`.

**ACs:** AC-20, AC-22 to AC-31 (AC-31 for `/login`, `/register` and `/profile` only), AC-34, AC-35. AC-21 moves to task d (header, deviation 1).

**Files:** `tests/test_add_expense_form_csrf.py`. No app files. Any failure here is a task b bug: stop and show me before changing app code.

**Red:** none expected. All 13 tests guard code from task b, so each one is proven able to fail with its own mutation.
- Notes on writing the tests: AC-20, AC-30 and AC-35 use a fresh client with no helper calls. AC-27 sets `user_id` with a raw `client.session_transaction()`, not `login_as`, which would add a token. AC-22 and AC-23 sign in through the real `GET /login` page and read the token with `_page_token`. AC-25 uses two clients (`app.test_client()` twice). AC-26 is one test that loops over `""`, `"é" * 43`, `"x" * 10_000` and `token + " "`, asserting the CSRF 400 (never 500) and no row for each. AC-29 asserts `PUT`/`DELETE /expenses/add` and `POST /profile` give 405, and `POST /no-such-page` gives 404, all without a token. AC-31 (header, deviation 2) checks `/login` and `/register` signed out and `/profile` signed in.
- Run `.venv/bin/pytest -q tests/test_add_expense_form_csrf.py`. All of these pass on the first run.

**Mutations** (one per test, the steps above):

| Test | One-off mutation | Why it goes red |
|---|---|---|
| AC-20 `test_login_register_pages_issue_token_ac20` | In `get_csrf_token`, use `secrets.token_hex(8)` | 16 characters, fewer than 43 |
| AC-22 `test_login_rotates_token_ac22` | **Login rotation:** delete the `get_csrf_token()` line in `login()` | No new token T2 after login |
| AC-23 `test_token_dies_at_logout_ac23` | In `logout()`, replace `session.clear()` with `session.pop("user_id", None)` | T survives logout and the login with T gets 302 |
| AC-24 `test_failed_login_keeps_token_ac24` | In `login()`, add `session.pop("csrf_token", None)` on the 401 path before the render | The re-render issues a new token |
| AC-25 `test_other_session_token_rejected_ac25` | In `get_csrf_token`, use one process-wide token: `token = app.config.setdefault("CSRF_SHARED", secrets.token_urlsafe(32))` | B's session holds A's token, so the post gets 303 |
| AC-26 `test_malformed_tokens_rejected_ac26` | **Bytes compare_digest:** compare the `str` values, `secrets.compare_digest(submitted, expected)` | `"é" * 43` raises `TypeError`, so 500 |
| AC-27 `test_absent_session_token_never_matches_ac27` | Use `session.get("csrf_token", "")` and `request.form.get("csrf_token", "")`, and delete both non-empty checks | `b"" == b""` matches |
| AC-28 `test_csrf_before_load_current_user_ac28` | **Hook order:** move the whole `check_csrf_token` block below `load_current_user` | `load_current_user` clears the session first, so the token is gone and the answer is 400, not 302 |
| AC-29 `test_405_and_404_not_checked_ac29` | **Endpoint-is-None guard:** delete `or request.endpoint is None` | `POST /profile` and `POST /no-such-page` get 400 |
| AC-30 `test_formless_pages_set_no_cookie_ac30` | Call `get_csrf_token()` inside `inject_current_user` | Every page writes the session |
| AC-31 `test_every_post_form_has_token_ac31` | Delete the hidden input from `register.html` | The register form has no token |
| AC-34 `test_profile_after_real_login_no_set_cookie_ac34` | **Login rotation** (same as AC-22): delete `get_csrf_token()` in `login()` | `/profile`'s nav form writes a token, so `Set-Cookie` |
| AC-35 `test_login_register_no_store_ac35` | **No-store:** unwrap `no_store(...)` from the GET `/register` render (then, separately, from the GET `/login` render) | No `Cache-Control: no-store` |

After each mutation, delete `__pycache__`, revert by hand, re-run the test and check `git diff` shows no trace.

**Commands:**
```bash
shasum spendly.db; .venv/bin/pytest -q; shasum spendly.db
.venv/bin/pytest --collect-only -q | tail -1     # 261
git diff -- app.py templates/                    # empty (no app changes in this task)
```

**Expected count:** 248 + 13 = **261**.

**Commit:** `test: cover CSRF token lifecycle and checking rules`

Do not commit until I have reviewed the diff.

---

## Task d: the add-expense form page

**Model:** Opus (form route, security-sensitive: escaping, re-render, no-store).

First run `git branch --show-current`; stop if it says `main`.

**ACs:** AC-1 to AC-7, AC-21 (moved from task c), AC-32, the `/expenses/add` half of AC-31, and the deliberate Step 6 AC-12, AC-13, AC-18 and AC-27 changes (Step 6 AC-1 already changed in task a: it sends a token through `post_form`).

**Files:** `app.py`, `templates/add_expense.html` (new), `templates/base.html`, `tests/test_add_expense_form_csrf.py`, `tests/test_add_expense.py`.

**Red:**
- Add to the new file: `test_get_signed_out_redirects_ac1`, `test_get_renders_form_ac2` (the seven categories in `CATEGORIES` order, read from the HTML; `min="2000-01-01"`; `max` = tomorrow UTC; `maxlength="200"`; the submit button; a link to `/profile`), `test_get_token_matches_session_no_store_ac3`, `test_invalid_amount_rerenders_values_ac4` (matches `<option value="Bills" selected>`), `test_rerender_escapes_input_ac5`, `test_rerender_other_field_errors_ac6`, `test_end_to_end_real_pages_ac7`, `test_token_is_per_session_ac21` and `test_nav_add_expense_link_ac32`. Add `/expenses/add` to AC-31's page list, expecting exactly 2 POST forms there. Error messages are imported from `app` or copied verbatim from Step 6 (`Enter a valid amount, like 250 or 99.50.` and the category, date and description messages).
- In `test_add_expense.py`, apply the design §4 changes to `test_invalid_post_plain_text_400_ac12`, `test_error_does_not_echo_input_ac13`, `test_get_placeholder_protected_ac18` and `test_description_control_chars_ac27`. Keep their names. Nothing else is loosened.
- Run `.venv/bin/pytest -q tests/test_add_expense_form_csrf.py tests/test_add_expense.py`. Red: AC-2 to AC-7, AC-21, AC-31 and AC-32 fail (placeholder page, plain-text 400, no nav link), and so do Step 6 AC-12, 13, 18 and 27.
- **Guard that passes on the first run:** AC-1 (`@login_required` already protects GET). Mutation below.

**Green** (design §2, §3):
- `app.py`: put `render_expense_form(...)` directly above the route, exactly as in design §3. `add_expense()` GET returns `render_expense_form(today)`. The POST error path returns `render_expense_form(today, 400, error=..., amount=..., category=..., date_value=date_str, description=...)`. The `create_expense`, `ForeignKeyViolation` and 303 code is unchanged. `clean_expense`, `validate_expense` and `create_expense` are not touched. The `"coming in Step 7"` string is removed; the Step 8 and Step 9 placeholders stay exactly as they are.
- `templates/add_expense.html`: as in design §2 (auth layout classes, `expense-form-section`, hidden token first, the C11 `disabled` + conditional `selected` placeholder option, exact `<option value="{{ c }}"{% if c == category %} selected{% endif %}>` spacing, `form-cancel` link, error box). No `|safe`, no `Markup`, no `style=`.
- `templates/base.html`: `<a href="{{ url_for('add_expense') }}" class="nav-add">Add Expense</a>` before `.nav-user`, signed-in only.
- Run `.venv/bin/pytest -q tests/test_add_expense_form_csrf.py tests/test_add_expense.py`, then the full suite. The existing `test_profile_nav_and_add_expense_links_ac20` must still pass unchanged.

**Mutations** (after green):
- AC-1: remove `@login_required` from `add_expense`. A signed-out GET gets 200, so AC-1 goes red.
- AC-3 (**no-store** on the form page): delete the `resp.headers["Cache-Control"] = "no-store"` line in `no_store`. AC-3 goes red (as do AC-35 and the login/register pages; that's expected).
- AC-4 (no `Set-Cookie` on the 400): add `session["touched"] = 1` before the 400 `return`. AC-4 goes red.
- AC-5 (escaping): add `|safe` to the description `value` in `add_expense.html`. AC-5 goes red.
- AC-32: wrap the nav link in `{% if false %}`. AC-32 goes red.

**Commands:**
```bash
shasum spendly.db; .venv/bin/pytest -q; shasum spendly.db
.venv/bin/pytest --collect-only -q | tail -1                       # 270
grep -n "coming in Step" app.py                                    # only Step 8 and Step 9
grep -rn "|safe\|Markup\|autoescape false\|style=" templates/      # nothing
git diff main -- app.py | grep -n "def clean_expense\|def validate_expense"   # nothing
git diff main -- tests/test_add_expense.py | grep '^-def test_'    # empty
```

**Expected count:** 261 + 9 = **270**.

**Commit:** `feat: render the add expense form with token and re-render on error`

Do not commit until I have reviewed the diff.

---

## Task e: R4 `<bdi>`, CSS and docs

**Model:** Sonnet (CSS and docs; the one template line and AC-33 are written red first).

First run `git branch --show-current`; stop if it says `main`.

**ACs:** AC-33. Also the Definition of done items for CSS and CLAUDE.md, except the deploy note (task f).

**Files:** `templates/profile.html`, `static/css/style.css`, `CLAUDE.md`, `tests/test_add_expense_form_csrf.py`.

**Red:**
- Add `test_cf_descriptions_stored_in_bdi_ac33`. Post `"‮abc"`, `"a​b"` and `"क्‌ष"` with `post_form`. Read each row back with a parameterised `SELECT` and check it is stored unchanged. Then check that `/profile` shows each one as `<bdi>…</bdi>`. Use `\u` escapes in the test source, never literal invisible characters.
- Run `.venv/bin/pytest -q tests/test_add_expense_form_csrf.py::test_cf_descriptions_stored_in_bdi_ac33`. It goes red (no `<bdi>` yet).

**Green:**
- `templates/profile.html:67` → `<td data-label="Description"><bdi>{{ e["description"] or "—" }}</bdi></td>`. Nothing else changes.
- **`<bdi>` mutation** (after green, the steps above): remove the `<bdi>` and `</bdi>` tags again. AC-33 goes red. Revert by hand.
- `static/css/style.css` (design §2): `.nav-links .nav-add` and its `:hover`, `.form-select`, `.form-cancel` and its `:hover`. Change the mobile rule at line 869 to `.nav-links a:not(.nav-cta):not(.nav-user):not(.nav-add)` (C10). Use existing variables only, and add no hex values.
- `CLAUDE.md` (C8): the `/expenses/add` entry (Step 7 form, `render_expense_form`, HTML 400 re-render with escaped values, `no-store`), the CSRF design (one token per session, `get_csrf_token` / `csrf_token()` template global, rotated at login, dropped at logout, global `check_csrf_token` hook registered before `load_current_user`, matched `POST`s only, bytes `compare_digest`, fixed plain-text 400 with no `Set-Cookie`, form body only), `no_store`, R4 closed (`Cf` kept, `<bdi>` on `/profile`), the session now holding `user_id` and `csrf_token`, `/login` and `/register` setting `no-store`, `tests/helpers.py`, `add_expense.html` in the templates list, and the new roadmap (Steps 1–6 as built, 7 this step, 8 dashboard UI, 9 list/search/filter, 10 edit, 11 delete, 12 deploy). Change "until Steps 8-9" to "until Steps 10-11", and note that the `"coming in Step 8"` and `"coming in Step 9"` strings in `app.py` are out of date and will be replaced in Steps 10 and 11. **Do not** remove the "Do not deploy" note or the "no CSRF token on any form" gap yet (task f). No env values, URLs, passwords or tokens in the text.

**Commands:**
```bash
shasum spendly.db; .venv/bin/pytest -q; shasum spendly.db
.venv/bin/pytest --collect-only -q | tail -1                        # 271
grep -n "#[0-9a-fA-F]\{3,8\}" static/css/style.css                  # every hit inside :root
grep -o "var(--[a-z0-9-]*)" static/css/style.css | sort -u           # each defined in :root
grep -rn "style=" templates/                                        # nothing
grep -n "Steps 10-11\|Step 12\|R4\|csrf_token" CLAUDE.md             # new lines present
grep -n "Do not deploy" CLAUDE.md                                   # still present
```

**Expected count:** 270 + 1 = **271**.

**Commit:** `feat: close R4 with bdi, style the add expense form and document Step 7`

Do not commit until I have reviewed the diff.

---

## V: validate (no commit of its own)

**Model:** Opus (security and quality validation).

First run `git branch --show-current`; stop if it says `main`.

**ACs:** all of AC-1 to AC-35 (review and test coverage).

**Files:** none by default. A fix batch touches only the files named in its approved findings.

**Steps:**
1. Run `/code-review-feature 07-add-expense-form-csrf`. It reviews `git diff main...HEAD` plus any uncommitted work with the security and quality reviewers, and it is read-only. Stop and show me the combined findings.
2. Run `/test-feature 07-add-expense-form-csrf`. Stop and show me the result.
3. Apply only the fixes I approve, in the batches I name. For each batch:
   - First run `git branch --show-current`; stop if it says `main`.
   - Red first wherever the fix can be tested: a failing test, then the fix, then the file's tests and `.venv/bin/pytest -q`. A new test that passes on its first run gets a mutation check (steps above), and a fix to the CSRF hook re-runs the task c mutations it touches.
   - Tests stay on `spendly_test` only. Never print DB URLs, passwords or CSRF tokens.
   - One commit per batch, with a conventional message (`fix: ...`, `test: ...`, `docs: ...`).
   - Do not commit until I have reviewed the diff.
4. Tests added by `/test-feature` that I approve go in their own batch commit (`test: ...`). Tests I reject are removed before any commit.

**Expected count:** 271 + A, where A is the number of collected tests added in approved batches (0 if none). Record the actual number here when V ends; S and f use it. **Recorded:** _(fill in)_

**Commit:** none of its own; one per approved fix batch.

Do not commit until I have reviewed the diff.

---

## S: final read-only sweep and manual checks (no commit)

**Model:** Opus (security-sensitive review).

First run `git branch --show-current`; stop if it says `main`.

**ACs:** all of AC-1 to AC-35 (confirmation only), and the spec's Definition of done.

**Files:** none edited. This task is read-only.

**Commands** (report each result; fix nothing. Any problem goes back to V as a new batch):
```bash
shasum spendly.db; .venv/bin/pytest -q; shasum spendly.db                 # all pass, hashes match
.venv/bin/pytest --collect-only -q | tail -1                              # 271 + A
grep -c "_ac[0-9]*(" tests/test_add_expense_form_csrf.py                  # 35, AC-1..AC-35 each once
git diff main -- tests/conftest.py                                        # empty
git diff main -- tests/test_add_expense.py tests/test_login_logout.py tests/test_profile.py tests/test_registration.py tests/test_database.py | grep '^-def test_'   # empty
git diff main --stat -- tests/test_add_expense.py tests/test_login_logout.py tests/test_profile.py tests/test_registration.py tests/test_database.py
git diff main -- tests/test_add_expense.py tests/test_login_logout.py tests/test_profile.py tests/test_registration.py   # only post_form/csrf_token/login_as + the 7 listed AC changes
grep -rn "|safe\|Markup\|autoescape false" templates/                     # nothing
grep -rn "style=" templates/                                              # nothing
grep -n "#[0-9a-fA-F]\{3,8\}" static/css/style.css                        # all inside :root
grep -n "coming in Step 7" app.py                                         # nothing
git diff main -- app.py | grep "coming in Step"                           # only the removed Step 7 line
git diff main -- app.py | grep -n "^[-+]def clean_expense\|^[-+]def validate_expense"   # nothing
git diff main -- database/db.py requirements.txt                          # empty
grep -rn "<form" templates/                                               # POST forms only in base, login, register, add_expense
sed -n '/def check_csrf_token/,/^def /p' app.py | grep -n "request.args\|request.headers"   # expect nothing (login() legitimately reads request.args for ?registered=1)
grep -nE "(SELECT|INSERT|UPDATE|DELETE)" app.py                           # no SQL
git diff main...HEAD | grep -niE "postgresql://|password=|secret_key ?="  # no real URL, password or key
git status                                                                # clean
```

**Manual checks** (I run these; you list them and wait). Start the app with `SPENDLY_SECRET_KEY=dev-only-value .venv/bin/python3 app.py` and open `http://localhost:5001`:
- [ ] Signed out: the nav has no "Add Expense" link. Register and sign in work from the real pages.
- [ ] Signed in: the nav shows "Add Expense" (also at ≤600px width). The form shows today's date (UTC) and the seven categories, and Cancel goes to `/profile`.
- [ ] A valid expense shows up on `/profile`.
- [ ] An invalid amount (`abc`) shows the error and keeps the typed values.
- [ ] Sign out works.
- [ ] **Tamper check:** on `/expenses/add`, open dev tools, change one character of the hidden `csrf_token` value (don't copy or paste the token anywhere) and submit a valid form. Expect the fixed plain-text 400 `Invalid or missing form token. Reload the page and try again.`, and `/profile` shows no new expense. Repeat once by deleting the hidden input entirely.
- [ ] A description with U+202E (e.g. pasted `‮abc`) does not reorder the other text in its row on `/profile`.

**Report:** the counts, each grep result, the hash check and the manual checklist (with the boxes I ticked). Task f starts only after I confirm that every automated check passed and the tamper check passed.

**Expected count:** **271 + A**.

**Commit:** none.

Do not commit until I have reviewed the diff.

---

## Task f: lift the deploy block

**Model:** Sonnet (docs).

First run `git branch --show-current`; stop if it says `main`.

**Precondition:** S has passed and I have confirmed the manual tamper check. If not, stop.

**ACs:** none (the last Definition of done item).

**Files:** `CLAUDE.md`.

**Red/green:** docs only, so there are no tests.
- In the Sessions paragraph, remove the "no CSRF token on any form, including `POST /expenses/add` (only `SameSite=Lax`)" known gap, the "CSRF is deferred to Step 7…" sentence and the **Do not deploy** (`… before Step 7 ships it`) note. Keep "no rate limiting" and "until Steps 10-11". Do not add a new deploy approval: deployment is still Step 12.

**Commands:**
```bash
grep -n "Do not deploy\|no CSRF token\|deferred to Step 7" CLAUDE.md   # nothing
grep -n "rate limiting\|Steps 10-11" CLAUDE.md                         # still present
git diff -- CLAUDE.md                                                  # only those removals
.venv/bin/pytest --collect-only -q | tail -1                           # 271 + A (unchanged)
```

**Expected count:** **271 + A** (271 if V added none).

**Commit:** `docs: lift the pre-CSRF deploy block`

Do not commit until I have reviewed the diff.

---

## Summary

| Task | Design §8 | What | Model | Collected after |
|---|---|---|---|---|
| a | 1 | `tests/helpers.py`, 31 call sites, `login_as` | Sonnet | 236 |
| b | 2 | CSRF token + hook, login rotation, hidden fields, `no_store`; AC-8–19; Step 3 AC-2/21 | Opus | 248 |
| c | 3 | Lifecycle / rule tests AC-20, 22–31, 34, 35 | Opus | 261 |
| d | 4 | Form page, 400 re-render, nav link; AC-1–7, 21, 32 (+ AC-31 add page); Step 6 AC-12/13/18/27 | Opus | 270 |
| e | 5 | `<bdi>` + AC-33, CSS, CLAUDE.md | Sonnet | 271 |
| V | — | `/code-review-feature`, then `/test-feature`; approved fix batches | Opus | 271 + A |
| S | 5 (sweep) | Read-only sweep, DoD greps, manual checks + tamper check | Opus | 271 + A |
| f | 6 | Remove deploy note and CSRF gap from CLAUDE.md | Sonnet | 271 + A |
