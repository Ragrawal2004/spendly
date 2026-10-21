---
description: Run a code review checklist on a file
---

Review @$ARGUMENTS against this checklist. Report pass or fail for each item, with the line number for any fail. Do NOT edit anything.
1. All SQL with variable data uses ? placeholders.
2. No password or hash is printed or logged.
3. Errors are not swallowed (no bare except that hides them).
4. Connections are closed.
5. Functions match the signatures in the spec.
6. Anything not covered by a test.