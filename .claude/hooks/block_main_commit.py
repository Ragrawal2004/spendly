# Blocks "git commit" and "git push" while the current git branch is main.
import json, re, subprocess, sys

try:
    data = json.load(sys.stdin)
    cmd = data["tool_input"]["command"]
    if re.search(r"\bgit\s+(-\S+\s+([^-\s]\S*\s+)?)*(commit|push)\b", cmd):
        branch = subprocess.run(
            ["git", "branch", "--show-current"],
            cwd=data.get("cwd") or None,
            capture_output=True, text=True, timeout=5,
        ).stdout.strip()
        if branch == "main":
            print("Blocked: git commit/push on main. Switch to a feature branch.", file=sys.stderr)
            sys.exit(2)
except Exception:
    pass
sys.exit(0)
