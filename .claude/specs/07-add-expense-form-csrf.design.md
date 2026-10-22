# Design: Add Expense Form and CSRF (Step 7)

Source: `.claude/specs/07-add-expense-form-csrf.md`. Branch `feature/add-expense-form-csrf` (checked: not `main`).
Verified on Flask 3.1.3 / Werkzeug 3.1.6 (`.venv`).

## 1. Signatures and placement (`app.py`)

No new imports (`secrets`, `make_response`, `session`, `timedelta` are already imported).

**CSRF block** — new, placed directly after the `startup()` call and **above** `load_current_user`
(Flask runs `before_request` functions in registration order = textual order; see C5):

```python
CSRF_ERROR = "Invalid or missing form token. Reload the page and try again."


@app.template_global("csrf_token")
def get_csrf_token():
    token = session.get("csrf_token")
    if not isinstance(token, str) or not token:
        token = secrets.token_urlsafe(32)
        session["csrf_token"] = token
    return token


# Registered before load_current_user, so a bad POST is rejected before any DB work or session.clear().
@app.before_request
def check_csrf_token():
    if request.method != "POST" or request.endpoint is None:
        return None
    expected = session.get("csrf_token")
    submitted = request.form.get("csrf_token")
    if (
        isinstance(expected, str) and expected
        and isinstance(submitted, str) and submitted
        and secrets.compare_digest(submitted.encode("utf-8"), expected.encode("utf-8"))
    ):
        return None
    return CSRF_ERROR, 400, {"Content-Type": "text/plain; charset=utf-8"}
```

- `@app.template_global("csrf_token")` mirrors the existing `@app.template_filter("format_amount")` and returns
  the function unchanged, so `get_csrf_token()` stays callable from Python.
- The hook only reads `session` (no write → no `Set-Cookie`; Flask adds `Vary: Cookie`), never logs, never echoes.
  Form body only — never `request.args` / headers.

**No-store helper** — next to `login_required`:

```python
def no_store(rv, status=200):
    resp = make_response(rv, status)
    resp.headers["Cache-Control"] = "no-store"
    return resp
```

Used by `GET /login` 200, `GET /register` 200, `GET /expenses/add` and its 400 re-render. `profile()` keeps its
existing inline header (no refactor of Step 4 code).

**Login change** (`app.py:249-251`):

```python
            session.clear()
            session["user_id"] = user["id"]
            get_csrf_token()  # fresh token for the new privilege level
            return redirect(url_for("profile"))
```

The 400/401 paths do not touch the token (AC-24). Logout is unchanged: `session.clear()` drops the token.

**GET pages:** `register()` GET → `return no_store(render_template("register.html"))`;
`login()` GET → `return no_store(render_template("login.html", registered=...))`. Signed-in redirects unchanged.

## 2. Templates and CSS

| File | Change |
|---|---|
| `base.html` | Signed-in nav: `<a href="{{ url_for('add_expense') }}" class="nav-add">Add Expense</a>` before `.nav-user`. Sign-out form gets `<input type="hidden" name="csrf_token" value="{{ csrf_token() }}">` as first child. |
| `login.html` | Same hidden input as first child of the form. |
| `register.html` | Same hidden input as first child of the form. |
| `profile.html` | Line 67 → `<td data-label="Description"><bdi>{{ e["description"] or "—" }}</bdi></td>`. Nothing else (the existing "Add expense" button stays). |
| `add_expense.html` (new) | See below. |

`add_expense.html` reuses the auth layout classes (`auth-section`, `auth-container`, `auth-header`, `auth-card`,
`auth-error`, `form-group`, `form-input`, `btn-submit`), plus `expense-form-section` on the section:

- `<form method="POST" action="{{ url_for('add_expense') }}">`, first child the hidden `csrf_token`.
- `amount`: `type="text" inputmode="decimal" maxlength="18" required autofocus value="{{ amount }}"`, label "Amount (₹)".
- `category`: `<select id="category" name="category" class="form-input form-select" required>`;
  `<option value="" disabled{% if category not in categories %} selected{% endif %}>Choose a category</option>`, then
  `{% for c in categories %}<option value="{{ c }}"{% if c == category %} selected{% endif %}>{{ c }}</option>{% endfor %}`
  (exact spacing so tests can match `<option value="Bills" selected>`).
