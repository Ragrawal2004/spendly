# Design: Expense List with Search and Filter (Step 9)

Source: `.claude/specs/09-expense-list-search-filter.md`. Branch `feature/expense-list-search-filter` (checked: not `main`).
Verified against Flask 3.1.3, Werkzeug 3.1.6, psycopg 3.3.6 and pytest 8.3.5 in `.venv`.

## 1. `app.py`

**Imports:** add `get_filtered_expenses` and `get_filtered_summary` to the `from database.db import (...)` list, keeping alphabetical order (after `get_expense_summary`). No new stdlib imports are needed, because `date`, `datetime`, `re` and `unicodedata` are already imported.

**Constants:** add these directly under `_DATE_RE` (line 64):

```python
PAGE_SIZE = 20
MAX_SEARCH = 100
_PAGE_RE = re.compile(r"[0-9]{1,9}")
```

**Helpers and view:** placed after `add_expense()` and before the "Placeholder routes" banner, in this order. This follows the existing pattern of putting the helpers just above their route (`clean_registration` sits above `register`).

```python
def _filter_date(value):
    value = value.strip()
    if not _DATE_RE.fullmatch(value):
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None

def clean_expense_filters(args):
    category = args.get("category", "").strip()
    q = args.get("q", "").strip()
    if not q or len(q) > MAX_SEARCH or any(unicodedata.category(c) == "Cc" for c in q):
        q = None
    page = args.get("page", "").strip()
    return {
        "category": category if category in CATEGORIES else None,
        "date_from": _filter_date(args.get("date_from", "")),
        "date_to": _filter_date(args.get("date_to", "")),
        "q": q,
        "page": max(int(page), 1) if _PAGE_RE.fullmatch(page) else 1,
    }

def page_window(count, page, page_size):
    pages = max(1, (count + page_size - 1) // page_size)
    page = min(max(page, 1), pages)
    offset = (page - 1) * page_size
    first = offset + 1 if count else 0
    last = min(offset + page_size, count)
    return {"page": page, "pages": pages, "offset": offset, "first": first, "last": last}

@app.route("/expenses")
@login_required
def expense_list():
    uid = g.current_user["id"]
    filters = clean_expense_filters(request.args)
    criteria = (filters["category"], filters["date_from"], filters["date_to"], filters["q"])

    summary = get_filtered_summary(uid, *criteria)
    pager = page_window(summary["count"], filters["page"], PAGE_SIZE)
    expenses = []
    has_expenses = summary["count"] > 0
    if has_expenses:
        expenses = get_filtered_expenses(uid, *criteria, PAGE_SIZE, pager["offset"])
    elif any(value is not None for value in criteria):
        # Pick the empty state: does the user own any expenses at all?
        has_expenses = get_filtered_summary(uid, None, None, None, None)["count"] > 0

    # Only effective, non-default filters are carried into the page links (D7).
    active = {key: filters[key] for key in ("category", "q") if filters[key] is not None}
    for key in ("date_from", "date_to"):
        if filters[key] is not None:
            active[key] = filters[key].isoformat()
    prev_url = next_url = None
    if pager["page"] > 1:
        prev_url = url_for("expense_list", page=pager["page"] - 1, **active)
    if pager["page"] < pager["pages"]:
        next_url = url_for("expense_list", page=pager["page"] + 1, **active)

    return no_store(
        render_template(
            "expenses.html",
            filters=filters, summary=summary, pager=pager, expenses=expenses,
            has_expenses=has_expenses, prev_url=prev_url, next_url=next_url,
            categories=CATEGORIES, max_search=MAX_SEARCH,
        )
    )
```

Notes:
- `_filter_date` is a small private helper, so the two date checks are written once. Like the code in `validate_expense`, it uses `_DATE_RE.fullmatch` and then `strptime`. `0000-01-01` raises `ValueError` and gives `None`. `２０２６-…` fails the regex, because Python's `[0-9]` matches ASCII digits only.
- `int(page)` runs only after `_PAGE_RE` has matched at most 9 ASCII digits.
- None of the filter keys (`category`, `q`, `date_from`, `date_to`) clash with `url_for`'s reserved `_external`, `_anchor`, `_method` or `_scheme`.
- When `summary["count"]` is 0, `page_window` returns `first = last = 0` and `offset = 0`. The extra unfiltered count query runs only when no row matches and at least one filter is active.
- The view reads only `request.args` and `g.current_user["id"]`. It never writes the session, so a normal 200 sends no `Set-Cookie`.
- `GET` routes get `HEAD` and `OPTIONS` from Flask automatically. A `POST`, `PUT` or `DELETE` gets a 405, and the CSRF hook skips it because `request.endpoint is None` (Step 7 C6).

