# Blocks commands that print secrets: echo/printf/print of the DB URLs or secret key,
# env dumps (printenv, env, export -p, declare -x, bare set/export, print of os.environ),
# and cat/less/head/tail of ~/.zshrc or .env files. Scanned per line (re.M).
import json, re, sys

VARS = r"(DATABASE_URL|SPENDLY_TEST_DATABASE_URL|SPENDLY_SECRET_KEY)"
START = r"(^[ \t]*|[;&|][ \t]*)"
END = r"[ \t]*($|[;&|])"
PATTERNS = [
    r"\b(echo|printf|print)\b[^;&|\n]*\b" + VARS + r"\b",
    START + r"(printenv|env|set|export)" + END,
    START + r"printenv[ \t]+" + VARS + r"\b",
    START + r"export[ \t]+-p\b",
    START + r"declare[ \t]+-x" + END,
    r"\b(print|echo)[ \t]*\(?[ \t]*(dict\([ \t]*)?os\.environ[ \t]*\)",
    r"\b(cat|less|head|tail)\b[^;&|\n]*(\.zshrc\b|(?<![\w.])\.env(\.\w+)?(?![\w/-]))",
]

try:
    cmd = json.load(sys.stdin)["tool_input"]["command"]
    if any(re.search(p, cmd, re.M) for p in PATTERNS):
        print("Blocked: this command would print a secret.", file=sys.stderr)
        sys.exit(2)
except Exception:
    pass
sys.exit(0)
