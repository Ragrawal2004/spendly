# Design: Step 4 — Profile

Companion to `04-profile.md`. Design only; no code. All four open questions take the spec's recommended defaults: the page is read-only, "this month" uses the server's UTC date, `₹` is hardcoded, and the expense placeholders stay unprotected.

## 1. `app.py`

**New imports:** `functools.wraps`, `math`, `datetime`/`timezone` (from `datetime`) and `make_response`, plus `get_user_profile`, `get_expense_summary`, `get_category_totals` and `get_recent_expenses`, imported by name like the Step 3 functions so tests can monkeypatch `app.get_user_profile` (AC-25).

**Order of definitions:** the new helpers and the decorator go after `inject_current_user` and before the routes section. `profile()` moves out of the placeholder section and sits after `logout()`. The three expense placeholders stay where they are, unchanged.

**`login_required(view)`**
- `@wraps(view)`. The inner function returns `redirect(url_for("login"))` if `not g.current_user`, otherwise `view(*args, **kwargs)`.
- It reads `g.current_user` with `getattr(g, "current_user", None)`. AC-23 calls it inside `test_request_context()`, where `before_request` does not run, so `g.current_user` may never have been set.
- The redirect target is fixed: no `next` parameter and nothing taken from the request.
- It is applied below `@app.route("/profile")`. Because of `wraps`, the endpoint name stays `profile`, so the existing `url_for("profile")` calls in `login()` and `register()` keep working.

**`month_bounds(today) -> (str, str)`** (pure): returns `today.replace(day=1)` and the first day of the next month, both as `isoformat()`. In December the next month is January of `year + 1`. It never uses `timedelta` arithmetic on day 31.

**`member_since(created_at) -> str | None`** (pure): `datetime.strptime(created_at, "%Y-%m-%d %H:%M:%S").strftime("%B %Y")`, catching `(TypeError, ValueError)` and returning `None`. `None` covers both NULL (`TypeError`) and `""`/`"garbage"` (`ValueError`). `%B` depends on the locale, but the default C locale gives "March".

**`format_amount(value) -> str`**, registered with `@app.template_filter("format_amount")`: returns `f"₹{value:,.2f}"`. `0.1 + 0.2` gives `₹0.30` and `12345678.9` gives `₹12,345,678.90`. It is a pure function, so it can also be unit tested.

**`category_share(total, overall) -> int`** (pure): returns `math.floor(total / overall * 100 + 0.5)`, or `0` when `overall` is 0. This is the only division, and it is guarded.

**`profile()`, GET only**
1. `@login_required` has already run, so `g.current_user` is a row.
2. `uid = g.current_user["id"]`. Nothing is read from `request.args`, the form or the session (AC-13).
3. `profile_row = get_user_profile(uid)`. If it is `None`: `session.clear()`, then `return redirect(url_for("login"))`.
4. `month_start, next_month_start = month_bounds(datetime.now(timezone.utc).date())`.
5. `summary = get_expense_summary(uid, month_start, next_month_start)`, `rows = get_category_totals(uid)`, `recent = get_recent_expenses(uid)`.
6. Build `categories = [{"category", "total", "count", "percent": category_share(row["total"], summary["total"])} ...]`. The percentages are computed in Python, not in Jinja.
7. Call `render_template("profile.html", user=g.current_user, member_since=member_since(profile_row["created_at"]), summary=summary, categories=categories, recent=recent)`. Wrap it in `make_response`, set `Cache-Control: no-store`, and return it.
- `profile_row` is used only for `created_at`. The name and email come from `g.current_user`, as the spec requires.
- Session writes happen only in the vanished-user branch, so a 200 response sends no `Set-Cookie`. The session is non-permanent, so Flask does not refresh the cookie (AC-17).

## 2. `database/db.py`

Four functions in the style of `get_user_by_id`: `with closing(get_db()) as conn:`, a parameterised `SELECT`, and `WHERE user_id = ?` (or `WHERE id = ?` for users) on every query. No schema change. The existing `idx_expenses_user_date` index covers the `user_id` filter and the date ordering.

