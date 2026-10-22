---
description: Run the security and quality reviews of this branch's changes in parallel and combine their findings
argument-hint: "Optional step spec, e.g. 06-add-expense"
allowed-tools: Bash(git diff:*)
disable-model-invocation: true
---

Review the Spendly changes on this branch. Step spec (optional): $ARGUMENTS

## Pre-flight

Collect the review diff from three parts:
- `git diff main...HEAD` — commits on this branch
- `git diff` — unstaged work
- `git diff --staged` — staged work

If all three are empty, reply "No changes detected" and stop. Untracked files appear in none of them; to include a new file, `git add -N <file>` it first.

## Review

Launch the **spendly-security-reviewer** and **spendly-quality-reviewer** subagents at the same time, in one message, so they run in parallel. Give each the step spec (if given) and tell it to review the whole combined diff, all three parts, not only uncommitted work.

## Verdict

Map the reviewers' groups (the quality reviewer's **Worth improving** counts as **Should fix**):
- any **Blocking** item → **CHANGES REQUESTED**
- **Should fix** items but no Blocking → **APPROVED WITH SUGGESTIONS**
- only **Nit** items, or none → **APPROVED**

## Combined Action Plan

Under the verdict, list every finding in this order: **Blocking**, then **Should fix**, then **Nit**. Give each item its `file:line` and which reviewer raised it, and merge duplicates. Write "none" for an empty group.

Then stop and wait for me. Nothing is edited before I approve it.

## Rules

- Never edit any file, and never commit, stage or stash anything.
- Never print `DATABASE_URL`, `SPENDLY_TEST_DATABASE_URL`, passwords or secrets.
