---
description: Seed realistic dummy expenses for a specific user (development only)
argument-hint: "<user_id> <count> <months>"
allowed-tools: Read, Bash(python3:*), Bash(.venv/bin/python:*)
---

Read database/db.py to understand the expenses table schema and the get_db() helper.

User input: $ARGUMENTS

## Step 0 — Safety

If the environment variable SPENDLY_ENV is "production", stop and say so. Do not insert anything.

## Step 1 — Parse arguments

Extract from $ARGUMENTS:
- user_id — positive integer
- count — positive integer, at most 1000
- months — positive integer, at most 36

If any argument is missing, not a valid integer, or out of range, stop and say:
"Usage: /seed-expenses <user_id> <count> <months>
Example: /seed-expenses 1 50 6"

## Step 2 — Verify user exists

Before generating anything, confirm the user_id exists in the users table. If not, stop and say:
"No user found with id <user_id>."

## Step 3 — Generate and insert expenses

Write and run a Python script from the project root (use .venv/bin/python, because db.py imports werkzeug) that:

1. Picks each expense date at random between (today - months*30 days) and today, using date arithmetic. Format as YYYY-MM-DD. Never a future date.
2. Uses exactly these category names (spelling and capitalisation matter, the database rejects anything else) with realistic Indian descriptions and amounts (₹):
   - Food: 50–800
   - Transport: 20–500
   - Bills: 200–3000
   - Health: 100–2000
   - Entertainment: 100–1500
   - Shopping: 200–5000
   - Other: 50–1000
3. Picks categories with weights of about Food 35, Transport 20, Shopping 15, Bills 12, Entertainment 8, Health 6, Other 4.
4. Rounds every amount to 2 decimals.
5. Gets its connection from get_db() in db.py. Do not hardcode the database filename.
6. Uses parameterised queries only, with ? placeholders and no string formatting in SQL.
7. Inserts all expenses in a single transaction using `with closing(get_db()) as conn:` and `with conn:`, so everything rolls back if any insert fails.

## Step 4 — Confirm

Print:
- How many expenses were inserted
- The date range they span (earliest and latest date)
- A sample of 5 inserted records, ordered by date