| Function | SQL shape | Returns |
|---|---|---|
| `get_user_profile(user_id)` | `SELECT id, name, email, created_at FROM users WHERE id = ?` | `fetchone()`, Row or None |
| `get_expense_summary(user_id, month_start, next_month_start)` | `SELECT COALESCE(SUM(amount),0) AS total, COUNT(*) AS count, COALESCE(SUM(CASE WHEN date >= ? AND date < ? THEN amount END),0) AS month_total FROM expenses WHERE user_id = ?` | always one row (an aggregate with no `GROUP BY`) |
| `get_category_totals(user_id)` | `SELECT category, SUM(amount) AS total, COUNT(*) AS count ... WHERE user_id = ? GROUP BY category ORDER BY total DESC, category ASC` | `fetchall()` |
| `get_recent_expenses(user_id, limit=5)` | `SELECT id, amount, category, date, description ... WHERE user_id = ? ORDER BY date DESC, id DESC LIMIT ?` | `fetchall()` |

- The parameter order in the summary query is `(month_start, next_month_start, user_id)`, because the `CASE` placeholders come before `WHERE`. A wrong order would silently give a zero `month_total`, and AC-8 catches it.
- None of these functions selects `password_hash`. No rounding happens in SQL.

## 3. Templates

**`templates/profile.html`** extends `base.html`. `{% block title %}Profile - Spendly{% endblock %}`. Inside the content block, a `<section class="profile-section">` holds:
1. **`.profile-card`**: `user["name"]` in `.profile-name`, `user["email"]` in `.profile-email`, and `{% if member_since %}<p class="profile-since">Member since {{ member_since }}</p>{% endif %}`.
2. **`.profile-stats`**, three `.stat-tile`s: "Total spent" `{{ summary["total"]|format_amount }}`, "This month" `{{ summary["month_total"]|format_amount }}`, and the count `{{ summary["count"] }} {{ "expense" if summary["count"] == 1 else "expenses" }}` (see conflict C6).
3. **"By category"**: `{% if categories %}` with a `.category-row` per item (name, `total|format_amount`, `{{ c.percent }}%`). Nothing is rendered when the list is empty, so AC-9 can assert `category-row` is absent.
4. **"Recent expenses"**: `{% if recent %}` renders a `<table class="expense-table">` with Date, Category, Description and Amount columns. The description cell is `{{ e["description"] or "—" }}`, which covers NULL and `""` (AC-15). `{% else %}` renders `<p class="empty-state">No expenses yet.</p>`.
5. `<a href="{{ url_for('add_expense') }}" class="btn-primary">Add expense</a>`.
- No `|safe` anywhere, and all attribute values are quoted. The word "Profile" can appear in the page, but it never appears in a redirect body (AC-1).

**`templates/base.html`**: change `<span class="nav-user">` to `<a href="{{ url_for('profile') }}" class="nav-user">{{ current_user["name"] }}</a>`. The existing tests for AC-16 and AC-17 (the name appears and is escaped) still pass. See conflict C1 for the CSS this needs.

## 4. CSS (`static/css/style.css`)

Use existing variables only (`--paper-card`, `--border`, `--ink*`, `--accent`, `--accent-light`, `--radius-*`, `--font-display`, `--max-width`). No new colours are needed.
- `.profile-section`: `max-width: 840px`, centred, padding like the other page sections.
- `.profile-card`, `.stat-tile`: card look (`var(--paper-card)`, `1px solid var(--border)`, `var(--radius-md)`). Set `overflow-wrap: anywhere` on the name and email, so a 100-character name or a long email wraps.
- `.profile-stats`: `display: grid; grid-template-columns: repeat(3, 1fr)`, changing to `1fr` at ≤600px.
- `.category-row`: a flex row with `justify-content: space-between`, and the share in `var(--ink-muted)`.
- `.expense-table`: `width: 100%; table-layout: fixed; border-collapse: collapse`. Cells get `overflow-wrap: anywhere`, and the amount cell gets `white-space: nowrap; text-align: right`. At ≤600px, change rows to `display: block` (a stacked card per expense with the header row hidden), so four columns never force a horizontal scroll at 375px. Each `<td>` in `profile.html` gets a fixed `data-label` attribute (`data-label="Date"`, `"Category"`, `"Description"`, `"Amount"`). At ≤600px, `.expense-table td::before { content: attr(data-label); }` shows it, so stacked rows keep their column names. The labels are constant strings, never user data.
- `.empty-state`: `var(--ink-muted)`, centred.
- **Nav fixes** (conflict C1): change `.nav-user` to `.nav-links .nav-user { color: var(--ink); }` plus a hover underline. Narrow the ≤600px rule to `.nav-links a:not(.nav-cta):not(.nav-user)`. Give `.nav-user` `max-width` plus `overflow: hidden; text-overflow: ellipsis; white-space: nowrap`, so a 100-character name cannot push the nav off-screen on mobile.

## 5. Tests (`tests/test_profile.py`)

