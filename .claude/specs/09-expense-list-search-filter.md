# Spec: Expense List with Search and Filter

## Overview

Give signed-in users one page, `GET /expenses`, that lists **all** of their own expenses, not just the five most recent ones on `/profile`. Rows are ordered newest first (`date DESC, id DESC`) and split into pages of 20. A `GET` filter form above the table narrows the list by category (one of the seven, or all), by an inclusive from-date / to-date range and by a case-insensitive substring search on the description. All four filters combine with AND. The page shows `Showing X-Y of Z`, the total amount of every matching row (all pages, not only the current one), Previous / Next links that keep the active filters, and two different empty states: one for a user with no expenses at all, one for filters that match nothing. The nav gets an "Expenses" link for signed-in users. The page is read-only: there are no edit or delete links yet (Steps 10-11 add them; see "Later steps"). It comes now because Step 7 lets users add as many expenses as they like, but the only place to see them is the five-row list on `/profile`. Step 8 (dashboard UI) is skipped for now, so this page reuses the existing look (`.expense-table`, `.recent-panel`, `.empty-state`, `.btn`, `.form-group`) and the `format_amount` filter.

## Scope and non-goals

**In scope**

- `GET /expenses` behind `@login_required`, with query parameters `category`, `date_from`, `date_to`, `q` and `page`.
- Two new read functions in `database/db.py`, sharing one filter clause.
- Pure helpers in `app.py` that normalise the query parameters and work out the page window.
- `templates/expenses.html`, an "Expenses" nav link in `base.html`, CSS for the filter bar and the pagination links.
- `tests/test_expense_list.py`, one test per AC.

**Non-goals (not in this step)**

- Edit and delete links or buttons (Steps 10-11). The placeholder routes `/expenses/<id>/edit` and `/expenses/<id>/delete` and their out-of-date strings are left exactly as they are.
- Any change to `/profile`, including a "View all" link from its recent list (left to Step 8; see "Later steps").
- The dashboard redesign (Step 8).
- Sorting by anything other than date then id; sortable columns.
- Searching category or amount text; full-text search; `pg_trgm` or any other extension.
- CSV export, per-page size chosen by the user, saved filters, JavaScript (the filter form is a plain `GET` form; `static/js/main.js` stays empty).
- Rate limiting (still a known gap, as in CLAUDE.md).
- Case-insensitive matching outside ASCII: how `ILIKE` folds non-ASCII letters depends on the database locale, so it is not specified or tested.

## Depends on

- Step 01 (database setup): the `expenses` table and the `idx_expenses_user_date` index.
- Step 03 (login and logout): sessions, `load_current_user`, `g.current_user`.
- Step 04 (profile): `login_required`, `format_amount`, the `.expense-table` / `.recent-panel` / `.empty-state` styles, the `<bdi>` description cell.
- Step 05 (PostgreSQL migration): psycopg 3, `%s` / `%(name)s` placeholders, `spendly_test`.
- Step 06 (add expense backend): `CATEGORIES`, `_DATE_RE`, `create_expense` (used by the tests to make rows).
- Step 07 (add expense form and CSRF): `no_store`, the CSRF hook (which this step must *not* trigger), the nav "Add Expense" link, `tests/helpers.py`.
- Step 08 (dashboard UI) is **not** required and is not built yet.

## Routes

- `GET /expenses` — the signed-in user's expense list with filters and pagination; `Cache-Control: no-store` — logged-in. Endpoint name `expense_list`.

Methods other than `GET`, `HEAD` and `OPTIONS` get Flask's 405 (Flask answers `OPTIONS` itself with 200 and an `Allow` header). A `POST /expenses` gets the 405 even without a token, because the CSRF hook skips requests that match no rule for their method (`request.endpoint is None`), as Step 7 AC-29 already shows for `/profile`. `/expenses/` (trailing slash) is a 404, as with every other route. `/expenses/add` is unchanged.

## Database changes

No schema changes. Verified against `database/db.py`: `_SCHEMA` already creates `idx_expenses_user_date ON expenses (user_id, date)` with `IF NOT EXISTS` (see D5), so `init_db()` and `_SCHEMA` are not edited.

New read functions in `database/db.py` (no writes):

- `get_filtered_summary(user_id, category, date_from, date_to, search) -> dict` returns one row `{"count": int, "total": Decimal}` for every matching row; `{"count": 0, "total": Decimal("0")}` when nothing matches (`COUNT(*)`, `COALESCE(SUM(amount), 0)`).
- `get_filtered_expenses(user_id, category, date_from, date_to, search, limit, offset) -> list[dict]` returns `id, amount, category, date, description`, ordered `date DESC, id DESC`, then `LIMIT %(limit)s OFFSET %(offset)s`.
- Argument types: `user_id: int`; `category: str | None` (already one of `CATEGORIES`, or `None` for all); `date_from` / `date_to: datetime.date | None`; `search: str | None` (the raw search text, **not** yet escaped; see D2); `limit` / `offset: int`.
- Both functions use the **same** private filter clause, so the count, total and rows can never disagree.
- The empty-state choice (`No expenses yet.` versus `No expenses match these filters.`) reuses `get_filtered_summary(uid, None, None, None, None)` for the user's unfiltered count. There is no third function.