- `date`: `type="date" value="{{ date_value }}" min="{{ min_date }}" max="{{ max_date }}" required`.
- `description`: `type="text" maxlength="{{ max_description }}"` (200), `value="{{ description }}"`, optional.
- `<button type="submit" class="btn-submit">Add expense</button>` and
  `<a href="{{ url_for('profile') }}" class="form-cancel">Cancel</a>`.
- `{% if error %}<div class="auth-error">{{ error }}</div>{% endif %}`. Autoescape only; no `|safe`, no `style=`.

CSS (`static/css/style.css`, existing variables only, no hex):

- `.nav-links .nav-add { color: var(--accent); font-weight: 500; }` + `:hover { color: var(--ink); }`.
- Mobile rule at `style.css:869` becomes `.nav-links a:not(.nav-cta):not(.nav-user):not(.nav-add)` (C10).
- `.form-select { background: var(--paper-card); cursor: pointer; }`.
- `.form-cancel { display: block; text-align: center; margin-top: 1rem; color: var(--ink-muted); }` + `:hover { color: var(--ink); }`.

## 3. Route changes (`add_expense`)

```python
def render_expense_form(today, status=200, error=None, amount="", category="", date_value=None, description=""):
    return no_store(
        render_template(
            "add_expense.html",
            error=error, amount=amount, category=category, description=description,
            date_value=today.isoformat() if date_value is None else date_value,
            categories=CATEGORIES,
            min_date=MIN_EXPENSE_DATE.isoformat(),
            max_date=(today + timedelta(days=1)).isoformat(),
            max_description=MAX_DESCRIPTION,
        ),
        status,
    )


@app.route("/expenses/add", methods=["GET", "POST"])
@login_required
def add_expense():
    today = datetime.now(timezone.utc).date()
    if request.method == "GET":
        return render_expense_form(today)

    amount, category, date_str, description = clean_expense(request.form)
    error, values = validate_expense(amount, category, date_str, description, today=today)
    if error:
        return render_expense_form(
            today, 400, error=error, amount=amount, category=category,
            date_value=date_str, description=description,
        )
    # create_expense / ForeignKeyViolation / 303 unchanged
```

`render_expense_form` sits directly above the route. `clean_expense`, `validate_expense`, `create_expense`
are untouched. The 400 path renders the nav, which calls `csrf_token()` — the token already exists (the request
passed the check), so no session write.

## 4. Existing test call sites (31) and helpers

New file `tests/helpers.py` (plain functions; imported with `from helpers import csrf_token, post_form` — see C12).
`tests/conftest.py` is not touched.

```python
import secrets


def csrf_token(client):
    with client.session_transaction() as sess:
        token = sess.get("csrf_token")
        if not token:
            token = secrets.token_urlsafe(32)
            sess["csrf_token"] = token
    return token


def post_form(client, url, data=None, **kwargs):
    data = dict(data or {})
    if "csrf_token" not in data:
        data["csrf_token"] = csrf_token(client)
    return client.post(url, data=data, **kwargs)
```

It reads the token fresh on every call, so a login in the middle of a test (rotation) and a logout (token gone,
helper makes a new one) both work. Copying `data` keeps parametrized dicts unmutated.

| File | `client.post` sites | Lines | Change |
|---|---|---|---|
| `test_add_expense.py` | 20 | 214, 225, 241, 265, 277, 289, 306, 318, 350, 367, 380, 384, 394, 399, 411, 426, 430, 454, 470, 475 | `post_form(client, url, data, ...)` (470 is `/login`, 475 keeps `follow_redirects=True`) |
| `test_login_logout.py` | 8 | 355 (`_post_login` helper), 405, 510, 579, 591, 615, 663, 728 | `post_form`; `/logout` calls become `post_form(client, "/logout")` |
| `test_profile.py` | 2 | 265 (`/logout`), 387 (`/login`, `follow_redirects`) | `post_form` |
| `test_registration.py` | 1 | 22 (`post` helper) | `post_form(client, "/register", {filtered data})` |
| **Total** | **31** | | Matches the spec. |