Helpers live in the file, copying `test_login_logout.py`:
- `_make_user(name, email)` calls `create_user(..., generate_password_hash("password123"))`.
- `login_as(client, uid)` uses `session_transaction`.
- `_add_expense(uid, amount, category, date, description=None)` does a parameterised insert through `closing(get_db())`.
- `_set_created_at(uid, value)` runs an `UPDATE`.

The `client` fixture calls `init_db()`. Tests that call the db functions directly need `init_db()` first, as `_make_user` does in the Step 3 file.

Notes per criterion:
- **AC-1, 3, 4, 22**: assert `status_code == 302` and `Location == "/login"`. Werkzeug returns relative Locations, as the existing `.endswith("/profile")` assertions show. AC-4 uses `client.set_cookie("session", "garbage")`.
- **AC-5**: `POST` gives 405. `PUT` and `DELETE` can be parametrized in.
- **AC-7, AC-23**: pure unit tests. AC-23 uses `app.test_request_context()` and sets `g.current_user` by hand. It covers both branches, uses a sentinel return value plus a `ran` flag, and checks `wrapped.__name__`.
- **AC-8**: dates `2026-10-01`, `2026-10-31`, `2026-11-01` and `2026-09-30`, with bounds `("2026-10-01", "2026-11-01")`.
- **AC-9**: assert `"category-row" not in body`.
- **AC-10**: assert the row tuples, and `"67%"` in the page.
- **AC-11**: two expenses on the same date, and check that the higher `id` comes first.
- **AC-12, 13**: two users with distinct descriptions and amounts.
- **AC-17**: assert `response.headers["Cache-Control"] == "no-store"` and `"Set-Cookie" not in response.headers`.
- **AC-19**: must call `seed_db()` itself, because the import-time seed only went to the `mkstemp` database. Then use `get_user_by_email("demo@spendly.com")["id"]` and `login_as`. Count `<tr` rows inside `<tbody>` only, so the header row in `<thead>` is not counted (5). Compute the expected total as `sum(row[2] for row in db._DEMO_EXPENSES_TABLE)` (`₹6,498.00` today) and the expected count as `len(db._DEMO_EXPENSES_TABLE)`. Neither value is hardcoded.
- **AC-20**: use an order-independent regex for an `<a>` tag containing both `href="/profile"` and `class="nav-user"`, plus `href="/expenses/add"`.
- **AC-21**: `client.post("/login", ..., follow_redirects=True)`, then assert 200 and the user's name.
- **AC-25**: parametrize `"garbage"` and `""` through `_set_created_at`. For `None`, monkeypatch `app.get_user_profile` with a fake whose `created_at` is `None`. The schema has `created_at NOT NULL`, so an `UPDATE` cannot store NULL (see C4).
- **Extra tests** (not ACs, but cheap): `format_amount` and `category_share` units (half-up: `12.5 → 13`, `0 overall → 0`), and the vanished-user branch (monkeypatch `get_user_profile` to return `None`, expect 302 and a cleared session).
- No existing test asserts the "coming in Step 4" placeholder text or follows a redirect to `/profile`, so no existing test needs changing.

## 6. Spec conflicts and resolutions

| # | Conflict | Resolution |
|---|---|---|
| C1 | Turning `.nav-user` into an `<a>` collides with existing CSS. The ≤600px rule `.nav-links a:not(.nav-cta) { display: none }` would hide the name on mobile, and `.nav-links a` (specificity 0,1,1) beats `.nav-user` (0,1,0), turning the name muted grey | Narrow the mobile rule and raise the `.nav-user` specificity (§4) |
| C2 | "Any non-GET method gives 405", but Flask adds `HEAD` and `OPTIONS` to every GET route automatically. `HEAD` behaves like GET (redirect or 200), and `OPTIONS` returns 200 | Accepted. AC-5 tests POST, PUT and DELETE only. Neither method exposes data a GET wouldn't |
| C3 | "The decorator is the only place that makes this check", but the spec also requires the route itself to redirect when `get_user_profile` returns `None`, and `login()` and `register()` already check `g.current_user` (the opposite case) | Read the rule as "the only *signed-out → login* gate based on `g.current_user`". The vanished-row branch is a separate, spec-mandated fallback |
| C4 | AC-25 lists `created_at` NULL, but the schema says `created_at TEXT NOT NULL` | Already handled by the spec's monkeypatch option. Use only the monkeypatch for `None` |
| C5 | AC-10 says "round(400 / 600 × 100)", but the rules forbid Python's `round()` and require `math.floor(x + 0.5)` | Use `math.floor`. Both give 67 here, so this is only a wording issue |
| C6 | The spec fixes "0 expenses" and "3 expenses" but says nothing about one | Render "1 expense". This doesn't affect any AC |
| C7 | The currency is `₹`, but the spec's format `₹12,345,678.90` uses Western grouping, not Indian lakh grouping (`₹1,23,45,678.90`) | Follow the spec (AC-16). Record this as a deliberate choice |
| C8 | `seed_db` dates demo expenses `today.replace(day=d)` for d up to 22, so on 2026-10-21 one demo expense is in the future. It still counts in "this month" and sorts first in "Recent" | Not a Step 4 bug. AC-19 checks only the count and the total. Mention it in the manual check |
| C9 | CLAUDE.md uses `"Profile page — coming in Step 4"` as its example placeholder | Change the example to the Step 7 placeholder when updating CLAUDE.md |

