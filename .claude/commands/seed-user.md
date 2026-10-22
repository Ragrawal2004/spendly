---
description: Create a single dummy user in the database (development only)
allowed-tools: Read, Bash(python3:*), Bash(.venv/bin/python:*)
---

Read database/db.py to understand the users table schema and the get_db() helper.

If the environment variable SPENDLY_ENV is "production", stop and say so. Do not create anything.

Then write and run a Python script using Bash, from the project root, that:

1. Generates a realistic random Indian user using your own knowledge of common Indian names across regions:
   - Name: a realistic Indian first + last name
   - Email: derived from the name, lowercase, with a random 2-3 digit number suffix (e.g. rahul.sharma91@gmail.com)
   - Password: "password123" hashed with werkzeug's generate_password_hash
   - created_at: do not set it. Let the column's default fill it in.

2. Checks if the generated email already exists in the users table (compare case-insensitively). If it does, regenerate until unique.

3. Inserts the user using the same pattern as db.py:
   `with closing(get_db()) as conn, conn.transaction():` and a parameterized INSERT using %s placeholders.

4. Prints a confirmation in this format:
   - id: <id>
   - name: <name>
   - email: <email>
   - password: password123 (never print the hash)