Not counted and left without a token on purpose: `test_profile.py:259` (`getattr(client, "post")("/profile")` → 405)
and `test_add_expense.py:341-342` (`put`/`delete` → 405).

`login_as` helpers (`test_add_expense.py:53`, `test_login_logout.py:295`, `test_profile.py:36`) keep setting
`user_id`, then call `csrf_token(client)`, leaving the session as a real login does.

Intentionally changed Step 6 ACs (`test_add_expense.py`):

| AC | Test | New assertion |
|---|---|---|
| AC-1 | `test_post_signed_out_redirects_ac1` | Sends a token via `post_form`; still 302 `/login`, no rows. |
| AC-12 | `test_invalid_post_plain_text_400_ac12` | 400, `Content-Type` starts `text/html`, `AMOUNT_FORMAT_ERROR in body`, no rows. |
| AC-13 | `test_error_does_not_echo_input_ac13` | 400; `&lt;script&gt;` and `&lt;b&gt;` in body; `<script>alert(1)` and `<b>1</b>` not in body. |
| AC-18 | `test_get_placeholder_protected_ac18` | Signed-out half unchanged; signed-in 200 has `name="amount"`, `name="category"`, `name="date"`, `name="description"`. |
| AC-27 | `test_description_control_chars_ac27` | Each bad value: 400 with `DESCRIPTION_CONTROL_ERROR in body`; table empty; `"Lunch\n"` half unchanged. |

Intentionally changed Step 3 ACs (`test_login_logout.py`, approved as C2):

| AC | Test | New assertion |
|---|---|---|
| AC-2 | `test_ac2_valid_login_redirects_to_profile_with_only_user_id` | `set(sess) == {"user_id", "csrf_token"}` and `sess["user_id"] == uid`. |
| AC-21 | `test_ac21_login_discards_other_session_data` | Same two assertions; `junk` is still proven dropped. |

So seven deliberate AC changes in total: Step 6 AC-1, AC-12, AC-13, AC-18, AC-27 plus Step 3 AC-2, AC-21.

## 5. Acceptance criteria → tests (`tests/test_add_expense_form_csrf.py`)

Local helper `_page_token(body)` reads `name="csrf_token" value="([^"]+)"`.

| AC | Test | AC | Test |
|---|---|---|---|
| 1 | `test_get_signed_out_redirects_ac1` | 19 | `test_logout_valid_token_ac19` |
| 2 | `test_get_renders_form_ac2` | 20 | `test_login_register_pages_issue_token_ac20` |
| 3 | `test_get_token_matches_session_no_store_ac3` | 21 | `test_token_is_per_session_ac21` |
| 4 | `test_invalid_amount_rerenders_values_ac4` | 22 | `test_login_rotates_token_ac22` |
| 5 | `test_rerender_escapes_input_ac5` | 23 | `test_token_dies_at_logout_ac23` |
| 6 | `test_rerender_other_field_errors_ac6` | 24 | `test_failed_login_keeps_token_ac24` |
| 7 | `test_end_to_end_real_pages_ac7` | 25 | `test_other_session_token_rejected_ac25` |
| 8 | `test_add_missing_token_ac8` | 26 | `test_malformed_tokens_rejected_ac26` |
| 9 | `test_add_wrong_token_ac9` | 27 | `test_absent_session_token_never_matches_ac27` |
| 10 | `test_add_valid_token_ac10` | 28 | `test_csrf_before_load_current_user_ac28` |
| 11 | `test_login_missing_token_ac11` | 29 | `test_405_and_404_not_checked_ac29` |
| 12 | `test_login_wrong_token_ac12` | 30 | `test_formless_pages_set_no_cookie_ac30` |
| 13 | `test_login_valid_token_ac13` | 31 | `test_every_post_form_has_token_ac31` |
| 14 | `test_register_missing_token_ac14` | 32 | `test_nav_add_expense_link_ac32` |
| 15 | `test_register_wrong_token_ac15` | 33 | `test_cf_descriptions_stored_in_bdi_ac33` |
| 16 | `test_register_valid_token_ac16` | 34 | `test_profile_after_real_login_no_set_cookie_ac34` |
| 17 | `test_logout_missing_token_ac17` | 35 | `test_login_register_no_store_ac35` |
| 18 | `test_logout_wrong_token_ac18` | | |