**Checked, no conflict:** `url_for("profile")` from Step 3 still resolves, because `wraps` keeps the endpoint name. AC-16 and AC-17 nav tests still pass with an `<a>`. `get_user_by_id` already omits the hash. The `client` and `isolated_db` fixtures need no change. `/expenses/add` exists, so `url_for('add_expense')` works.

## 7. Risks

- **Wrong user's data (high impact):** every query must filter by `user_id`, and the route must only ever use `g.current_user["id"]`. AC-12 and AC-13 guard this. Review each new `SELECT` for a missing `WHERE`.
- **Summary parameter order:** see §2. AC-8 catches it.
- **Division by zero:** handled only in `category_share`. AC-9 covers it.
- **XSS:** name, email and description are user data. Autoescape plus no `|safe` covers it. AC-14 checks.
- **Cached page after logout:** `no-store` is set only on the 200 response, and the browser must respect it. This is a manual DoD check.
- **Layout at 375px:** a long description, a large amount or a long nav name. The table stacking and nav ellipsis (§4) need a visual check in the browser.
- **UTC "this month":** near midnight, Indian users (UTC+5:30) may see the previous or next month's total. Accepted per the open-question default.
- **Float display:** `SUM` of REAL values can give `400.00000000001`. This is safe because `format_amount` rounds only for display. Never compare sums with `==` in tests. Assert formatted strings or use `pytest.approx`.
- **Known gap (unchanged):** the `/expenses/*` placeholders are still public until Steps 7-9.

## 8. Verification

- `.venv/bin/pytest -q`: the new `tests/test_profile.py` (AC-1 to AC-25 plus the extras) and the Step 1-3 suites all pass. Run `shasum spendly.db` before and after the run, and check the hash is unchanged.
- Manual: `SPENDLY_SECRET_KEY=dev-only-value .venv/bin/python3 app.py` and work through the spec's browser checklist: signed-out redirect, demo user page, empty state for a new user, nav link, back button after sign-out, 375px layout, and a 200-character description.
- Greps from the DoD: no SQL in `app.py`, no `password_hash` in `profile.html`, no new hex colours outside `:root`.
- Update CLAUDE.md: mark Step 4 complete, document `/profile`, `login_required`, the helpers and the four db functions, drop "`/profile` is not yet protected", and fix the placeholder example (C9).
- `git status` shows only the files the spec lists.


## 9. Build order

1. **Nav change first:** turn `.nav-user` into a link in `base.html`, together with the C1 CSS fixes. Run the full suite (`.venv/bin/pytest -q`) right away, before starting any other task. This is the only change that touches pages Steps 1-3 already test (AC-16 and AC-17 in `test_login_logout.py`).
2. **`database/db.py`, the four read functions, plus their tests:** AC-8, AC-10 (the row order from `get_category_totals`) and AC-11.
3. **`app.py`, the helpers, `login_required` and the `profile()` route, plus their tests:** AC-7, AC-23, the `format_amount` and `category_share` unit tests, the vanished-user test, and the requests that never render the page: AC-1, AC-3, AC-4, AC-5 and AC-22. `profile.html` does not exist until item 4, so tests that expect a 200 belong to item 4.
4. **`templates/profile.html` and the profile CSS, plus their tests:** AC-2, AC-6, AC-9, AC-10 (`67%` on the page), AC-12 to AC-21, AC-24 and AC-25.
5. CLAUDE.md update and the manual verification in §8.

In items 2-4, the tests go into `tests/test_profile.py` before or together with the code they cover. The full suite (`.venv/bin/pytest -q`) must be green before each item is committed.