## 2. `database/db.py`

These are placed after `get_recent_expenses` and before `_DEMO_EXPENSES_TABLE`. `_SCHEMA`, `init_db` and `seed_db` are not touched.

```python
# Shared by the count/total and the page query so they can never disagree.
# ESCAPE '\\' in Python is ESCAPE '\' in SQL (standard_conforming_strings on).
_EXPENSE_FILTER = (
    "WHERE user_id = %(user_id)s "
    "AND (%(category)s::text IS NULL OR category = %(category)s) "
    "AND (%(date_from)s::date IS NULL OR date >= %(date_from)s) "
    "AND (%(date_to)s::date IS NULL OR date <= %(date_to)s) "
    "AND (%(pattern)s::text IS NULL OR description ILIKE %(pattern)s ESCAPE '\\') "
)

_FILTERED_SUMMARY_SQL = (
    "SELECT COUNT(*) AS count, COALESCE(SUM(amount), 0) AS total "
    "FROM expenses " + _EXPENSE_FILTER
)

_FILTERED_EXPENSES_SQL = (
    "SELECT id, amount, category, date, description "
    "FROM expenses " + _EXPENSE_FILTER
    + "ORDER BY date DESC, id DESC LIMIT %(limit)s OFFSET %(offset)s"
)

def _like_pattern(text: str) -> str:
    # Backslash first, so the escapes added for % and _ are not doubled.
    escaped = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"

def _filter_params(user_id, category, date_from, date_to, search) -> dict:
    return {
        "user_id": user_id,
        "category": category,
        "date_from": date_from,
        "date_to": date_to,
        "pattern": None if search is None else _like_pattern(search),
    }

def get_filtered_summary(
    user_id: int, category: str | None, date_from: date | None,
    date_to: date | None, search: str | None,
) -> dict:
    with closing(get_db()) as conn:
        return conn.execute(
            _FILTERED_SUMMARY_SQL,
            _filter_params(user_id, category, date_from, date_to, search),
        ).fetchone()

def get_filtered_expenses(
    user_id: int, category: str | None, date_from: date | None,
    date_to: date | None, search: str | None, limit: int, offset: int,
) -> list[dict]:
    params = _filter_params(user_id, category, date_from, date_to, search)
    params.update(limit=limit, offset=offset)
    with closing(get_db()) as conn:
        return conn.execute(_FILTERED_EXPENSES_SQL, params).fetchall()
```

**Full SQL text as PostgreSQL receives it.** psycopg 3.3.6 `_queries.py:224-240` was checked: a repeated `%(name)s` reuses the same `$n`.

```sql
-- get_filtered_summary
SELECT COUNT(*) AS count, COALESCE(SUM(amount), 0) AS total FROM expenses
WHERE user_id = $1
  AND ($2::text IS NULL OR category = $2)
  AND ($3::date IS NULL OR date >= $3)
  AND ($4::date IS NULL OR date <= $4)
  AND ($5::text IS NULL OR description ILIKE $5 ESCAPE '\')

-- get_filtered_expenses
SELECT id, amount, category, date, description FROM expenses
WHERE <same five lines>
ORDER BY date DESC, id DESC LIMIT $6 OFFSET $7
```

- The two `+` joins happen once, at import time, and join string literals only. No value ever enters the SQL text. Every value is a bound parameter.
- The f-string in `_like_pattern` builds a **parameter value**, not SQL. The DoD grep `execute(f` still finds nothing.
- Return types: `count` is an `int` (bigint) and `total` is a `Decimal`, with `Decimal("0")` from `COALESCE` when nothing matches. Rows are `dict`s, as from every other read.
- No new import is needed for the `date | None` type hints. `grep -n "^from datetime\|^import datetime" database/db.py` finds line 3, `from datetime import date, datetime, timezone`, so `date` is already imported. The new functions name their parameters `date_from` and `date_to`, so nothing shadows `date` (unlike `create_expense`, whose `date` parameter shadows it inside that function only).

