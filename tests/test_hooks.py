import json
import subprocess
import sys
from pathlib import Path

import pytest

HOOKS = Path(__file__).resolve().parent.parent / ".claude" / "hooks"


@pytest.fixture(autouse=True)
def isolated_db():
    # Overrides the conftest fixture of the same name: hook tests never touch the database.
    yield


def run_hook(name, payload, env=None):
    stdin = payload if isinstance(payload, str) else json.dumps(payload)
    return subprocess.run(
        [sys.executable, str(HOOKS / name)],
        input=stdin, capture_output=True, text=True, timeout=15, env=env,
    )


def bash(command, cwd=None):
    return {"tool_name": "Bash", "tool_input": {"command": command}, "cwd": cwd}


def assert_blocked(result):
    assert result.returncode == 2
    assert result.stderr.strip().startswith("Blocked")
    assert len(result.stderr.strip().splitlines()) == 1


def make_repo(tmp_path, branch):
    subprocess.run(["git", "init", "-q", "-b", branch, str(tmp_path)], check=True)
    return str(tmp_path)


# 1. block_main_commit.py

@pytest.mark.parametrize("command", ["git commit -m x", "git push origin main", "git -C . commit -m x"])
def test_commit_push_blocked_on_main(tmp_path, command):
    assert_blocked(run_hook("block_main_commit.py", bash(command, make_repo(tmp_path, "main"))))


def test_commit_allowed_on_feature_branch(tmp_path):
    result = run_hook("block_main_commit.py", bash("git commit -m x", make_repo(tmp_path, "chore/x")))
    assert result.returncode == 0


def test_other_git_commands_allowed_on_main(tmp_path):
    cwd = make_repo(tmp_path, "main")
    assert run_hook("block_main_commit.py", bash("git status", cwd)).returncode == 0
    assert run_hook("block_main_commit.py", bash("git log --oneline", cwd)).returncode == 0


# 2. block_secret_print.py

@pytest.mark.parametrize("command", [
    "echo $DATABASE_URL",
    'echo "$SPENDLY_TEST_DATABASE_URL"',
    "printf '%s' ${SPENDLY_SECRET_KEY}",
    "python3 -c 'print(os.environ[\"DATABASE_URL\"])'",
    "printenv",
    "env",
    "cd x && env | sort",
    "printenv DATABASE_URL",
    "cat ~/.zshrc",
    "head -5 .env",
    "tail .env.local",
    "less /Users/me/project/.env",
])
def test_secret_printing_blocked(command):
    assert_blocked(run_hook("block_secret_print.py", bash(command)))


@pytest.mark.parametrize("command", [
    'psql "$DATABASE_URL" -c "SELECT 1"',
    "echo hi && psql $DATABASE_URL -c 'SELECT 1'",
    "echo hello",
    "env FOO=1 .venv/bin/pytest",
    "printenv HOME",
    "cat .venv/pyvenv.cfg",
    "cat README.md",
    ".venv/bin/pytest -q",
    "export FOO=1",
    "set -e",
    'python3 -c \'import os; print(os.environ["HOME"])\'',
    "python3 - <<'EOF'\nimport os, psycopg\nurl = os.environ[\"DATABASE_URL\"]\n"
    "rows = psycopg.connect(url).execute('SELECT 1').fetchall()\nprint(rows)\nEOF",
    "echo starting\npsql $DATABASE_URL -c 'SELECT 1'",
])
def test_secret_use_without_printing_allowed(command):
    assert run_hook("block_secret_print.py", bash(command)).returncode == 0


@pytest.mark.parametrize("command", [
    "export -p",
    "declare -x",
    "set",
    "export",
    "cd x\nexport\nls",
    "python3 -c 'import os; print(os.environ)'",
    "python3 -c 'import os; print(dict(os.environ))'",
])
def test_environment_dumps_blocked(command):
    assert_blocked(run_hook("block_secret_print.py", bash(command)))