## Templates

- **Create:**
  - `templates/expenses.html` extends `base.html`; title `Expenses - Spendly`; `<h1>Expenses</h1>`. In order:
    - **Filter form:** `<form method="GET" action="{{ url_for('expense_list') }}">` with **no** `csrf_token` field. Fields:
      - `category`: a `<select>` whose first option is `All categories` (`value=""`), then the seven `CATEGORIES` in order; the effective category is `selected`.
      - `date_from` and `date_to`: `type="date"`, `value` the effective date as `YYYY-MM-DD` or empty, labelled "From" and "To".
      - `q`: `type="search"`, `maxlength` `MAX_SEARCH`, `value` the effective search text or empty, labelled "Search description".
      - an "Apply" submit button and a "Clear filters" link to `url_for('expense_list')`.
    - **Results** (only when `Z > 0`): the line `Showing X-Y of Z` (ASCII hyphen, e.g. `Showing 21-25 of 25`) and the line `Total: ₹12,345.60` (`format_amount` of the filtered total). The markup may wrap parts of these lines, and of `Page N of M`, in elements: tests match them on the page text with tags stripped and whitespace collapsed.
    - **Table:** an `.expense-table` with columns Date, Category, Description, Amount, the same cells as `profile.html`: the date as `YYYY-MM-DD`, the description wrapped in `<bdi>`, `—` for a `NULL` description, the amount through `format_amount`. There is no Actions column yet.
    - **Pagination** (only when there is more than one page): a "Previous" link (left out on page 1), `Page N of M`, and a "Next" link (left out on the last page). The hrefs come from `prev_url` / `next_url` built in the view (D7).
    - **Empty states:** `No expenses yet.` with an "Add expense" link to `url_for('add_expense')` when the user has no expenses at all (with or without filters). `No expenses match these filters.` with a "Clear filters" link when the user has expenses but none match. Neither state shows the table, `Showing` or `Total`.
    - Values come only from Jinja expressions with autoescaping: no `|safe`, no `Markup`, no `{% autoescape false %}`, and no `style="..."` attributes or `<style>` blocks.
- **Modify:**
  - `templates/base.html`: the signed-in nav gets `<a href="{{ url_for('expense_list') }}" class="nav-expenses">Expenses</a>` **before** "Add Expense". Nothing else changes, and the signed-out nav is unchanged.

## Files to change

- `app.py`: the `PAGE_SIZE`, `MAX_SEARCH` and `_PAGE_RE` constants; the pure helpers `clean_expense_filters(args)` and `page_window(count, page, page_size)`; the `GET /expenses` view `expense_list`; imports of the two new db functions.
- `database/db.py`: `get_filtered_summary`, `get_filtered_expenses`, the shared private filter clause and `_like_pattern(text)`.
- `templates/base.html`: the nav link (above).
- `static/css/style.css`: styles for the filter bar, the results line and the pagination, plus `.nav-links .nav-expenses` styled like `.nav-add`. At 600px and below: the mobile rule `.nav-links a:not(.nav-cta):not(.nav-user):not(.nav-add)` gains `:not(.nav-expenses)` so no signed-in link is hidden, and `.nav-links` gets a smaller `gap` and `flex-wrap: wrap`, so the Expenses, Add Expense, user-name and Sign out items fit or wrap without horizontal overflow at 360px wide. Existing variables only; no hex outside `:root`.
- `CLAUDE.md`: document `/expenses`, the helpers, the db functions and decisions D1-D7; update the roadmap line ("Step 7 ... is this step") so it says Steps 1-7 and 9 are built and Step 8 is still to come.
- **Not changed:** `tests/conftest.py`, `tests/helpers.py`, every existing test file, `database/db.py`'s `_SCHEMA` / `init_db` / `seed_db`, `templates/profile.html`, `static/js/main.js`, the placeholder edit/delete routes, and the untracked `expense-tracker-frontend/` folder (not read, not modified, not staged).

## Files to create

- `templates/expenses.html`
- `tests/test_expense_list.py`: one test per acceptance criterion below, named `test_..._acN`.

## New dependencies

No new dependencies.

## Decisions

