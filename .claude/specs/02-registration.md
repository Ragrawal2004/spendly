# Spec: Registration

## Overview

Make the existing `/register` page work. Today `GET /register` renders a form whose `POST` is not handled, so nobody can create an account. This step adds form handling: validate the input, normalise the email, hash the password with werkzeug, insert the user through `database/db.py`, and send the new user to the sign-in page. It is Step 2 of the roadmap and the first feature built on the data layer from Step 1. Login, sessions and logout come in Step 3, so registration does not sign the user in.

## Depends on

- Step 01 (database setup): `users` table, `get_db()`, `init_db()`, and the test fixtures in `tests/conftest.py`.

## Routes

- `GET /register` — render the empty registration form — public (unchanged behaviour)
- `POST /register` — validate the form, create the user, redirect to `/login?registered=1` on success; re-render the form with an error and HTTP 400 on failure — public
- `GET /login` — existing route; now also shows a success banner when the query string contains `registered=1` — public

## Database changes

No database changes. The `users` table already has everything needed (`name` non-blank check, `email` unique `COLLATE NOCASE`, `password_hash`, `created_at` default).

One new function in `database/db.py` so routes never touch raw SQL:

- `create_user(name, email, password_hash) -> int` — inserts one row with a parameterised `INSERT`, using `with closing(get_db()) as conn:` then `with conn:`, and returns the new id. It does not catch `sqlite3.IntegrityError`; the route handles it.

## Templates

- **Create:** none
- **Modify:**
  - `templates/register.html` — post to `url_for('register')`; re-fill `name` and `email` from the submitted values (never the password); add `minlength="8"` and `maxlength` attributes that match the server limits; add a "Confirm password" input (`type="password"`, `name="confirm_password"`, `autocomplete="new-password"`, `minlength="8"`, `maxlength="128"`), never re-filled
  - `templates/login.html` — show a success message when `registered` is set (for example "Account created. Please sign in.")

## Files to change

- `app.py` — `register()` accepts `GET` and `POST`; import `request`, `redirect`, `url_for`, `generate_password_hash`, `sqlite3`; `login()` passes the `registered` flag to the template
- `database/db.py` — add `create_user()`
- `templates/register.html`
- `templates/login.html`
- `static/css/style.css` — add an `.auth-success` banner next to `.auth-error`, using existing CSS variables only
- `tests/conftest.py` — add a `client` fixture
- `CLAUDE.md` — mark Step 2 complete

## Files to create

- `tests/test_registration.py`

## New dependencies

No new dependencies.

## Rules for implementation

- No SQLAlchemy or ORMs
- Parameterised queries only
- Passwords hashed with werkzeug (`generate_password_hash`)
- Use CSS variables — never hardcode hex values
- All templates extend `base.html`
- Emails are stripped and lowercased in application code before saving or looking up (SQLite NOCASE is ASCII-only)
- A helper `clean_registration(form) -> (name, email, password, confirm_password)` in `app.py` does all normalisation: `name` stripped; `email` stripped and lowercased; `password` and `confirm_password` untouched. A missing field becomes an empty string. Both the validation helper and `create_user()` receive its output (`create_user()` gets the cleaned name and email and the hash of the cleaned password); nothing re-reads the raw form.
- Login errors never reveal whether the email or the password was wrong (nothing to change in this step, but do not add any login logic that breaks this)
- Secrets such as the Flask secret key come from environment variables, never from the code. This step needs no session or flash, so it must not introduce a secret key.
- Passwords and password hashes are never printed or logged
- Route code calls `create_user()`; no SQL in `app.py`
- Validation lives in one helper in `app.py` that returns an error string or `None`, so it can be tested without a request
- Limits: name 1–100 characters after stripping; email at most 254 characters and must contain no whitespace, exactly one `@` with non-empty text on both sides, and a `.` in the domain part; the domain must not start or end with a dot; password 8–128 characters. Passwords are not stripped or altered.
- The validation helper checks in this order and returns the first error: name, email, password length, then `password != confirm_password` ("Passwords do not match.").
- Jinja autoescaping stays on; never use `|safe` on user input
- Template attribute values from user input are always quoted
- The redirect after success is `redirect(url_for('login', registered=1))` (HTTP 302). Do not redirect to a user-supplied URL.

## Error handling

