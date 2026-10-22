# Tasks: Step 4 — Profile

Companion to `04-profile.md` (spec) and `04-profile.design.md` (design). Planning only; no code here.

**How to work through this list**
- Do the tasks in order. Each task is one commit.
- Red, green, commit: write the listed test first and watch it fail, make it pass, then run `.venv/bin/pytest -q` before committing.
- When a test passes before the code exists, say so; it is a regression guard. Regression guards in this list: AC-5 (the placeholder route is already GET-only) and AC-18 (no hash is ever sent, before or after the page exists).
- All new tests go in `tests/test_profile.py`. Test setup follows spec section "Acceptance criteria and tests" (temporary database via `SPENDLY_DB`, `init_db()` through the `client` fixture or before direct db calls, users via `create_user()` with `generate_password_hash`, expenses via direct parameterised inserts through `closing(get_db())`; default user `Rahul Sharma` / `rahul@example.com`).
- Never compare float sums with `==`: assert formatted strings or use `pytest.approx` (design §7).
- Commit messages follow the repo's `type: summary` style. The `Co-Authored-By` trailer is added at commit time.
- Where an AC is only partly satisfiable until a later task lands, the task says so; the AC is owned by the task where it first passes in full (see the coverage table at the end).
- The app stays usable at every commit: until Task 5, a signed-in `GET /profile` still returns the placeholder string, so no commit ships a route that renders a missing template.

---

## Task 1: nav name links to profile

**Goal:** the nav user name becomes a link to `/profile` without breaking the Step 3 nav on desktop or mobile.

**Change:**
- `templates/base.html`: replace `<span class="nav-user">` with `<a href="{{ url_for('profile') }}" class="nav-user">{{ current_user["name"] }}</a>` (autoescaped, no `|safe`, quoted attributes).
- `static/css/style.css` (conflict C1): raise the rule to `.nav-links .nav-user { color: var(--ink); }` with a hover underline; narrow the ≤600px hiding rule to `.nav-links a:not(.nav-cta):not(.nav-user)`; give `.nav-user` a `max-width` with `overflow: hidden; text-overflow: ellipsis; white-space: nowrap`. CSS variables only, no hex values.

**ACs satisfied:** none in full. The nav half of AC-20 is built here; AC-20 is owned by Task 5, where `/profile` first returns 200.

**Test first:**
- Create `tests/test_profile.py` with the shared helpers from design §5: `_make_user(name, email)`, `login_as(client, uid)`, `_add_expense(uid, amount, category, date, description=None)` and `_set_created_at(uid, value)`.
- Signed in, `GET /` contains an `<a>` tag with both `href="/profile"` and `class="nav-user"` (order-independent regex, as AC-20 will use). Fails before the change.
- Run the full suite immediately: Step 3's AC-16 and AC-17 (name shown, name escaped) in `test_login_logout.py` must still pass.

Check the ≤600px nav by eye while signed in: the name and "Sign out" are both visible, and a long name is cut with an ellipsis.

**Commit:** `feat: link nav user name to profile`

---

## Task 2: db.py profile read functions

**Goal:** the route can fetch everything the page shows without any SQL in `app.py`, and no query can read another user's rows.

**Change:** `database/db.py` — add four functions in the style of `get_user_by_id`, each with `with closing(get_db()) as conn:`, a parameterised `SELECT` and a `user_id` filter (design §2 table):
- `get_user_profile(user_id)`: `id, name, email, created_at`, `fetchone()`.
- `get_expense_summary(user_id, month_start, next_month_start)`: one row of `total`, `count`, `month_total`, using `COALESCE(SUM(...), 0)`; parameters in the order `(month_start, next_month_start, user_id)`.
- `get_category_totals(user_id)`: `category, total, count`, `GROUP BY category ORDER BY total DESC, category ASC`.
- `get_recent_expenses(user_id, limit=5)`: `id, amount, category, date, description`, `ORDER BY date DESC, id DESC LIMIT ?`.

No schema change, no rounding in SQL, no `password_hash` selected.

**ACs satisfied:** AC-8, AC-11. Function-level half of AC-10 (the row order); its `67%` page half lands in Task 6.

**Test first:**
- AC-8: dates `2026-10-01`, `2026-10-31`, `2026-11-01`, `2026-09-30` with bounds `("2026-10-01", "2026-11-01")`: `month_total` counts the first two, `total` all four, `count == 4`.
- AC-10 (function level): Food 300 and 100, Transport 100, Bills 100 give rows `Food 400 (2)`, `Bills 100 (1)`, `Transport 100 (1)` in that order.
- AC-11: seven expenses on distinct dates return exactly five rows, newest first; two expenses on the same date return the higher `id` first.
- Extra (not ACs): `get_user_profile` hit returns `created_at` and has no `password_hash` key; miss returns `None`. `get_expense_summary` for a user with no expenses returns `0`, `0`, `0`. Two users' expenses: each function called for user A returns none of user B's rows.