AC-27 sets `user_id` with a raw `session_transaction` (not `login_as`, which would add a token). AC-30 and AC-20 use
a fresh client with no helper calls. Expected count: 236 + 35 = 271.

## 6. Conflicts

- **C1 — Step 3 AC-15 (login while signed in).** No conflict. With `login_as` storing a token, `post_form` passes the
  hook; `login()` redirects signed-in users before rotating, so `user_id == uid_a` still holds. Only the `post_form` change.
- **C2 — Step 3 AC-2 and AC-21 assert `dict(sess) == {"user_id": uid}`** (`test_login_logout.py:496, 548`). After
  rotation the session also holds `csrf_token`, so both fail. **Resolution (approved):** change to
  `assert set(sess) == {"user_id", "csrf_token"}` and `assert sess["user_id"] == uid` (AC-21 still proves `junk` is
  dropped). Recorded in the spec's Conflicts section and Definition of done as two extra deliberate changes, next to
  the five Step 6 ACs.
- **C3 — Placeholder text.** Only `test_add_expense.py:334` (Step 6 AC-18) asserts it; changed per spec. No other test.
- **C4 — "No `Set-Cookie`" tests.** `test_profile.py:356` (Step 4 AC-17) and `test_add_expense.py:382, 386`
  (Step 6 AC-22) pass only if the session already holds a token when the nav (or the 400 re-render) calls
  `csrf_token()`. Resolved by the `login_as` change. `test_login_logout.py:567` (login sets a cookie) still holds.
- **C5 — `before_request` order.** Flask 3.1.3 `preprocess_request` iterates `before_request_funcs[None]` in
  registration order and stops at the first non-`None` return (verified). So `check_csrf_token` must be defined above
  `load_current_user`; a CSRF failure then skips `load_current_user` entirely (no DB query, no `session.clear()`).
- **C6 — `request.endpoint` on 404/405.** It is `None`, and `before_request` hooks still run for them (verified).
  The `endpoint is None` guard keeps `POST /no-such-page` → 404 and `POST /profile` → 405
  (`test_profile.py:259`, Step 3 AC-13, Step 6 AC-19 unchanged).
- **C7 — 413 inside the hook.** Flask `MAX_FORM_MEMORY_SIZE` defaults to 500000. The first `request.form` access moves
  from the view into the hook, so `RequestEntityTooLarge` is raised there; Flask returns 413, later hooks are skipped,
  no `Set-Cookie` (verified). Spec's "before any view" still holds. No existing test covers 413.
- **C8 — CLAUDE.md is outdated** on: session holds "only `user_id`"; add-expense 400 is plain text and "never echoes
  input"; R4 "open"; GET placeholder; "until Steps 8-9"; "no CSRF token" and "Do not deploy". Fixed in the docs task
  (deploy note removed last, after the CSRF tests and manual tamper check).
- **C9 — Step 3 AC-12 (logout twice, no session).** Works: logout clears the token, and `post_form` creates a new one
  on the second loop. No assertion change.
- **C10 — Mobile CSS hides nav links.** `style.css:869` hides every `.nav-links a` except `.nav-cta`/`.nav-user` at
  ≤600px, which would hide "Add Expense". Resolved by the `.nav-add` class and adding it to the `:not()` list.
- **C11 — Disabled placeholder option.** Spec says `disabled`; without `selected` too, browsers show "Food" as chosen.
  Resolved: `disabled` + `selected` when `category not in categories`, and `required` on the `<select>`.
- **C12 — Where the test helpers live.** The spec first placed them in `tests/conftest.py`; they now live in a new
  `tests/helpers.py` so `conftest.py` (guards and fixtures) stays untouched and test files never import `conftest`.
  `tests/` has no `__init__.py` and `pytest.ini` uses the default prepend import mode, so `tests/` is on `sys.path`
  and `from helpers import csrf_token, post_form` works. No name clashes in the four files; `helpers.py` holds no
  tests or fixtures, so pytest does not collect it (`python_files` default is `test_*.py`).
