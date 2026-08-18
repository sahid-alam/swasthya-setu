#!/usr/bin/env bash
# PreToolUse hook (Edit|Write). Reads tool input JSON on stdin.
# Exit 2 = block the tool call and show stderr to Claude.

INPUT=$(cat)
FILE=$(echo "$INPUT" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('tool_input',{}).get('file_path',''))" 2>/dev/null)

[ -z "$FILE" ] && exit 0

case "$FILE" in
  *docs/PRD.md)
    echo "BLOCKED: docs/PRD.md is the product source of truth. Scope changes must be made by the team in chat, not during a build session. Propose the change instead." >&2
    exit 2 ;;
  *docs/DESIGN.md)
    echo "BLOCKED: docs/DESIGN.md is the team's design system. Don't drift it during build sessions — implement it in code (tailwind theme / tokens.css / components). If the system genuinely needs a change, propose it in chat." >&2
    exit 2 ;;
  *ml/artifacts/*)
    echo "BLOCKED: ml/artifacts/ holds committed model artifacts. Regenerate via scripts in ml/, never hand-edit." >&2
    exit 2 ;;
  *.env|*/.env)
    echo "BLOCKED: never edit .env directly. Update .env.example and tell the user what to set." >&2
    exit 2 ;;
esac

exit 0