**D1. Invalid or tampered query parameters: ignore, never 400. One rule for every parameter.** Each parameter is stripped of surrounding whitespace and checked. A value that fails its check is treated as **absent** (its default), and the page renders with status 200. Only the first value of a repeated parameter is read (`request.args.get`). Unknown parameters (`user_id`, `sort`, `csrf_token`, ...) are ignored. Defaults: category all, no from-date, no to-date, no search, page 1. The one exception is a well-formed `page` that is out of range: it is **clamped** to the nearest real page (`page=0` → 1, `page=99` → the last page).
*Why:* the page is a read-only `GET` that writes nothing, so a bad value carries no risk. A 400 would throw away a bookmarked or hand-edited URL for nothing. The filter form is always re-rendered from the **effective** (normalised) values, not the raw ones, so a dropped filter shows up as an empty field and the user is never misled about what is applied. Ignoring also means no raw parameter (other than a valid `q`) is ever echoed into the page.
Checks:
- `category`: exactly one of `CATEGORIES` (case-sensitive, as in `validate_expense`); `""` means all.
- `date_from`, `date_to`: `_DATE_RE.fullmatch`, then `datetime.strptime(v, "%Y-%m-%d")`, so the value is a real calendar date with ASCII digits. There is no `MIN_EXPENSE_DATE` / tomorrow window: a filter only narrows the list.
- `q`: after stripping, it must be non-empty, at most `MAX_SEARCH` characters and contain no Unicode category `Cc` character. A NUL would make PostgreSQL raise `DataError` (a 500), and stored descriptions can never contain `Cc` (Step 6), so nothing matchable is lost.
- `page`: `_PAGE_RE = re.compile(r"[0-9]{1,9}")` with `fullmatch`, so ASCII digits only. `int()` on longer strings is never called (no huge-int work, and the OFFSET stays bounded); `"٢"`, `"1.5"`, `"-1"` and `""` are invalid.
- `date_from` later than `date_to`: both are kept, and the result is honestly empty (the "no matches" state). They are not swapped.

**D2. Literal search.** The search is a case-insensitive substring match: `description ILIKE %(pattern)s ESCAPE '\'`. In `database/db.py`, `_like_pattern(text)` escapes `\` first, then `%` and `_`, each prefixed with `\`, and wraps the result as `%...%`. The pattern is always passed as a parameter, never put into the SQL text. In Python the SQL literal is written so that PostgreSQL receives a single backslash (`ESCAPE '\'`, `standard_conforming_strings` on, the default). `NULL` descriptions never match. A search for `50%` matches only descriptions containing the characters `50%`.

**D2a. Fixed SQL text.** The filter clause is one fixed string with `NULL` guards and named placeholders, with no runtime composition:
`WHERE user_id = %(user_id)s AND (%(category)s::text IS NULL OR category = %(category)s) AND (%(date_from)s::date IS NULL OR date >= %(date_from)s) AND (%(date_to)s::date IS NULL OR date <= %(date_to)s) AND (%(pattern)s::text IS NULL OR description ILIKE %(pattern)s ESCAPE '\')`.
No f-string, `%` formatting, `.format()` or `+` ever puts a value into SQL. `user_id` always comes from `g.current_user["id"]`.

**D3. Constants in `app.py`.** `PAGE_SIZE = 20` (enough for a month of daily spending on one screen; matches `.expense-table` on a phone without endless scrolling) and `MAX_SEARCH = 100` (half of `MAX_DESCRIPTION`; long enough for any real phrase, short enough to bound the `ILIKE` work). The template's `maxlength` comes from `MAX_SEARCH`, never a second literal.

**D4. Filtered total.** `get_filtered_summary` returns `COALESCE(SUM(amount), 0)` as `Decimal` (`NUMERIC(12,2)`). It is never converted to `float` and is not rounded in SQL. It covers **every** matching row, not just the current page. It is shown as `Total: ` followed by `format_amount` (`₹12,345.60`, the existing filter, Indian-rupee sign, western comma grouping exactly as on `/profile`). It is shown only when `Z > 0`.

**D5. Index: none added.** `idx_expenses_user_date ON expenses (user_id, date)` already exists in `_SCHEMA` with `IF NOT EXISTS`. It serves `user_id = ?` plus the date range, and a backward scan gives rows in `date DESC` order. The `id DESC` tie-break needs a small sort within each user's rows, and the category / `ILIKE` filters are applied to that user's rows only, which is a small set per user. A leading-`%` `ILIKE` cannot use a btree anyway, and a trigram index would need the `pg_trgm` extension (a non-goal). `_SCHEMA` and `init_db` stay untouched.

**D6. `Cache-Control: no-store`** on every 200 from `/expenses`, through the existing `no_store()`. *Why:* the page is private financial data, and every signed-in page carries the session CSRF token in the nav sign-out form, so a shared or back-button cache must not keep it (the same rule as `/profile` and `/expenses/add`). The 200 path never writes the session (the token already exists from login), so no `Set-Cookie`.

**D7. Pagination links.** The view builds `prev_url` and `next_url` with `url_for("expense_list", page=n, **active)`, where `active` holds only the **effective, non-default** filters (`category`, `date_from` as ISO, `date_to` as ISO, `q`). `url_for` percent-encodes each value, and Jinja's attribute autoescaping then turns `&` into `&amp;` in the `href`. The template only outputs `{{ prev_url }}` / `{{ next_url }}`. It never joins query strings itself, never uses `|urlencode` on hand-built strings, and never uses `request.query_string` or `request.args` directly. The parameter names `date_from` / `date_to` (not `from` / `to`) are chosen because `from` is a Python keyword. It can only be passed to `url_for` as `**{"from": ...}`, which is awkward and easy to get wrong in both the view and the tests. Ignored or unknown parameters are never carried into a link.

**GET only, so no CSRF.** The route accepts only `GET` (and `HEAD`). The global CSRF hook checks only matched `POST`s, so it never runs for this page. The filter form is `method="GET"` and must **not** contain the CSRF token: a token in a `GET` form would end up in the URL, browser history and server logs.

