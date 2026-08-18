---
description: Verify the scripted demo still runs end-to-end (priority-zero if broken)
---

The demo is a product feature (CLAUDE.md Iron Rule 4). Verify it now:

1. `make demo` from the current tree. Confirm the stack comes up and seeding completes with no errors.
2. Walk the spine scenario via API/simulators, asserting after each step:
   - Trigger doctor-absent via simulator → `doctor_status` flips and `presence.changed` published.
   - Replan fires → `plan_runs` row with duration_ms < 5000 and moved_count > 0.
   - `notifications` rows created for affected patients (mock=true is fine).
   - Dashboard WebSocket received the events (check via test client).
3. If Phase 2 modules exist, additionally verify: referral reserve→expiry, blood widget renders data, Golden Hour ranking returns < 3s.
4. Report PASS/FAIL per step. On any FAIL: stop other work, diagnose, and fix — then re-run this command. Log the breakage + cause in the Session Log.

$ARGUMENTS