**Commit:** `feat: add profile summary queries to db`

---

## Task 3: pure profile helpers

**Goal:** all date, money and percentage logic is in small pure functions that can be unit tested without a request.

**Change:** `app.py` — add, after `inject_current_user` and before the routes section, with `math` and `datetime`/`timezone` imports:
- `month_bounds(today) -> (str, str)`: first day of this month and of next month as ISO strings; December rolls to January of `year + 1`; no `timedelta`.
- `member_since(created_at) -> str | None`: `strptime(..., "%Y-%m-%d %H:%M:%S").strftime("%B %Y")`, returning `None` on `TypeError` or `ValueError`.
- `format_amount(value) -> str`, registered with `@app.template_filter("format_amount")`: `f"₹{value:,.2f}"`.
- `category_share(total, overall) -> int`: `math.floor(total / overall * 100 + 0.5)`, or `0` when `overall` is 0.

**ACs satisfied:** AC-7. Function-level halves of AC-16 (formatting), AC-24 and AC-25 (`member_since`); the page halves land in Tasks 5 and 6.

**Test first:**
- AC-7: `month_bounds(date(2026, 10, 21)) == ("2026-10-01", "2026-11-01")` and `month_bounds(date(2026, 12, 15)) == ("2026-12-01", "2027-01-01")`.
- `member_since("2026-03-05 10:20:30") == "March 2026"`; `None`, `""` and `"garbage"` (parametrized) return `None` without raising.
- `format_amount`: `12345678.9` gives `₹12,345,678.90`, `0.1 + 0.2` gives `₹0.30`, `0` gives `₹0.00`.
- `category_share`: `(400, 600) == 67`, half-up `(12.5, 100) == 13` (not banker's 12), `(0, 0) == 0`.

**Commit:** `feat: add month bounds, member-since and amount helpers`

---

## Task 4: login_required on /profile

**Goal:** signed-out visitors can no longer reach `/profile`, through one decorator that is the only signed-out gate.

**Change:** `app.py` — add the `functools.wraps` import and `login_required(view)` next to the Task 3 helpers: `@wraps(view)`; if `not getattr(g, "current_user", None)`, return `redirect(url_for("login"))`, else call the view. No `next` parameter, nothing read from the request. Apply `@login_required` below `@app.route("/profile")` on the existing placeholder (which stays a placeholder string until Task 5). The endpoint name stays `profile`, so `url_for("profile")` in `login()`, `register()` and `base.html` keeps working.

**ACs satisfied:** AC-1, AC-3, AC-4, AC-5, AC-22, AC-23.

**Test first** (one test per AC, in order; AC-1, 3, 4, 22 and 23 fail before the change):
- AC-1: no session, `GET /profile` gives 302 with `Location == "/login"`; body contains neither the user's name nor "Profile".
- AC-3: `login_as` a nonexistent id; 302 to `/login` and `user_id` gone from the session.
- AC-4: `client.set_cookie("session", "garbage")`; 302 to `/login`, no exception.
- AC-5: signed in, `POST`, `PUT` and `DELETE /profile` (parametrized) each give 405. Regression guard: the route is already GET-only.
- AC-22: signed in, `POST /logout`, then `GET /profile` gives 302 to `/login`.
- AC-23: inside `app.test_request_context()`, wrap a view that sets a `ran` flag and returns a sentinel. With `g.current_user = None`: a redirect whose `Location` is `/login` with no query string, and `ran` is false. With `g.current_user` set to a user row: the sentinel is returned. `wrapped.__name__` equals the original name.

**Commit:** `feat: protect profile with login_required`

---

## Task 5: profile route, account card and stat tiles

**Goal:** a signed-in user gets a real, uncached profile page showing who they are and their spending totals.

**Change:**
- `app.py`: add the `make_response` import and the four db functions by name (so tests can monkeypatch `app.get_user_profile`). Replace the placeholder `profile()` with the real route, moved after `logout()` (design §1 steps 1-7): `uid = g.current_user["id"]`; `get_user_profile(uid)` returning `None` gives `session.clear()` and a redirect to `/login`; month bounds from `datetime.now(timezone.utc).date()`; fetch the summary, category totals and recent expenses; build `categories` with `percent` from `category_share`; render `profile.html` with `user=g.current_user`, `member_since`, `summary`, `categories` and `recent`; wrap in `make_response` and set `Cache-Control: no-store`. No session writes on the 200 path.
- Keep `@login_required` below `@app.route("/profile")`; the Task 4 tests must stay green.
- `templates/profile.html` (new): extends `base.html`, title "Profile - Spendly"; `.profile-section` with the `.profile-card` (name, email, "Member since" only when set), the `.profile-stats` tiles (total, this month, count with "1 expense" / "N expenses", conflict C6) and the "Add expense" link to `url_for('add_expense')`. The category and recent sections arrive in Task 6. No `|safe`; attributes quoted.

**ACs satisfied:** AC-2, AC-6, AC-13, AC-16, AC-17, AC-18, AC-20, AC-21, AC-24, AC-25.

**Test first** (one test per AC, in order):
- AC-2: signed in, 200 with name, email and "Member since".
- AC-6: expenses 100.00, 250.50, 49.50 show `₹400.00` and `3 expenses`.
- AC-13: two users; `GET /profile?user_id=<other id>` shows the signed-in user's name and not the other's.
- AC-16: one expense of 12345678.9 shows `₹12,345,678.90`; expenses 0.1 and 0.2 show `₹0.30`.
- AC-17: `Cache-Control == "no-store"` and no `Set-Cookie` header.
- AC-18: body contains neither the stored hash nor the string `password_hash`. Regression guard (the placeholder never leaked it either).
- AC-20: the nav `<a>` with `href="/profile"` and `class="nav-user"`, and `href="/expenses/add"` on the page.
- AC-21: `POST /login` with valid credentials and `follow_redirects=True` gives 200 and the user's name.
- AC-24: `_set_created_at(uid, "2026-03-05 10:20:30")` shows `Member since March 2026`.
- AC-25: `"garbage"` and `""` via `_set_created_at` (parametrized), and `None` via monkeypatching `app.get_user_profile` (C4): 200, no "Member since", no exception.
- Extra: vanished user, with `app.get_user_profile` monkeypatched to return `None`: 302 to `/login` and `user_id` gone from the session.

**Commit:** `feat: render profile page with account card and totals`

---

## Task 6: category breakdown and recent expenses

**Goal:** the page shows where the money went and the latest expenses, with a safe empty state.

**Change:** `templates/profile.html` —
- "By category": `{% if categories %}` with one `.category-row` per item (name, `total|format_amount`, `{{ c.percent }}%`); nothing rendered when empty.
- "Recent expenses": `{% if recent %}` renders `<table class="expense-table">` with a `<thead>` (Date, Category, Description, Amount) and the rows in `<tbody>`; each `<td>` has a fixed, quoted `data-label` ("Date", "Category", "Description", "Amount"); the description cell is `{{ e["description"] or "—" }}`; amounts use `format_amount`. `{% else %}` renders `<p class="empty-state">No expenses yet.</p>`.

No route change: `categories` and `recent` are already passed in Task 5.

**ACs satisfied:** AC-9, AC-10 (page half; function half in Task 2), AC-12, AC-14, AC-15, AC-19.

**Test first** (one test per AC, in order):
- AC-9: no expenses: 200, `₹0.00`, `0 expenses`, "No expenses yet.", and `"category-row" not in body`.
- AC-10: the Task 2 data on the page shows Food with `67%`.
- AC-12: two users with distinct amounts and descriptions; each page contains only its own.
- AC-14: user named `<b>x</b>` with description `<script>alert(1)</script>`: `&lt;b&gt;x&lt;/b&gt;` and `&lt;script&gt;` present, no raw `<script>alert(1)</script>`.
- AC-15: a `NULL` description shows "—" and the HTML has no "None".
- AC-19: call `seed_db()` in the test, sign in as `get_user_by_email("demo@spendly.com")`; exactly five `<tr` inside `<tbody>`; the total equals `format_amount(sum(row[2] for row in db._DEMO_EXPENSES_TABLE))` and the count `len(db._DEMO_EXPENSES_TABLE)` (neither hardcoded).

**Commit:** `feat: show category breakdown and recent expenses on profile`

---

## Task 7: profile CSS

**Goal:** the page looks like the rest of Spendly and is readable from 375px to desktop with no horizontal scroll.

**Change:** `static/css/style.css` (design §4), existing variables only:
- `.profile-section`: `max-width: 840px`, centred, padded like other sections.
- `.profile-card`, `.stat-tile`: card look; `overflow-wrap: anywhere` on name and email.
- `.profile-stats`: three-column grid, one column at ≤600px.
- `.category-row`: flex, space-between, share in `var(--ink-muted)`.
- `.expense-table`: `width: 100%; table-layout: fixed; border-collapse: collapse`; cells `overflow-wrap: anywhere`; amount cell `white-space: nowrap; text-align: right`. At ≤600px rows become stacked blocks, `<thead>` hidden, `td::before { content: attr(data-label); }`.
- `.empty-state`: muted and centred.

**ACs satisfied:** none (styling). Supports the spec's 375px edge cases and DoD browser checks.

**Test first:** no new test; the existing suite must stay green. Verify by hand instead:
- `git diff main -- static/css/style.css | grep -E '^\+.*#[0-9a-fA-F]{3,8}\b'` prints nothing outside `:root`.
- In the browser at 375px and desktop width: demo user page, a 100-character name and a 200-character description (with and without spaces) wrap with no horizontal scroll.

**Commit:** `style: add profile page styles`

---

## Task 8: final sweep

**Goal:** prove the whole step meets the spec. This is the last gate before the CLAUDE.md update (Task 9).

**ACs satisfied:** all of AC-1 to AC-25 pass together (individual owners are in the coverage table below).

**Test first:** nothing new. If the sweep finds a gap, add a failing test for it first, fix it, and commit the fix separately.

**Definition of Done (copied from the spec; tick each box):**

- [ ] All acceptance criteria (AC-1 to AC-25) pass with `pytest -q`, and the existing Step 1-3 tests still pass
- [ ] The app was run by hand (`SPENDLY_SECRET_KEY=dev-only-value .venv/bin/python3 app.py`) and verified in the browser:
  - [ ] Visiting `/profile` signed out redirects to `/login`
  - [ ] Signing in as `demo@spendly.com` / `demo123` lands on a profile page showing "Demo User", the email, total, this-month total, count, the category breakdown and five recent expenses, newest first
  - [ ] A freshly registered user sees the empty state with no errors
  - [ ] Clicking the nav name goes to `/profile`; "Add expense" goes to the placeholder
  - [ ] After "Sign out", the browser back button does not show the profile page content on reload
  - [ ] The layout is readable at 375px width and at desktop width, with no horizontal scroll
  - [ ] An expense with a 200-character description (insert one for the demo user) wraps inside its cell with no horizontal scroll at 375px width
- [ ] No hardcoded hex colours added: `git diff main -- static/css/style.css | grep -E '^\+.*#[0-9a-fA-F]{3,8}\b'` prints nothing, except lines that define variables inside the `:root` block
- [ ] `grep -n "password_hash" templates/profile.html` finds nothing, and no new db function selects `password_hash`
- [ ] `grep -nE "(SELECT|INSERT|UPDATE|DELETE)" app.py` finds no SQL
- [ ] `CLAUDE.md` marks Step 4 complete and no longer lists `/profile` as unprotected (done in Task 9; tick after it lands)
- [ ] `shasum spendly.db` before and after `pytest -q` is identical

**Extra checks from the design (sections 7 and 8):**
- Review each new `SELECT` in `database/db.py` for its `user_id` / `id` filter.
- `grep -n "|safe" templates/profile.html templates/base.html` prints nothing.
- Signed-in mobile (≤600px) nav: name and "Sign out" visible.
- Demo data dated later this month (conflict C8) sorts first in "Recent"; this is expected, not a bug.
- `git status` shows changes only in the files the spec lists.
- Known gaps stay as recorded and are not fixed here: no CSRF token, no rate limiting, `/expenses/*` placeholders public until Steps 7-9.

**Commit:** only if the sweep produces a change: `chore: final sweep fixes for profile`

---

## Task 9: CLAUDE.md update

**Goal:** the project guide matches the code.

**Change:** `CLAUDE.md` — mark Step 4 complete; document `/profile` (GET only, `login_required`, `Cache-Control: no-store`, vanished-user fallback), the `login_required` decorator, the helpers (`month_bounds`, `member_since`, `format_amount`, `category_share`) and the four new `database/db.py` functions; remove "`/profile` is not yet protected" from the known gaps and add the public `/expenses/*` placeholders; change the placeholder example from "Profile page — coming in Step 4" to a Step 7 one (conflict C9).

**ACs satisfied:** none.

**Test first:** none (documentation). Re-read the changed lines against the final code from Tasks 1 to 7.

**Commit:** `docs: document profile page in CLAUDE.md`

---

## AC coverage

| AC | Task | AC | Task |
| --- | --- | --- | --- |
| AC-1 | 4 | AC-14 | 6 |
| AC-2 | 5 | AC-15 | 6 |
| AC-3 | 4 | AC-16 | 5 (function level in 3) |
| AC-4 | 4 | AC-17 | 5 |
| AC-5 | 4 | AC-18 | 5 |
| AC-6 | 5 | AC-19 | 6 |
| AC-7 | 3 | AC-20 | 5 (nav half built in 1) |
| AC-8 | 2 | AC-21 | 5 |
| AC-9 | 6 | AC-22 | 4 |
| AC-10 | 6 (function level in 2) | AC-23 | 4 |
| AC-11 | 2 | AC-24 | 5 (function level in 3) |
| AC-12 | 6 | AC-25 | 5 (function level in 3) |
| AC-13 | 5 | | |

All 25 criteria are covered. Tasks 1, 7 and 9 own no AC; Task 8 re-verifies all of them.