## 3. `templates/expenses.html` (new)

```jinja
{% extends "base.html" %}

{% block title %}Expenses - Spendly{% endblock %}

{% block content %}
<section class="expenses-section">
    <h1 class="expenses-title">Expenses</h1>

    <form method="GET" action="{{ url_for('expense_list') }}" class="filter-bar">
        <div class="form-group">
            <label for="category">Category</label>
            <select id="category" name="category" class="form-input form-select">
                <option value=""{% if filters["category"] is none %} selected{% endif %}>All categories</option>
                {% for c in categories %}
                <option value="{{ c }}"{% if c == filters["category"] %} selected{% endif %}>{{ c }}</option>
                {% endfor %}
            </select>
        </div>
        <div class="form-group">
            <label for="date_from">From</label>
            <input type="date" id="date_from" name="date_from" class="form-input" value="{{ filters["date_from"] or "" }}">
        </div>
        <div class="form-group">
            <label for="date_to">To</label>
            <input type="date" id="date_to" name="date_to" class="form-input" value="{{ filters["date_to"] or "" }}">
        </div>
        <div class="form-group">
            <label for="q">Search description</label>
            <input type="search" id="q" name="q" class="form-input" maxlength="{{ max_search }}" value="{{ filters["q"] or "" }}">
        </div>
        <div class="filter-actions">
            <button type="submit" class="btn btn-primary">Apply</button>
            <a href="{{ url_for('expense_list') }}" class="btn btn-ghost">Clear filters</a>
        </div>
    </form>

    {% if summary["count"] > 0 %}
    <div class="results-bar">
        <p class="results-count">Showing {{ pager["first"] }}-{{ pager["last"] }} of {{ summary["count"] }}</p>
        <p class="results-total">Total: {{ summary["total"]|format_amount }}</p>
    </div>

    <table class="expense-table">
        <thead><tr><th>Date</th><th>Category</th><th>Description</th><th>Amount</th></tr></thead>
        <tbody>
            {% for e in expenses %}
            <tr>
                <td data-label="Date">{{ e["date"] }}</td>
                <td data-label="Category">{{ e["category"] }}</td>
                <td data-label="Description"><bdi>{{ e["description"] or "—" }}</bdi></td>
                <td data-label="Amount">{{ e["amount"]|format_amount }}</td>
            </tr>
            {% endfor %}
        </tbody>
    </table>

    {% if pager["pages"] > 1 %}
    <nav class="pagination" aria-label="Pages">
        {% if prev_url %}<a href="{{ prev_url }}" class="btn btn-ghost" rel="prev">Previous</a>{% endif %}
        <span class="pagination-status">Page {{ pager["page"] }} of {{ pager["pages"] }}</span>
        {% if next_url %}<a href="{{ next_url }}" class="btn btn-ghost" rel="next">Next</a>{% endif %}
    </nav>
    {% endif %}
    {% elif has_expenses %}
    <div class="empty-state">
        <p>No expenses match these filters.</p>
        <a href="{{ url_for('expense_list') }}" class="btn btn-ghost">Clear filters</a>
    </div>
    {% else %}
    <div class="empty-state">
        <p>No expenses yet.</p>
        <a href="{{ url_for('add_expense') }}" class="btn btn-primary">Add expense</a>
    </div>
    {% endif %}
</section>
{% endblock %}
```

**Exact text runs.** Each one is on one source line, with no whitespace around the hyphen:
- `Showing {{ first }}-{{ last }} of {{ count }}` renders as `Showing 21-25 of 25`.
- `Total: {{ total|format_amount }}` renders as `Total: ₹25,234.60`.
- `Page {{ page }} of {{ pages }}` renders as `Page 2 of 2`.

