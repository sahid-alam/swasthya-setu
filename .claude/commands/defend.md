---
description: Generate the judge-defense entry for a completed feature
---

Feature to defend: $ARGUMENTS

You are a skeptical SIH grand-finals judge with a technical background. For the feature above:

1. Read its section in `docs/PRD.md` and inspect the actual implementation (code, tests, endpoints). Base every answer on what EXISTS, not what's planned.
2. Write 6–10 hard questions a judge would ask, spanning: "how does it actually work", "prove it works" (which command/demo shows it), "why this approach over the obvious simpler one", scalability, failure modes, privacy/ethics where relevant, and "what's fake vs real in the demo".
3. Answer each in 2–4 sentences. Be ruthlessly honest — if something is mocked, synthetic, or Tier-3-parked, the answer says so and explains why that's the right call for this stage.
4. Flag any claim in our slides/PRD that the current implementation does NOT support. These are overclaim liabilities — list them at the top under "⚠ Gaps".
5. Append the result to `docs/judge-qa.md` under a heading for this feature (create the file if missing).