## Rules for implementation

- No SQLAlchemy or ORMs
- Parameterised queries only, in `database/db.py` only; fixed SQL text (D2a); `user_id` always from `g.current_user["id"]`, never from a request parameter
- Passwords hashed with werkzeug (this step touches no passwords)
- Use CSS variables — never hardcode hex values (no hex outside `:root` in `style.css`)
- No inline styles: no `style="..."` attributes or `<style>` blocks in any template
- All templates extend `base.html`
- Emails are stripped and lowercased in application code before saving or looking up (the database CHECK requires lowercase); this step does no email lookups
- Login errors never reveal whether the email or the password was wrong (unchanged)
- Secrets such as the Flask secret key come from environment variables, never from the code
- Passwords and password hashes are never printed or logged
- Never print `DATABASE_URL`, `SPENDLY_TEST_DATABASE_URL` or the CSRF token in logs or error messages
- Application code never logs request arguments (no `logging`, `print` or `app.logger` call with `request.args` or any value from it). The Werkzeug dev server's own access log, which prints each request line with its query string, is outside this rule and outside the Definition of done; Step 12 covers the production log.
- Money stays `Decimal`, never `float`, in SQL results, in `app.py` and in the template; formatting only through `format_amount`
- Jinja autoescaping on every value; no `|safe`, no `Markup`, no `{% autoescape false %}`
- Descriptions are always wrapped in `<bdi>` (R4 decision from Step 7)
- `@login_required` sits below `@app.route("/expenses")`; the view reads no session key directly
- `clean_expense_filters(args)` and `page_window(count, page, page_size)` are pure (no request, no database) and unit tested. Return contracts:
  - `clean_expense_filters(args)` returns a `dict` with exactly the keys `category` (`str` or `None`), `date_from` and `date_to` (`datetime.date` or `None`), `q` (`str` or `None`) and `page` (the requested page as an `int`, at least 1; the clamp to the last page is not done here).
  - `page_window(count, page, page_size)` returns a `dict` with exactly the keys `page` (the clamped page, at least 1), `pages` (the page count, at least 1), `offset` (`(page - 1) * page_size`), `first` and `last` (the 1-based positions in `Showing first-last of count`). `first` and `last` are both 0 when `count` is 0.
- The empty-state choice uses the user's unfiltered count: `No expenses yet.` exactly when the user owns zero expenses; the extra unfiltered count is only needed when the filtered count is 0 and a filter is active
- Do not touch `expense-tracker-frontend/`
- Tests use `spendly_test` only; one test per acceptance criterion

## Error handling

| Action | Required result |
| --- | --- |
| `GET /expenses`, signed out | 302 to `/login` (no `next` parameter) |
| `GET /expenses`, session `user_id` no longer exists | Session cleared by `load_current_user`, 302 to `/login` |
| `GET /expenses`, signed in, valid or invalid parameters | 200 `text/html`, `Cache-Control: no-store`, no `Set-Cookie`; invalid parameters are ignored (D1); never 400 |
| Any parameter carrying SQL or HTML (`' OR 1=1 --`, `<script>`) | 200; treated as an invalid value, or as a literal search; no SQL error; only escaped text in the HTML |
| `q` containing NUL or another `Cc` character | Ignored (no search); 200, never a 500 |
| `page` beyond the last page | 200, clamped to the last page |
| `page` with zero matches | 200, page 1, the right empty state |
| `POST`, `PUT`, `DELETE /expenses` (with or without a token) | 405 (no CSRF 400; the hook does not run) |
| `GET /expenses/` | 404 |
| Any database error | Not caught; Flask 500 |

## Edge cases