- **C13 — No-store scope.** Spec requires it only on the 200 `GET /login` / `GET /register`. Their 400/401 re-renders
  also carry the token, but responses to `POST` are not stored by default. Follow the spec; no extra headers.

## 7. Risks

- **Signed-in session without a token** (cookie from before this step, or a `login_as`-style session): the first page
  render writes a token, so that one `/profile` response sends `Set-Cookie`. A `POST` from a page rendered before the
  upgrade gets the CSRF 400; reloading fixes it. Accepted (spec edge case). Also: `load_current_user`'s
  `session.clear()` for a vanished user drops the token; the next page render makes a new one.
- **Token caching:** pages carrying the token are `no-store` (`/login`, `/register`, `/expenses/add`, `/profile`).
  Other signed-in pages (`/`, `/terms`, `/privacy`) carry it in the nav form without `no-store`, but Flask sends
  `Vary: Cookie` and a token is useless without its session cookie. Accepted; revisit at Step 12 deploy.
- **Plain-text 400 when the cookie is lost:** a user whose session cookie expired (browser restart, cleared cookies,
  or the dev server reloading with a random secret key) gets a bare text page on any form submit, even `/login`. It
  tells them to reload, but has no link. Mitigation: document running dev with `SPENDLY_SECRET_KEY`; accept the bare
  page (it cannot echo input and needs no token to render).

## 8. Task order

1. **Helpers and test updates, no behaviour change.** Create `tests/helpers.py` with `csrf_token`/`post_form`
   (`conftest.py` untouched); switch all 31 call sites; update the three `login_as`. The app ignores the extra field,
   so the suite stays green (236). C2 still passes here, because login's `session.clear()` drops the test-planted token.
2. **CSRF hook and protected routes.** `get_csrf_token` + template global, `check_csrf_token` above
   `load_current_user`, login rotation, hidden fields in `base.html`, `login.html`, `register.html`, `no_store` on
   `GET /login` and `GET /register`. Apply the C2 change (Step 3 AC-2, AC-21). Add tests AC-8 to AC-19.
3. **Token lifecycle and edge tests.** Add AC-20 to AC-31, AC-34, AC-35 (no app changes expected; any failure here is
   a task 2 bug).
4. **Form page.** `add_expense.html`, `render_expense_form`, GET and 400 path, nav link. Apply the Step 6 AC-12, 13,
   18, 27 changes. Add AC-1 to AC-7, AC-32.
5. **R4, CSS, docs.** `<bdi>` in `profile.html` + AC-33; CSS additions and mobile rule; CLAUDE.md (form, CSRF design,
   R4 closed, session contents, roadmap, "until Steps 10-11"). Then the full sweep: suite (271), DoD greps, the
   Verification checks below, and the manual browser checklist including the tamper check.
6. **Lift the deploy block.** Remove the "Do not deploy before Step 7" note and the "no CSRF token on any form" known
   gap from CLAUDE.md — only after the task 5 sweep and the manual tamper check have both passed.

## Verification

- `.venv/bin/pytest -q` (271 pass) and `.venv/bin/pytest --collect-only -q`.
- The DoD greps (`|safe`, `coming in Step 7`); `git diff main -- templates/ | grep -n '^+.*style='` finds nothing added (the three inline bar widths in `landing.html` predate this branch; Step 8 will handle them); `git diff main -- tests/... | grep '^-def test_'` empty;
  `git diff main -- tests/conftest.py` empty; `shasum spendly.db` unchanged.
- `grep -rn "<form" templates/` lists POST forms only in `base.html` (sign-out), `login.html`, `register.html` and
  `add_expense.html`. Any other POST form must get the hidden `csrf_token` field before the step is done.
- Every CSS variable used by the new rules (`--accent`, `--ink`, `--ink-muted`, `--paper-card`) is defined in `:root`
  of `static/css/style.css`: `grep -o "var(--[a-z0-9-]*)" static/css/style.css | sort -u` checked against the `:root`
  block, and no new hex values outside it.
- The manual checklist with `SPENDLY_SECRET_KEY=dev-only-value .venv/bin/python3 app.py`.
