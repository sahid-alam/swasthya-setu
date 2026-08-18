#!/usr/bin/env bash
# PostToolUse hook (Edit|Write): auto-format the file that was just edited.
# Never fails the build — formatting is best-effort.

INPUT=$(cat)
FILE=$(echo "$INPUT" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('tool_input',{}).get('file_path',''))" 2>/dev/null)

[ -z "$FILE" ] || [ ! -f "$FILE" ] && exit 0

case "$FILE" in
  *.py)
    command -v ruff  >/dev/null && ruff check --fix -q "$FILE" 2>/dev/null
    command -v black >/dev/null && black -q "$FILE" 2>/dev/null
    ;;
  *.ts|*.tsx|*.js|*.jsx|*.css|*.json)
    if [ -f frontend/node_modules/.bin/prettier ]; then
      frontend/node_modules/.bin/prettier --write --log-level silent "$FILE" 2>/dev/null
    elif command -v npx >/dev/null; then
      npx --no-install prettier --write --log-level silent "$FILE" 2>/dev/null
    fi
    ;;
esac

exit 0
