---
description: Create a spec file and feature branch for the next Spendly step
argument-hint: "Step number and feature name e.g. 2 registration"
allowed-tools: Read, Write, Glob, Bash(git:*)
disable-model-invocation: true
---

You are a senior developer spinning up a new feature for the
Spendly expense tracker. Always follow the rules in CLAUDE.md.

User input: $ARGUMENTS

## Step 1 — Check the working directory and current branch
Run `git status` and check for uncommitted, unstaged, or
untracked files. If any exist, stop immediately and tell
the user to commit or stash changes before proceeding.
DO NOT CONTINUE until the working directory is clean.

Then run `git branch --show-current`. If the current branch
is not `main` and has commits that are not merged into main,
tell the user which branch it is and stop, so no work is
left behind.

## Step 2 — Parse the arguments
From $ARGUMENTS extract:

1. `step_number` — zero-padded to 2 digits: 2 → 02, 11 → 11

2. `feature_title` — human readable title in Title Case
   - Example: "Registration" or "Login and Logout"

3. `feature_slug` — git and file safe slug
   - Lowercase, kebab-case
   - Only a-z, 0-9 and -
   - Maximum 40 characters
   - Example: registration, login-logout

4. `branch_name` — format: `feature/<feature_slug>`
   - Example: `feature/registration`

If you cannot infer these from $ARGUMENTS, ask the user
to clarify before proceeding.

## Step 3 — Check branch name is not taken
Run `git branch` to list existing branches.
If `branch_name` is already taken, append a number:
`feature/registration-01`, `feature/registration-02` etc.

## Step 4 — Switch to main and pull latest
Run:
```
git checkout main
git pull origin main
```
If either command fails, stop and report the error.
Do NOT create the branch after a failed pull.

## Step 5 — Create and switch to the feature branch
Run:
```
git checkout -b <branch_name>
```

## Step 6 — Research the codebase
Read these files before writing the spec:
- `CLAUDE.md` — roadmap, conventions, schema
- `app.py` — existing routes and structure
- `database/db.py` — existing schema and functions
- All files in `.claude/specs/` — avoid duplicating existing specs

Check `CLAUDE.md` to confirm the requested step is not already
marked complete. If it is, warn the user and stop.
Also check `.claude/specs/` for an existing spec with the
same step number. If one exists, warn the user and stop.

## Step 7 — Write the spec
Generate a spec document with this exact structure:

---
# Spec: <feature_title>

## Overview
One paragraph describing what this feature does and why
it exists at this stage of the Spendly roadmap.

## Depends on
Which previous steps this feature requires to be complete.

## Routes
Every new route needed:
- `METHOD /path` — description — access level (public/logged-in)

If no new routes: state "No new routes".

## Database changes
Any new tables, columns, or constraints needed.
Always verify against `database/db.py` before writing this.
If none: state "No database changes".

## Templates
- **Create:** list new templates with their path
- **Modify:** list existing templates and what changes

## Files to change
Every file that will be modified.

## Files to create
Every new file that will be created.

## New dependencies
Any new pip packages. If none: state "No new dependencies".

## Rules for implementation
Specific constraints Claude must follow. Always include:
- No SQLAlchemy or ORMs
- Parameterised queries only
- Passwords hashed with werkzeug
- Use CSS variables — never hardcode hex values
- All templates extend `base.html`
- Emails are stripped and lowercased in application code
  before saving or looking up (the database CHECK requires lowercase)
- Login errors never reveal whether the email or the
  password was wrong
- Secrets such as the Flask secret key come from environment
  variables, never from the code
- Passwords and password hashes are never printed or logged

## Error handling
A table: action → required result (the exact exception,
HTTP status, or message shown to the user).

## Edge cases
Inputs and states that must be handled: empty values,
duplicates, different letter case, extra whitespace,
logged-out access to protected pages, repeated submits.

## Acceptance criteria and tests
Numbered AC-1, AC-2, and so on. Each is one
Given / When / Then and maps to exactly one automated test
in `tests/`. Tests use the `spendly_test` database (reset
before every test) and never touch `spendly` or `spendly.db`.

## Open questions
Decisions the user must make before the design stage. List
each one with a recommended default. If there are none,
state "None".

## Definition of done
A specific testable checklist. It must include:
- All acceptance criteria pass with `pytest -q`
- The app was run by hand and each user-visible item was
  verified in the browser
- Each remaining item must be something that can be verified
  by running the app or the tests
---

## Step 8 — Save the spec
Save to: `.claude/specs/<step_number>-<feature_slug>.md`

Do NOT commit. The user commits the spec after reviewing it.

## Step 9 — Report to the user
Print a short summary in this exact format:
```
Branch:    <branch_name>
Spec file: .claude/specs/<step_number>-<feature_slug>.md
Title:     <feature_title>
```

If the spec has open questions, list them in one line each
under the summary.

Then tell the user:
"Next: open a fresh session (/clear) and review
`.claude/specs/<step_number>-<feature_slug>.md` as a skeptic
(list gaps and contradictions, do not edit). Fix what is real,
commit the spec, and only then enter Plan Mode with Shift+Tab
twice for the design."

Do not print the full spec in chat unless explicitly asked.