| Action | Required result |
| --- | --- |
| `name` empty or only whitespace | HTTP 400, form re-rendered, error "Please enter your name." |
| `name` longer than 100 characters | HTTP 400, error "Name must be 100 characters or fewer." |
| `email` empty or not a plausible address | HTTP 400, error "Please enter a valid email address." |
| `email` longer than 254 characters | HTTP 400, same error as above |
| `password` shorter than 8 characters | HTTP 400, error "Password must be at least 8 characters." |
| `password` longer than 128 characters | HTTP 400, error "Password must be 128 characters or fewer." |
| `password` and `confirm_password` differ (including `confirm_password` missing or empty) | HTTP 400, error "Passwords do not match." No row is created. |
| Email already registered (any letter case): `create_user()` raises `sqlite3.IntegrityError` | HTTP 400, error "An account with this email already exists." No new row is created. This is the only duplicate detection; there is no separate lookup before the insert. |
| Any other database error | Not caught; Flask returns HTTP 500 and nothing is written |
| A required field is missing from the POST body | Treated as an empty value (HTTP 400 with that field's error), never a `KeyError` or 400 from Werkzeug |
| Success | HTTP 302 to `/login?registered=1`; exactly one new row in `users` |

Validation rejects blank names first and the hash is never null, so an `IntegrityError` from `create_user()` can only mean a duplicate email.

On every error the submitted `name` and `email` are put back in the form; the password and confirm password fields are always empty.

## Edge cases

- Empty or whitespace-only values for each field, and fields missing from the POST entirely
- Email with surrounding spaces (`"  Rahul@Example.com "`) is stored as `rahul@example.com`
- Duplicate email differing only in case (`A@x.com` vs `a@x.com`) is rejected
- Duplicate email with leading or trailing spaces is rejected
- Non-ASCII emails (`É@x.com` vs `é@x.com`) collide because the application lowercases them before saving, even though SQLite NOCASE would not
- Name with surrounding spaces is stored stripped; inner spaces are kept
- Password with leading or trailing spaces is stored exactly as typed (hash of the untrimmed value)
- Password of exactly 8 and exactly 128 characters is accepted; 7 and 129 are rejected
- HTML or script in the name (`<script>alert(1)</script>`) is stored as plain text and shown escaped
- Repeated submit (double click or browser reload of the POST): the second request hits the duplicate-email path, shows the error, and creates no second row
- `GET /register` after a failed POST shows an empty form
- Logged-out access: `/register` and `/login` are public. No protected pages are added in this step.
- Unicode normal forms (é as one character vs e plus a combining accent) are treated as different emails; known limit.
- The form uses POST only; a `GET /register?email=...` must not create a user
- A confirm_password that differs from password only by leading or trailing spaces is a mismatch (neither value is stripped).

## Acceptance criteria and tests

In every acceptance criterion, a POST includes a confirm_password equal to password, unless the criterion says otherwise.

Each criterion is one test in `tests/test_registration.py`. Tests use temporary databases through the `SPENDLY_DB` environment variable (the existing autouse fixture), call `init_db()` after the fixture has set the path, and never touch the real `spendly.db`.

- **AC-1** Given an initialised empty database, when `GET /register` is requested, then the status is 200 and the page contains fields named `name`, `email` and `password`.
- **AC-2** Given valid input (`Rahul Sharma`, `rahul@example.com`, `password123`, `confirm_password` `password123`), when the form is POSTed, then the response is a 302 to `/login?registered=1` and `users` has exactly 1 row with that name and email.
- **AC-3** Given a successful registration, when the stored `password_hash` is read, then it is not `password123` and `check_password_hash(hash, "password123")` is true.
- **AC-4** Given the email `"  Rahul@Example.COM "`, when the form is POSTed, then the stored email is `rahul@example.com`.
- **AC-5** Given an existing user `rahul@example.com`, when `RAHUL@example.com` is POSTed, then `create_user()` raises `sqlite3.IntegrityError` (no prior lookup), the status is 400, the page shows "An account with this email already exists.", and `users` still has 1 row.
- **AC-6** Given an existing user `rahul@example.com`, when `" rahul@example.com "` is POSTed, then the cleaned email matches the existing row and the result is the same as AC-5.
- **AC-7** Given names `""`, `"   "` and `"\t\n"`, when each is POSTed with otherwise valid data, then each returns 400 with "Please enter your name." and no row is created.
- **AC-8** Given a 101-character name, when POSTed, then the status is 400 with the name-length error; given a 100-character name, then it is accepted.
- **AC-9** Given emails `""`, `"plain"`, `"a@"`, `"@b.com"`, `"a@b"`, `"a@@b.com"`, `"a b@c.com"`, `"a@.com"` and `"a@b.com."`, when each is POSTed, then each returns 400 with "Please enter a valid email address." and no row is created.
- **AC-10** Given passwords of 7 and 129 characters (each with a matching `confirm_password`), when each is POSTed, then each returns 400 with the matching password error; given passwords of 8 and 128 characters, then each is accepted (separate emails).
- **AC-11** Given a POST with the `password` field missing entirely, when it is sent, then the status is 400 with the password error and no exception is raised.
- **AC-12** Given a failed POST with name `Asha` and email `asha@example.com`, when the page is rendered, then both values appear in the form inputs and the submitted password does not appear anywhere in the HTML.
- **AC-13** Given a POST with name `<script>alert(1)</script>` and a 7-character password with a matching `confirm_password`, when it is sent, then the status is 400 and the response HTML contains the escaped text and not a raw `<script>` tag.
- **AC-14** Given the same valid form POSTed twice in a row, when both responses are read, then the first is 302, the second is 400 with the duplicate-email message (raised by `create_user()` as `sqlite3.IntegrityError`), and `users` has exactly 1 row.
- **AC-15** Given `app.create_user` is monkeypatched to raise `sqlite3.IntegrityError`, when a valid form is POSTed, then the status is 400 with the duplicate-email message and no exception escapes; this is the only path that produces that message.
- **AC-16** Given `GET /login?registered=1`, when the page is requested, then it shows the success message; given `GET /login`, then it does not.
- **AC-17** Given a successful registration, when the application log output and response body are inspected, then neither contains the password or the hash.
- **AC-18** Given a user created by POSTing `É@x.com` through the route, when `é@x.com` and `É@X.COM` are each POSTed, then each returns 400 with the duplicate-email message and `users` still has 1 row.
- **AC-19** Given the password `"  password123  "` (leading and trailing spaces) and an identical `confirm_password`, when the form is POSTed, then `check_password_hash(hash, "  password123  ")` is true and `check_password_hash(hash, "password123")` is false.
- **AC-20** Given the name `"  Rahul Sharma  "`, when the form is POSTed, then the stored name is `Rahul Sharma`.
- **AC-21** Given `GET /register?name=Rahul&email=rahul@example.com&password=password123&confirm_password=password123`, when it is requested, then the status is 200 and `users` has 0 rows.
- **AC-22** Given valid name, email and password with a different `confirm_password`, when the form is POSTed, then the status is 400 with "Passwords do not match." and no row is created.
- **AC-23** Given a POST with the `confirm_password` field missing entirely, when it is sent, then the result is the same as AC-22 and no exception is raised.
- **AC-24** Given matching `password` and `confirm_password`, when the form is POSTed, then registration succeeds as in AC-2.
- **AC-25** Given any failed POST, when the page is rendered, then the `confirm_password` input has no value in the HTML and the submitted password does not appear anywhere in it.

## Open questions

1. **Where does a new user go after registering?** Recommended default: redirect to `/login?registered=1` with a success banner, because sessions do not exist until Step 3. Alternative: auto sign-in, which needs the session work from Step 3 first.
2. **Reveal that an email is already registered?** Recommended default: yes, show "An account with this email already exists." It is the normal sign-up experience and the user needs to know. The cost is that anyone can test whether an email has an account. Alternative: a generic message, which is worse for real users.
3. **Add a "confirm password" field?** Answer: yes. Add a second password field named `confirm_password`.
4. **CSRF protection?** The project has no CSRF library and no secret key yet. Recommended default: defer to Step 3 together with sessions and `SPENDLY_SECRET_KEY`, and note it as a known gap. Alternative: add Flask-WTF now (new dependency, secret key needed).
5. **Password rules beyond length?** Recommended default: length only (8–128), no composition rules.
6. **Name and email length limits** (100 and 254) are my choice, not in the schema. Recommended default: keep them.
7. **Rate limiting?** There is none yet, so registration can be scripted at any speed. Deferred as a known gap; revisit after sessions exist in Step 3.

## Definition of done

- [ ] All acceptance criteria AC-1 to AC-25 pass with `pytest -q`, and the existing database tests still pass
- [ ] The app was run by hand (`.venv/bin/python3 app.py`, port 5001) and each of these was verified in the browser: successful registration lands on the sign-in page with the success banner; the same email again (in different letter case) shows the duplicate error; an empty name, a bad email and a 7-character password each show their message; the form keeps name and email after an error but not the password
- [ ] Opening `spendly.db` shows the new row with a hashed password and a lowercase, stripped email
- [ ] `grep -nEi "select|insert" app.py` finds no SQL in `app.py`
- [ ] `git diff -U0 static/css/style.css | grep -E "^\+.*#[0-9a-fA-F]{3,8}"` prints nothing (no new hard-coded colours in the added rules)
- [ ] No password or hash appears in the terminal output of the running app during the manual run
- [ ] `git status` shows changes only in the files listed under "Files to change" and "Files to create"
