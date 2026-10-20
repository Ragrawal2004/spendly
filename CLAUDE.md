# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project overview

Spendly is a Flask-based expense tracker, built incrementally as a step-by-step learning project. The codebase is intentionally scaffolded with placeholder routes and an empty database module — features are implemented one step at a time rather than all at once.

## Commands

The venv lives at `.venv/` (not `venv/` — note the `.gitignore` excludes `venv/`, which doesn't match the actual `.venv/` directory name).

```bash
# Install dependencies (venv activation doesn't persist across separate Bash calls,
# so either chain source+command, or call the venv binary directly)
.venv/bin/pip install -r requirements.txt

# Run the dev server (binds port 5001, not Flask's default 5000)
.venv/bin/python3 app.py

# Run tests
.venv/bin/pytest
.venv/bin/pytest path/to/test_file.py::test_name   # single test
```

## Architecture

Flat, single-file Flask app — no blueprints, no app factory pattern. Everything routes from `app.py`.

- **`app.py`** — the only entry point. Each route either calls `render_template(...)` for built pages, or returns a placeholder string for features not yet implemented (labeled with their build step, e.g. `"Logout — coming in Step 3"`). Runs on port 5001 in debug mode.
- **`database/db.py`** — intended to isolate all SQLite access behind three functions: `get_db()` (SQLite connection with `row_factory` and foreign keys enabled), `init_db()` (creates tables with `CREATE TABLE IF NOT EXISTS`), `seed_db()` (sample data for development). Currently an empty stub — routes in `app.py` should call into this rather than touching raw SQL directly once it's implemented.
- **`templates/`** — server-rendered Jinja2 templates. `base.html` is the shared shell (nav, footer, font/CSS/JS includes); page templates (`landing.html`, `login.html`, `register.html`, `terms.html`, `privacy.html`) extend it via `{% block content %}`.
- **`static/`** — assets served directly via `url_for('static', filename=...)`, referenced from `base.html` so they're shared across all pages: one CSS file (`css/style.css`) and one JS file (`js/main.js`, currently empty — students add JS here as features are built).

No ORM — the data layer is meant to be raw `sqlite3` access through `database/db.py`'s three functions.
