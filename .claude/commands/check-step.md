---
description: Add missing tests for the current step, run the suite, then run the security and code quality reviews in parallel
argument-hint: "Optional step spec, e.g. 06-add-expense"
disable-model-invocation: true
---

Check the current Spendly step. Step spec (optional): $ARGUMENTS

Never edit app code and never commit, stage or stash anything. Pass the step spec above (if given) to every subagent.

1. Use the **spendly-test-writer** subagent to add any missing tests from the step's spec.
2. When it finishes, use the **spendly-test-runner** subagent to run the suite.
3. If any test fails or errors, or the `spendly.db` hash changed, stop here. Report the test-writer summary and the test-runner failures, and do not run the reviews.
4. Otherwise, launch the **spendly-security-reviewer** and **spendly-quality-reviewer** subagents at the same time, in one message, so they run in parallel.
5. Combine their reports into one list grouped as **Blocking**, **Should fix / Worth improving** and **Nit**, each item with `file:line` and which reviewer raised it (merge duplicates). Write "none" for an empty group. Put a one-line test summary (tests added, pass count) above it.

Then stop and wait for me. Do not fix anything.