- **Empty values:** `?category=&date_from=&date_to=&q=&page=` is the same as no parameters.
- **Extra whitespace:** `category=" Food "` works as `Food`; `q="  lunch  "` searches `lunch`; `q="   "` means no search. Whitespace *inside* `q` is kept.
- **Letter case:** `category=food` is invalid and ignored (all categories). The search is case-insensitive (`LUNCH` finds `Team lunch`).
- **Duplicates:** `?category=Food&category=Bills` uses `Food`. Two expenses with the same date are ordered by higher `id` first, so the order is total and no row repeats or vanishes between pages.
- **Boundaries:** both dates are inclusive. `date_from == date_to` gives that one day. `date_from > date_to` gives no matches. A user with exactly 20 expenses has one page and no pagination; 21 gives two pages.
- **Logged-out access:** a 302 to `/login`, with nothing read from the query string.
- **Repeated requests / refresh / back button:** `GET` with no side effects, so any number of repeats is safe. `no-store` means the back button refetches.
- **Rows added between the two queries** (count then page): accepted. The two autocommit reads can disagree by a row for one request. The next load is right.
- **Another user's data:** every query is filtered by the signed-in user's id. A `user_id` query parameter is ignored. A search that matches only another user's description finds nothing.
- **Descriptions** with `<script>`, `&` or a bidi override (U+202E) are shown escaped inside `<bdi>`. `NULL` descriptions show `—` and never match a search.
- **Search for `%`, `_` or `\`** matches those characters literally (D2). A search of 100 characters is applied; 101 is ignored.
- **Session predating Step 7** (holds `user_id` but no `csrf_token`): the first page view writes a token (`Set-Cookie`), as on every other signed-in page. This is accepted (Step 7 edge case).
- **Huge result sets:** the page size is fixed at 20, and the offset is at most `(pages - 1) * 20` after clamping.

## Conflicts with existing tests

No existing test should need to change. Checked on `main` at 273 collected tests:

- `tests/test_add_expense_form_csrf.py` AC-31 (every `POST` form carries the token): the new page has only the nav sign-out `POST` form, which already carries it. The filter form is `GET`, so it is out of that test's scope. No change.
- `tests/test_add_expense_form_csrf.py` AC-32 (`Add Expense` nav link present for signed-in users, absent for signed-out pages): the new link sits beside it and does not alter it. No change.
- `tests/test_profile.py:59` (regex for the `nav-user` link): unaffected by an extra sibling link. No change.
- No test asserts that `/expenses` is a 404, inspects `app.url_map` or counts nav links.
- Not a test, but a conflict to resolve: the mobile CSS rule hides every nav link except `.nav-cta`, `.nav-user` and `.nav-add`, so it would hide the new link; it gains `:not(.nav-expenses)` (see "Files to change").
- Not a test: CLAUDE.md's roadmap line still says "Step 7 ... is this step". It is updated (see "Files to change").

If the implementation makes any existing test fail, that is a bug in the implementation, not a reason to change the test. Any genuinely needed change must be listed in the design with its reason before it is made.

## Acceptance criteria and tests

Each criterion is one test in `tests/test_expense_list.py`, named `test_..._acN`. The file `import app` at module top (so the startup seed runs at collection time, before `isolated_db` drops the tables). Tests use the `spendly_test` PostgreSQL database (dropped and recreated before every test by `isolated_db` and `client`). They create users with `create_user()` and rows with `create_expense()`, sign in with a `login_as(client, uid)` helper that sets `session["user_id"]` and then calls `csrf_token(client)` from `tests/helpers.py`, and they never touch `spendly` or `spendly.db`. "The list" means the descriptions in the table body, in order. Link checks `html.unescape` the `href`, then compare `urllib.parse.parse_qs` of its query string. AC-10, AC-14, AC-19, AC-21 and AC-26 each loop over their values inside **one** test function (a plain `for` loop, no `pytest.mark.parametrize`), and each assertion message names the failing value (e.g. `assert resp.status_code == 200, f"page={value!r}"`), so each of these ACs collects as exactly one test and the total stays 309.

- **Backslashes and control characters:** the tests write `a\x00b`, `a\nb` and `\x7f` as Python escapes (a NUL, a line feed, a DEL). They write `C:\temp`, `100\%`, `\`, `\%` and `50%_\x` as raw strings (`r"C:\temp"`) or with doubled backslashes, so each contains a real backslash and never a tab or a `\x` escape. The spec text shows what each value really contains.
- **Query encoding:** every AC whose query values contain `%`, `&`, `#`, `+`, `<`, `>`, `\`, quotes, spaces, non-ASCII or control characters builds the request as `client.get("/expenses", query_string={...})`, so the client does the encoding. Literal URLs such as AC-29's `?q=50%25%20%26%20more` only show the encoded form.
- **Text matching:** checks on `Showing X-Y of Z`, `Total: ₹…` and `Page N of M` run on the page text with tags stripped and whitespace collapsed to single spaces, not on the raw HTML.

**Access and basics**