Other template details:
- The date inputs use `str(date)`, which is ISO `YYYY-MM-DD`, the same way `profile.html` renders `e["date"]`.
- `selected` matches the `add_expense.html` form (`<option value="Food" selected>`).
- Every value is autoescaped. There is no `|safe`, `Markup` or `style=`. The filter form is `GET` and has no `csrf_token`.
- Tests can find each empty-state block with `<div class="empty-state">(.*?)</div>` (DOTALL). The block contains no nested `div`.

**`templates/base.html`:** the signed-in branch, line 23, gets one new line above it:
`<a href="{{ url_for('expense_list') }}" class="nav-expenses">Expenses</a>`. Nothing else changes.

## 4. `static/css/style.css` (existing variables only, no hex)

| # | Where | Rule |
|---|---|---|
| 1 | line 119, the existing `.nav-add` rule | Becomes a grouped selector: `.nav-links .nav-add, .nav-links .nav-expenses { color: var(--accent); font-weight: 500; }` |
| 2 | line 121 | `.nav-links .nav-add:hover, .nav-links .nav-expenses:hover { color: var(--ink); }` |
| 3 | new "Expense list" section after `.profile-section .btn-primary` (line 781) | `.expenses-section { max-width: 960px; margin: 0 auto; padding: 3rem 2rem 4rem; }` |
| 4 | same | `.expenses-title { font-family: var(--font-display); font-size: 1.75rem; color: var(--ink); margin-bottom: 1.25rem; }` |
| 5 | same | `.filter-bar { display: grid; grid-template-columns: repeat(auto-fit, minmax(10rem, 1fr)); align-items: end; gap: 0.75rem 1rem; background: var(--paper-card); border: 1px solid var(--border); border-radius: var(--radius-md); padding: 1.25rem; margin-bottom: 1.5rem; }` |
| 6 | same | `.filter-bar .form-group { margin-bottom: 0; min-width: 0; }` |
| 7 | same | `.filter-actions { display: flex; flex-wrap: wrap; align-items: center; gap: 0.75rem; }` |
| 8 | same | `.results-bar { display: flex; flex-wrap: wrap; justify-content: space-between; gap: 0.25rem 1rem; margin-bottom: 0.75rem; font-size: 0.9rem; color: var(--ink-muted); }` |
| 9 | same | `.results-total { font-weight: 600; color: var(--ink); }` |
| 10 | same | `.pagination { display: flex; flex-wrap: wrap; justify-content: center; align-items: center; gap: 1rem; margin-top: 1.5rem; }` |
| 11 | same | `.pagination-status { font-size: 0.9rem; color: var(--ink-muted); }` |
| 12 | `@media (max-width: 600px)`, line 885 | The mobile rule becomes `.nav-links a:not(.nav-cta):not(.nav-user):not(.nav-add):not(.nav-expenses) { display: none; }` |
| 13 | same block | `.nav-links { gap: 0.5rem 1rem; flex-wrap: wrap; justify-content: flex-end; }`. This is the 600px wrap from the spec. |
| 14 | same block | `.nav-inner { height: auto; min-height: 60px; padding: 0.5rem 0; gap: 0.75rem; }`. This is needed for the wrap: `.nav-inner` has a fixed `height: 60px` (line 73), so a second row of links would spill out of the navbar. See C3. |
| 15 | same block | `.navbar { padding: 0 1rem; }`. This matches the 1rem mobile gutter that `.hero` and `.profile-section` already use, and gives the links 32px more room at 360px. |
| 16 | same block | `.expenses-section { padding: 2rem 1rem 3rem; }` and `.filter-bar { grid-template-columns: 1fr; padding: 1rem; }` |
| 17 | `@media (min-width: 900px)`, after line 996 | `.expenses-section .expense-table thead th { top: 60px; }`. The global sticky header (`top: 0`) would otherwise slide under the sticky 60px navbar on this long page. |

Checks on the table:
- Variables used: `--accent`, `--ink`, `--ink-muted`, `--paper-card`, `--border`, `--radius-md` and `--font-display`. All are defined in `:root`.
- At 360px the wide row is `Expenses` and `Add Expense` (about 163px). The user name (at most 8rem) and `Sign out` then wrap to a second line, and there is no horizontal scroll.

## 5. Tests and other files: what is affected

