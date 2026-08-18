#!/usr/bin/env bash
# SessionStart hook: orient every new session automatically.
# Prints current phase progress + next 5 unchecked items + last session log entry.

PLAN="docs/PLAN.md"
[ -f "$PLAN" ] || exit 0

echo "=== SWASTHYA-SETU BUILD STATE ==="
echo "-- Progress --"
grep -c '^\- \[x\]' "$PLAN" | xargs -I{} echo "done: {}"
grep -c '^\- \[ \]' "$PLAN" | xargs -I{} echo "todo: {}"
echo "-- Next unchecked items --"
grep -m 5 '^\- \[ \]' "$PLAN"
echo "-- Last session log entry --"
awk '/^## Session Log/{f=1} f && /^### /{last=NR} {lines[NR]=$0} END{if(last) for(i=last;i<=NR && i<last+8;i++) print lines[i]; else print "(no entries yet — this is the first session)"}' "$PLAN"
echo "================================="

exit 0