def test_commit_message_mentioning_secret_name_allowed_on_feature_branch(tmp_path):
    command = 'git commit -m "docs: mention DATABASE_URL in the notes"'
    cwd = make_repo(tmp_path, "chore/x")
    for name in ("block_main_commit.py", "block_secret_print.py", "block_destructive_sql.py"):
        assert run_hook(name, bash(command, cwd)).returncode == 0, name


# The hooks match raw command text on purpose, so a message such as
# "print the DATABASE_URL note" is blocked even though it only mentions the name.
def test_commit_message_with_print_and_secret_name_blocked_on_purpose():
    command = 'git commit -m "print the DATABASE_URL note"'
    assert_blocked(run_hook("block_secret_print.py", bash(command)))


# 3. block_destructive_sql.py

@pytest.mark.parametrize("command", [
    'psql -d spendly -c "DROP TABLE expenses"',
    'docker exec spendly-pg psql -U postgres -d spendly -c "TRUNCATE users"',
    'psql postgresql://u@localhost/spendly -c "delete from users"',
    'psql -d spendly -c "DELETE FROM expenses"',
    'psql -d spendly -c "DELETE FROM expenses WHERE id = 9; DELETE FROM users"',
    'psql "$DATABASE_URL" -c "DROP TABLE users"',
    "python3 -c \"import psycopg; psycopg.connect('dbname=spendly').execute('DELETE FROM expenses')\"",
])
def test_destructive_sql_on_spendly_blocked(command):
    assert_blocked(run_hook("block_destructive_sql.py", bash(command)))


@pytest.mark.parametrize("command", [
    'docker exec spendly-pg psql -U postgres -d spendly_test -c "DROP TABLE expenses"',
    'psql "$SPENDLY_TEST_DATABASE_URL" -c "TRUNCATE users"',
    'docker exec spendly-pg psql -U postgres -d spendly -c "SELECT count(*) FROM users"',
    'docker exec spendly-pg psql -U postgres -d postgres -c "CREATE DATABASE spendly"',
    "rm -rf build",
    'psql -d spendly -c "DELETE FROM expenses WHERE id = 9"',
    'psql -d spendly -c "delete from expenses where id = 9"',
])
def test_safe_sql_allowed(command):
    assert run_hook("block_destructive_sql.py", bash(command)).returncode == 0


# 4. block_frontend_edit.py

@pytest.mark.parametrize("tool_input", [
    {"file_path": "/p/expense-tracker-frontend/src/App.jsx"},
    {"file_path": "expense-tracker-frontend/package.json"},
    {"file_path": "/p/app/../expense-tracker-frontend/x.js"},
    {"notebook_path": "/p/expense-tracker-frontend/n.ipynb"},
])
def test_frontend_paths_blocked(tool_input):
    assert_blocked(run_hook("block_frontend_edit.py", {"tool_input": tool_input, "cwd": "/p"}))


@pytest.mark.parametrize("tool_input", [
    {"file_path": "/p/app.py"},
    {"file_path": "templates/expenses.html"},
    {"file_path": "/p/docs/expense-tracker-frontend-notes.md"},
    {"notebook_path": "/p/analysis.ipynb"},
])
def test_other_paths_allowed(tool_input):
    assert run_hook("block_frontend_edit.py", {"tool_input": tool_input, "cwd": "/p"}).returncode == 0


# 5. notify_done.py (PATH is emptied so no real notification is shown)

def test_stop_hook_exits_zero_without_osascript():
    result = run_hook("notify_done.py", {"hook_event_name": "Stop"}, env={"PATH": ""})
    assert result.returncode == 0
    assert result.stderr == ""


# Fail open on bad input

@pytest.mark.parametrize("name", [
    "block_main_commit.py", "block_secret_print.py", "block_destructive_sql.py", "block_frontend_edit.py",
])
@pytest.mark.parametrize("payload", ["not json", "{}", '{"tool_input": null}', ""])
def test_malformed_input_fails_open(name, payload):
    assert run_hook(name, payload).returncode == 0