The grep `nav-add|nav-user|nav-expenses|_NAV_ADD_RE|nav-links|nav-signout|href="/expenses|.count(` was run over `tests/*.py`:

| Hit | What it asserts | Effect of this step |
|---|---|---|
| `test_add_expense_form_csrf.py:127` `_NAV_ADD_RE` | `<a … href="/expenses/add" …>Add Expense</a>` | None. The new `href="/expenses"` does not match `href="/expenses/add"`. Used at 620 (present on `/profile` and `/expenses/add`) and 625 (absent on `/`, `/login`, `/register`). |
| `test_profile.py:59` `NAV_PROFILE_LINK` | `<a>` with `href="/profile"` and `class="nav-user"` | None, because a sibling link is added. |
| `test_profile.py:383` | `'href="/expenses/add"' in body` | None. Still true through the nav and the profile button. |
| `test_add_expense_form_csrf.py:101` `_POST_FORM_RE` (AC-31) | Every `method="post"` form (case-insensitive) on 4 pages carries the token | None. `/expenses` is not in its page list, and the filter form is `GET`. |
| `test_add_expense_form_csrf.py:599` | `/expenses/add` has exactly 2 POST forms | None. No POST form is added to `base.html`. |
| `test_add_expense_form_csrf.py:584` (AC-30) | `/`, `/terms`, `/privacy` set no cookie | None. Signed out, the new link is not rendered. |
| `test_database.py:206` `.count("Food")` | A category list | Unrelated. |
| Nav link counts | — | **None found.** No test counts `<a>` elements or nav children. |
| `/expenses` 404 or `url_map` | — | None found. |
| `templates/profile.html:26` `<span class="stat-label">Expenses</span>` | (template, not a test) | AC-7 must match an `<a … href="/expenses" …>Expenses</a>` regex, not the bare text `Expenses`, or this span would count on `/profile`. |
| `tests/conftest.py`, `tests/helpers.py` | — | Unchanged. `test_expense_list.py` defines its own `login_as`, `_make_user`, `_add`, `_text` (tags stripped, whitespace collapsed), `_listed` (tbody descriptions in order) and `_link(body, label)` (unescaped `href`). |

New file `tests/test_expense_list.py`. It does `import app` at module top, has one test per AC and no `parametrize`, for 36 tests in all:

| AC | Test | AC | Test | AC | Test |
|---|---|---|---|---|---|
| 1 | `test_signed_out_redirects_ac1` | 13 | `test_reversed_dates_no_match_ac13` | 25 | `test_last_page_ac25` |
| 2 | `test_no_expenses_empty_state_ac2` | 14 | `test_invalid_dates_ignored_ac14` | 26 | `test_invalid_page_ac26` |
| 3 | `test_rows_newest_first_ac3` | 15 | `test_search_case_insensitive_ac15` | 27 | `test_page_clamped_ac27` |
| 4 | `test_only_own_rows_ac4` | 16 | `test_search_percent_literal_ac16` | 28 | `test_twenty_rows_one_page_ac28` |
| 5 | `test_vanished_user_redirects_ac5` | 17 | `test_search_underscore_backslash_ac17` | 29 | `test_next_link_keeps_filters_ac29` |
| 6 | `test_other_methods_405_ac6` | 18 | `test_search_length_limits_ac18` | 30 | `test_next_link_drops_junk_ac30` |
| 7 | `test_nav_expenses_link_ac7` | 19 | `test_search_control_chars_ac19` | 31 | `test_no_expenses_beats_no_match_ac31` |
| 8 | `test_read_only_page_ac8` | 20 | `test_filters_combine_ac20` | 32 | `test_no_match_empty_state_ac32` |
| 9 | `test_category_filter_ac9` | 21 | `test_injection_strings_harmless_ac21` | 33 | `test_escaping_ac33` |
| 10 | `test_invalid_category_ignored_ac10` | 22 | `test_total_covers_all_pages_ac22` | 34 | `test_clean_expense_filters_ac34` |
| 11 | `test_date_range_inclusive_ac11` | 23 | `test_filtered_summary_types_ac23` | 35 | `test_page_window_ac35` |
| 12 | `test_single_date_bounds_ac12` | 24 | `test_first_page_ac24` | 36 | `test_like_pattern_ac36` |

