# Stop hook: shows a macOS notification that the task finished (never blocks).
import subprocess, sys

try:
    subprocess.run(
        ["osascript", "-e",
         'display notification "Task finished" with title "Claude Code"'],
        capture_output=True, timeout=5,
    )
except Exception:
    pass
sys.exit(0)
