# Blocks psql / python -c commands with DROP, TRUNCATE or DELETE FROM (without a WHERE)
# aimed at the spendly database (by name or via $DATABASE_URL). spendly_test stays allowed.
import json, re, sys

DESTRUCTIVE = r"\b(DROP|TRUNCATE)\b|\bDELETE\s+FROM\b(?![^;]*\bWHERE\b)"

try:
    cmd = json.load(sys.stdin)["tool_input"]["command"]
    runs_sql = re.search(r"\bpsql\b|\bpython3?\s+-c\b", cmd)
    destructive = re.search(DESTRUCTIVE, cmd, re.I | re.S)
    on_spendly = re.search(r"(?<![\w-])spendly(?![\w.-])|\$\{?DATABASE_URL\b", cmd)
    if runs_sql and destructive and on_spendly:
        print("Blocked: destructive SQL against the spendly database.", file=sys.stderr)
        sys.exit(2)
except Exception:
    pass
sys.exit(0)