Expected count: 273 + 36 = **309**.

## 6. Conflicts

- **C1. The spec mentions `.btn` and `.recent-panel` as reused styles.**
  - `style.css` has **no `.btn` rule**. `btn` is only a hook class in `profile.html`, where the styling comes from `.btn-primary` and `.btn-ghost`. This page therefore uses `btn btn-primary` and `btn btn-ghost` in the same way.
  - `.recent-panel` is **not used**. At 900px and wider it carries dashboard-only rules (card padding sized for a `.recent-header`, `overflow: hidden`), and its partner `.recent-body` is a scroll box (`max-height: calc(100dvh - …)`) that would trap the 20 rows in an inner scroller above the pagination.
  - `.expense-table` already has its own card border and background, so the table stands alone.
  - Step 8's "restyle along with `.recent-panel`" note applies only to `.expense-table`, `.empty-state`, `.btn-*` and `.form-*` here.
- **C2. `.profile-section .btn-primary { margin-top: 1.5rem; }` (line 781).** Reusing `.profile-section` would push the Apply button and the empty-state button down. The page uses its own `.expenses-section` instead, with the same padding values.
- **C3. The spec's mobile nav change names only `gap` and `flex-wrap` on `.nav-links`.** That is not enough on its own: `.nav-inner` has a fixed `height: 60px`, so wrapped links would overflow the sticky navbar onto the page. Rules 14 and 15 are added and listed here as a deliberate addition.
- **C4. `profile.html` shows the text "Expenses" in a stat tile.** The AC-7 test must match the link element, not the text (see §5).
- **C5. CLAUDE.md is out of date on these points, and the docs task fixes each one:**
  - the roadmap still says "Step 7 … is this step";
  - the `no_store` users list lacks `/expenses`;
  - the `templates/` list lacks `expenses.html`;
  - the `database/db.py` paragraph lacks the two reads and `_like_pattern`;
  - the `app.py` route list lacks `/expenses`, `clean_expense_filters`, `page_window` and the constants;
  - D1-D7 are not documented.

  The "edit/delete placeholders stay public until Steps 10-11" note stays accurate, and their "coming in Step 8/9" strings are deliberately left as they are.
- **C6. `expense-tracker-frontend/` is git-*ignored* (`!!`), not untracked.** The DoD line "still untracked or ignored exactly as before" holds.
- No existing test needs to change.

## 7. Risks

- **Bind-parameter typing.** `$2 IS NULL` with no cast would raise `IndeterminateDatatype` when the value is `None`. The casts on the first use of each parameter (`::text`, `::date`) fix its type, and the second use reuses the same `$n`, so the types stay consistent. AC-11, AC-23 and AC-31 exercise both the `NULL` and the non-`NULL` branches.
- **Backslash escaping.** The Python literal `'\\'` has to reach PostgreSQL as `'\'`. A raw string or `'\\\\'` would send two backslashes, and PostgreSQL would raise "invalid escape string" (a 500). AC-16, AC-17 and AC-36 pin this. The setup also relies on `standard_conforming_strings = on`, the default since PostgreSQL 9.1.
- **Sticky navbar height on mobile.** With wrapping, the navbar can grow to about 100px on narrow screens. `.main-content`'s `min-height: calc(100vh - 60px - 100px)` is only a minimum, so this is cosmetic. Checked by hand at 360px.
- **Sticky table header.** Rule 17 assumes the navbar is 60px tall at 900px and wider, which holds because the wrap applies only at 600px and below.
- **Count and page queries can disagree** by a row if an expense is added between the two reads. This is accepted by the spec, and the next load is correct.
- **Search text in URLs.** It appears in the `prev_url` and `next_url` links (percent-encoded, with `&` written as `&amp;`), in browser history and in the Werkzeug dev access log. The production log is Step 12's job.
- **`ILIKE` on non-ASCII text** is locale-dependent. This is a non-goal and is not tested.
- **A session that predates Step 7** writes a token on first view, which sends one `Set-Cookie`. This is accepted, as in Step 7.

## 8. Task order

Each task ends with a green suite and is committed on its own.