- **AC-1** Given no session, when `GET /expenses` is requested, then the response is 302 with `Location` `/login`.
- **AC-2** Given a signed-in user with no expenses, when `GET /expenses` is requested, then the status is 200, `Cache-Control` is `no-store`, no `Set-Cookie` is sent, the empty-state block shows `No expenses yet.` and, inside that block, a link to `/expenses/add` with the text `Add expense` (the nav's `Add Expense` link does not count), and the page has no `<table`, no `Showing` and no `Total:`.
- **AC-3** Given a signed-in user with expenses on 2026-03-01 (id order a, b), 2026-03-05 (amount `1234.50`) and 2026-02-10 (description `NULL`), when `GET /expenses` is requested, then the list is 2026-03-05, then b, then a (same date, higher id first), then 2026-02-10. Each row shows the date as `YYYY-MM-DD`, the category, the description inside `<bdi>`, and the amount through `format_amount` (the 2026-03-05 row shows `₹1,234.50`); the `NULL` description shows `—`.
- **AC-4** Given users A and B with their own expenses, including B's description `secret-b` in category Food, when A requests `/expenses`, `/expenses?q=secret-b`, `/expenses?category=Food` and `/expenses?user_id=<B's id>`, then no listed row (the table body) contains `secret-b`, and each `Z` and `Total:` counts only A's rows. The whole response is not checked, because the `q=secret-b` page rightly echoes the search into the search box.
- **AC-5** Given a session where `user_id` names a deleted user, when `GET /expenses` is requested, then the response is 302 to `/login` and the session no longer holds `user_id`.
- **AC-6** Given a signed-in user with no token sent, when `POST`, `PUT` and `DELETE /expenses` are requested, then each returns 405 (not the CSRF 400), and the `expenses` table is unchanged; and `GET /expenses/` (trailing slash) returns 404.
- **AC-7** Given a signed-in user, when `/profile`, `/expenses` and `/expenses/add` are fetched, then each has an `<a>` with `href="/expenses"` and text `Expenses`; and given no session, `/`, `/login` and `/register` have no such link.
- **AC-8** Given a signed-in user with expenses, when `GET /expenses` is requested, then the page has no link to `/expenses/<id>/edit` or `/expenses/<id>/delete`; its only `method="POST"` form is the nav sign-out form; the filter form is `method="GET"` and has no `csrf_token` input; and the category select's options are `All categories` (`value=""`) followed by the seven `CATEGORIES` in order.

**Filters**

- **AC-9** Given Food, Bills and Food expenses, when `?category=Food` is requested, then only the two Food rows are listed, `Showing 1-2 of 2` and the Food-only total are shown, and the Food option is `selected`.
- **AC-10** Given the same rows, when `category` is `food`, `Groceries`, `Food' OR '1'='1` and ` ` in turn, then each response is 200 with all three rows listed, and `All categories` is the selected option.
- **AC-11** Given expenses on 2026-03-31, 2026-04-01, 2026-04-30 and 2026-05-01, when `?date_from=2026-04-01&date_to=2026-04-30` is requested, then exactly the 2026-04-01 and 2026-04-30 rows are listed (both bounds inclusive), and the two date inputs carry those values.
- **AC-12** Given the same rows, when only `date_from=2026-04-30` is given, then 2026-04-30 and 2026-05-01 are listed; when only `date_to=2026-04-01` is given, then 2026-03-31 and 2026-04-01 are listed; and when `date_from=date_to=2026-04-01`, only that day is listed.
- **AC-13** Given the same rows, when `date_from=2026-05-01&date_to=2026-04-01` is requested, then the status is 200 and the page shows `No expenses match these filters.` with no table.
- **AC-14** Given the same rows, when `date_from` (and, separately, `date_to`) is each of `2026-02-30`, `2026-4-1`, `yesterday`, `2026-04-01T00:00`, `２０２６-04-01` and `0000-01-01`, then each response is 200 with all four rows listed, and that date input's `value` is empty.
- **AC-15** Given descriptions `Team lunch`, `LUNCHBOX`, `Dinner` and one `NULL`, when `?q=lunch` is requested, then exactly `Team lunch` and `LUNCHBOX` are listed; and when `?q=%20%20lunch%20%20` is requested, the same two are listed and the search input's `value` is `lunch`.
- **AC-16** Given descriptions `50% off shoes`, `500 rupees`, `5 0 %` and `Paid 50`, when `?q=50%` is requested, then only `50% off shoes` is listed.
- **AC-17** Given descriptions `a_b`, `axb`, `C:\temp`, `100\%` and `plain`, when `q` is `a_b`, then only `a_b` is listed; when `q` is `\`, then only `C:\temp` and `100\%` are listed; when `q` is `\%`, then only `100\%` is listed; and when `q` is `_`, then only `a_b` is listed.
- **AC-18** Given four expenses, one of them created in the setup with a 100-character description, when `q` is three spaces, then all four are listed and `No expenses match` is not shown. When `q` is 101 characters, then all four are listed and the search input's `value` is empty. When `q` is that 100-character description, then only that row is listed.
- **AC-19** Given expenses, when `q` is `a\x00b`, then `a\nb` and then `\x7f`, then each response is 200 (never 500) with all rows listed.
- **AC-20** Given rows that vary in category, date and description, when `?category=Food&date_from=2026-04-01&date_to=2026-04-30&q=lunch` is requested, then only the rows that pass all four filters are listed.
- **AC-21** Given users A (signed in) and B, where A has some descriptions that contain `%` and some that do not, and B's descriptions are unique tokens (e.g. `zq-b-7781`) that cannot appear anywhere else on the page (not category names, labels or nav text), when each of `category`, `date_from`, `date_to`, `q` and `page` is set in turn to each of `' OR 1=1 --`, `'; DROP TABLE expenses; --`, `<script>alert(1)</script>`, `%' OR '1'='1` and `%`, then every response is 200. No response contains B's descriptions or the raw `<script>alert(1)`. Afterwards the `users` and `expenses` row counts are unchanged and both tables still exist. For `q`, the injection strings are searched literally (`q=%` lists only A's descriptions containing `%`).

**Totals**

- **AC-22** Given 26 expenses (one of `0.10`, 24 of `1000.00` and one of `1234.50`), when `GET /expenses` (page 1) is requested, then the page shows `Total: ₹25,234.60`, the sum of all 26 rows, not just the 20 shown.
- **AC-23** Given a user with expenses `0.10` and `0.20` and another user with `5.00`, when `get_filtered_summary(uid, None, None, None, None)` is called, then it returns `count == 2` (an `int`) and `total == Decimal("0.30")` (a `Decimal`, not a `float`); and with `category="Bills"` it returns `count == 0` and `total == Decimal("0")`.

**Pagination**

- **AC-24** Given 25 expenses on distinct dates, when `GET /expenses` is requested, then 20 rows are listed (the 20 newest), the page shows `Showing 1-20 of 25` and `Page 1 of 2`, there is a Next link whose query is exactly `{"page": ["2"]}`, there is no Previous link, and `Cache-Control` is `no-store`.
- **AC-25** Given the same, when `?page=2` is requested (the last page), then the 5 oldest rows are listed, the page shows `Showing 21-25 of 25` and `Page 2 of 2`, there is a Previous link to page 1 and no Next link, and, since every row in the setup has a unique description, the descriptions listed on pages 1 and 2 together are exactly the 25 descriptions with no repeats (the page shows no ids).
- **AC-26** Given 25 expenses, when `page` is each of `0`, `-1`, `abc`, `1.5`, ` `, `٢` and `1234567890` in turn, then each response is 200 showing page 1 (`Showing 1-20 of 25`).
- **AC-27** Given 25 expenses, when `?page=99` is requested, then the status is 200 and it shows page 2 (`Showing 21-25 of 25`). And given a user with no expenses, `?page=5` gives 200 with `No expenses yet.`
- **AC-28** Given exactly 20 expenses, when `GET /expenses` is requested, then `Showing 1-20 of 20` is shown and there is no Previous link, Next link or `Page 1 of`; after one more expense is added, `Page 1 of 2` and a Next link appear.
- **AC-29** Given 25 Food expenses in April 2026 whose descriptions contain `50% & more`, when `?category=Food&date_from=2026-04-01&date_to=2026-04-30&q=50%25%20%26%20more` is requested, then the raw Next `href` contains `&amp;` and no bare `&`, and its unescaped query parses to exactly `{"category": ["Food"], "date_from": ["2026-04-01"], "date_to": ["2026-04-30"], "q": ["50% & more"], "page": ["2"]}`. Following it lists the remaining 5 rows, with all four filters still shown in the form.
- **AC-30** Given 25 expenses, when `?page=1&user_id=7&foo=bar&category=food&q=` is requested, then the Next link's query is exactly `{"page": ["2"]}`: unknown, invalid and empty parameters are never carried.

**Empty states and escaping**

- **AC-31** Given a user with no expenses, when `?q=anything&category=Food` is requested, then the page shows `No expenses yet.`, not `No expenses match these filters.`
- **AC-32** Given a user with only Bills expenses, when `?category=Food` is requested, then the empty-state block shows `No expenses match these filters.` and, inside that block, a `Clear filters` link to `/expenses`, and the page has no `<table`, `Showing` or `Total:`. The test looks inside the empty-state block, because the nav `Expenses` link and the filter form's own `Clear filters` link also point to `/expenses`.
- **AC-33** Given a stored description `"<script>alert(1)</script> & \u202eabc"`: on `GET /expenses`, the description appears as `"&lt;script&gt;alert(1)&lt;/script&gt; &amp; \u202eabc"` inside a `<bdi>` element and the raw `<script>alert(1)` appears nowhere in the body. On `GET /expenses` with `q=<b>x</b>` (which matches nothing, so no row is shown), the search input's `value` is `&lt;b&gt;x&lt;/b&gt;` and the raw `<b>x</b>` appears nowhere in the body. The test writes the bidi override as the Python escape `\u202e` in both strings, never as the raw character.

**Pure helpers**

- **AC-34** Given `MultiDict`s, when `clean_expense_filters` is called, then every result is a `dict` whose keys are exactly `{"category", "date_from", "date_to", "q", "page"}`, and:
  - `{}` gives `{"category": None, "date_from": None, "date_to": None, "q": None, "page": 1}`;
  - `category=[" Food ", "Bills"]` gives `"category": "Food"` (stripped, first value wins);
  - `date_from="2026-04-01"` gives `"date_from": date(2026, 4, 1)`;
  - a `q` of 100 characters is kept as `"q"`, while one of 101 characters, or one containing `\x00`, gives `"q": None`;
  - `page="3"` gives `"page": 3`, while `page="0"`, `"٣"` and `"1234567890"` each give `"page": 1`.
- **AC-35** Given counts and requested pages, when `page_window(count, page, 20)` is called, then every result is a `dict` whose keys are exactly `{"page", "pages", "offset", "first", "last"}`, and:
  - `(0, 1)` gives `{"page": 1, "pages": 1, "offset": 0, "first": 0, "last": 0}`;
  - `(25, 1)` gives `{"page": 1, "pages": 2, "offset": 0, "first": 1, "last": 20}`;
  - `(25, 2)` gives `{"page": 2, "pages": 2, "offset": 20, "first": 21, "last": 25}`;
  - `(25, 99)` gives the same as `(25, 2)`;
  - `(20, 2)` gives `{"page": 1, "pages": 1, "offset": 0, "first": 1, "last": 20}`;
  - `(21, 2)` gives `{"page": 2, "pages": 2, "offset": 20, "first": 21, "last": 21}`.
- **AC-36** Given the text `50%_\x`, when `_like_pattern` is called, then it returns `%50\%\_\\x%` (backslash escaped first, then `%` and `_`, wrapped in `%`).

## Later steps

- **Step 8 (dashboard UI)** will need to:
  - restyle `templates/expenses.html` along with `/profile` if it renames or replaces `.expense-table`, `.recent-panel`, `.empty-state`, `.btn` or `.form-group`, which this page reuses;
  - keep `format_amount` as the one money formatter (or change both pages together);
  - decide whether `/profile`'s "Recent expenses" panel gets a "View all" link to `url_for('expense_list')`;
  - keep the "Expenses" nav link (and its mobile-visible CSS rule) in any new nav.
  If Step 8 moves the list into a dashboard layout, AC-2/3/8/24-33 here are the regression net and must still pass.
- **Step 10 (edit expense)** adds an "Actions" column as the last column of the expenses table. Each row gets an "Edit" link to `url_for('edit_expense', id=e.id)`, shown only for the signed-in user's rows (they are the only rows listed). The edit route must check ownership itself and should return to `/expenses` with the same filters (it can pass the current query on to the form).
- **Step 11 (delete expense)** adds, in that same Actions cell, a small `method="POST"` form to `url_for('delete_expense', id=e.id)` that carries the hidden `csrf_token`, never a `GET` link. After that, AC-8's "only POST form is the nav sign-out form" changes on purpose, and the change must be listed in Step 11's conflicts.
- **Step 12 (deploy)** must configure the production access log (the WSGI server and any reverse proxy) so it does not record query strings, because `/expenses` URLs carry the user's search text and filters.

## Open questions

None. D1-D7 are decided above. The defaults you are most likely to want to change before the design are **page size 20** (D3), **out-of-range page clamped to the last page** rather than shown empty (D1), and **from-date after to-date shows "no matches"** rather than swapping the dates (D1).

## Definition of done

- [ ] All acceptance criteria pass with `.venv/bin/pytest -q`, together with the whole existing suite.
- [ ] `.venv/bin/pytest --collect-only -q` shows **309** tests: the 273 on `main` plus the 36 in `tests/test_expense_list.py` (AC-1 to AC-36, one test each).
- [ ] `git diff main --stat -- tests/` lists only `tests/test_expense_list.py`: `conftest.py`, `helpers.py` and every existing test file are unchanged.
- [ ] `git diff main -- database/db.py` adds only the new read functions and helpers; `_SCHEMA`, `init_db` and `seed_db` are unchanged.
- [ ] `git diff main -- templates/ | grep '^+' | grep -nE '\|safe|Markup|autoescape false|style=|<style'` finds nothing. Pre-existing exception, not touched by this step: `templates/landing.html` lines 51, 57 and 63 (`style="width: …%"` on the landing-page dashboard bars).
- [ ] `git diff main -- static/ | grep '^+' | grep -nE '#[0-9a-fA-F]{3,8}\b'` finds nothing (no new hex anywhere). Pre-existing exceptions outside `:root`, not touched by this step: `static/css/style.css` lines 255-257 (`.dot-red`, `.dot-yellow`, `.dot-green`), 335-337 (`.dashboard-bar-food`, `.dashboard-bar-travel`, `.dashboard-bar-bills`) and 496 (the `.auth-error` border `#f5c6c2`).
- [ ] `git diff main -- app.py database/db.py | grep '^+' | grep -nE 'float\('` finds nothing.
- [ ] `git diff main -- app.py database/db.py templates/ | grep '^+' | grep -nE 'logging|print\('` finds nothing. The Werkzeug dev server's access log is outside this check.
- [ ] No SQL in `database/db.py` is built with an f-string, `%` formatting, `.format()` or `+` that includes a value (checked by reading the diff); `grep -n "execute(f" database/db.py` finds nothing.
- [ ] `git status` shows `expense-tracker-frontend/` untouched (still untracked or ignored exactly as before, nothing from it staged).
- [ ] The app was run by hand (`SPENDLY_SECRET_KEY=dev-only-value .venv/bin/python3 app.py`) as `demo@spendly.com`, and each user-visible item was checked in the browser:
  - the "Expenses" nav link on desktop, and at 360px wide every signed-in nav item (Expenses, Add Expense, the user name, Sign out) visible, wrapping if needed, with no horizontal scroll;
  - newest-first order;
  - each filter alone and all four together;
  - `Showing X-Y of Z` and `Total:`;
  - Previous / Next keeping the filters (after adding 25+ expenses with `/seed-expenses`);
  - `?page=99` landing on the last page;
  - a search for `50%`;
  - both empty states;
  - the back button refetching (no stale page).
- [ ] The response headers for `/expenses` in the browser dev tools show `Cache-Control: no-store`, and no `Set-Cookie` on a normal page view.
- [ ] `CLAUDE.md` documents `/expenses`, the two db functions, the helpers and D1-D7, and its roadmap says Steps 1-7 and 9 are built, Step 8 is still to come.
