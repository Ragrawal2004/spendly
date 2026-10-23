# Blocks Edit, Write and NotebookEdit on any path under expense-tracker-frontend/.
# Bash writes to that folder (sed -i, redirects, rm) are not covered.
import json, os, sys

try:
    data = json.load(sys.stdin)
    ti = data["tool_input"]
    path = ti.get("file_path") or ti.get("notebook_path") or ""
    full = os.path.abspath(os.path.join(data.get("cwd") or "", path))
    if "expense-tracker-frontend" in full.split(os.sep):
        print("Blocked: expense-tracker-frontend/ must not be modified.", file=sys.stderr)
        sys.exit(2)
except Exception:
    pass
sys.exit(0)