1. **DB reads.** Add `_EXPENSE_FILTER`, `_like_pattern`, `_filter_params`, the two SQL constants and `get_filtered_summary` / `get_filtered_expenses` in `db.py`. Create `tests/test_expense_list.py` with its local helpers, plus AC-23 and AC-36. Expect 275.
2. **Pure helpers.** Add `PAGE_SIZE`, `MAX_SEARCH`, `_PAGE_RE`, `_filter_date`, `clean_expense_filters` and `page_window` in `app.py`, plus AC-34 and AC-35. Expect 277.
3. **Route, template and nav, built up in stages.** The view reaches its final form from §1 over three sub-tasks. Each stage's tests are added first, so each group starts red, and existing tests stay unchanged and green throughout. A few guard tests in a group can already pass before that stage's code exists; they are named below so a green guard test is not mistaken for a missing red one.
   - **3a. View with no filters, template and nav link.** The `expense_list` view ignores `request.args`. It calls `get_filtered_summary(uid, None, None, None, None)` and `get_filtered_expenses(uid, None, None, None, None, PAGE_SIZE, 0)`, gets its counts from `page_window(count, 1, PAGE_SIZE)` and renders `expenses.html` with the default `filters` dict, no `prev_url` or `next_url`, and `has_expenses` taken from the count. Add the full template from §3 and the `base.html` link. Add AC-1 to AC-8. Expect 285. All eight start red, because `/expenses` is a 404 before the route exists.
   - **3b. Filters, empty states, escaping.** The view reads `clean_expense_filters(request.args)` and passes the four criteria to both reads. Add the second, unfiltered count that picks between the two empty states. Add AC-9 to AC-21, AC-31, AC-32 and AC-33. Expect 301. AC-10, AC-14, AC-19 and AC-31 can pass before this stage's code, because 3a already ignores every parameter.
   - **3c. Totals and pagination.** The view uses the requested `filters["page"]`, clamps it through `page_window`, passes `pager["offset"]`, and builds `prev_url` and `next_url` from `active`. The template's pagination block then appears. Add AC-22 and AC-24 to AC-30. Expect 309. AC-22 (the total comes from the summary, built in 3a) and AC-26 (every page is page 1 until this stage) can pass before this stage's code.
4. **CSS.** Rules 1-17, then a manual check at desktop width and at 360px. Grep checks before committing:
   - `grep -n "nav-expenses" static/css/style.css` finds exactly three lines: rule 1, rule 2 and the mobile rule (rule 12).
   - `git diff HEAD -- static/ | grep '^+' | grep -nE '#[0-9a-fA-F]{3,8}\b'` finds nothing, so there is no new hex outside `:root`.
   - `git diff HEAD -- templates/ | grep '^+' | grep -n 'style='` and `grep -n 'style=' templates/expenses.html` find nothing.
5. **Docs.** Update `CLAUDE.md` to cover `/expenses`, the helpers, the db functions, D1-D7 and the roadmap ("Steps 1-7 and 9 are built; Step 8 is still to come").
6. **Definition of done.** This runs **only after task 5 is committed**, because the DoD greps diff against `main` (`git diff main -- …`), and a gap between the working tree and the last commit would hide or invent hits. The checks are:
   - `.venv/bin/pytest -q` and `--collect-only -q` (309);
   - `git diff main --stat -- tests/` (only `test_expense_list.py`);
   - `git diff main -- database/db.py` (reads only);
   - the `|safe`/`style=`, hex, `float(`, `logging|print(` and `execute(f` greps;
   - `git status` for `expense-tracker-frontend/`;
   - the manual browser checklist with `SPENDLY_SECRET_KEY=dev-only-value .venv/bin/python3 app.py` as `demo@spendly.com` (add 25+ rows with `/seed-expenses`), including the `no-store` header and the absence of `Set-Cookie` in dev tools;
   - at 360px wide, `/`, `/login`, `/register` and `/profile`, each both signed in and signed out (`/profile` signed out redirects to `/login`), with every nav item visible or wrapped, the navbar not overflowing onto the page and no horizontal scroll, because mobile navbar rules 14 and 15 apply to every page, not just `/expenses`.

The tasks file must name one mutation per guard test: for each guard test, the single code change that would make it fail.
