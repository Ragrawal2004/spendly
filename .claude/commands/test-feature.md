---
description: Add missing tests for the current step from its spec, then run the suite
argument-hint: "Optional step spec, e.g. 06-add-expense"
allowed-tools: Bash(.venv/bin/pytest:*), Bash(shasum spendly.db)
disable-model-invocation: true
---

Test the current Spendly step. Step spec (optional): $ARGUMENTS

Pass the step spec above (if given) to each subagent.

1. Use the **spendly-test-writer** subagent. Tell it to read the step spec's acceptance criteria, map each AC to exactly one test named with an `_acN` suffix, and add only missing tests plus clear gaps. Tests go in the right existing file under `tests/` (for the add-expense step, `tests/test_expenses.py`). Do not create `tests/test_$ARGUMENTS.py`. Ask it to list the names of the tests it added or changed.
2. When it finishes, use the **spendly-test-runner** subagent. Tell it to run the new or changed tests first with `.venv/bin/pytest -q <file>::<test> ...`, then the full suite with `.venv/bin/pytest -q --durations=5`, report the collected count, and check that `shasum spendly.db` is the same before and after.
3. If any test fails or errors, or the `spendly.db` hash changed, stop and report the failures as the test runner classified them.
4. Otherwise report in a few lines: tests added, ACs already covered, ACs not testable, the collected count, the pass count and the hash check.

Then stop and wait for me. Nothing outside `tests/` is edited before I approve it.

## Rules

- Never commit, stage or stash anything.
- Never fix app code (`app.py`, `database/`, `templates/`, `static/`), even when a failure is clearly an app bug.
- Never print `DATABASE_URL`, `SPENDLY_TEST_DATABASE_URL`, passwords or secrets.
