---
description: End-of-session checkpoint — verify, log, commit
---

Run the end-of-session checkpoint:

1. Run `make lint` and `make test`. If either fails, fix before proceeding (or record the failure explicitly in the log if out of scope for this session).
2. In `docs/PLAN.md`, tick `[x]` for every item completed AND verified this session — never tick untested items.
3. Append a Session Log entry to `docs/PLAN.md`: today's date, items touched, decisions made, gotchas, and exactly what the next session should pick up first.
4. If any architectural decision was made, add a row to the Key Decisions table in `docs/ARCHITECTURE.md`. If the schema changed, confirm `docs/SCHEMA.md` was updated.
5. `git add -A && git commit` with a conventional message summarizing the session.
6. Print a 3-line summary: what got done, what's next, any risk.

$ARGUMENTS
