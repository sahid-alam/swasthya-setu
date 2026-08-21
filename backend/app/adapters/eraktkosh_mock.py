"""Blood stock, offline — PRD §M6.

The default, per Iron Rule 4. e-RaktKosh is the Government of India's national blood
bank portal; it has no documented public JSON API, so the real adapter scrapes its
availability endpoint and that is a thing which breaks when someone changes a table on
a government website. The demo cannot depend on it.

What this returns is generated, and **every row it produces is stamped SYNTHETIC** —
the column, not a comment, so the §9d chip in the UI and the `source` field in the API
both say so without anyone remembering to mention it.

The numbers are shaped rather than random: negative groups are scarce, O-negative is
scarcest, and a district hospital holds a fraction of what a medical college does.
That shape is what makes a Golden Hour ranking interesting; uniform random stock would
make the blood factor meaningless.
"""

from __future__ import annotations

import random
from datetime import UTC, datetime

from app.adapters.base import BloodAdapter, BloodReading
from app.models import BloodComponent, BloodGroup, BloodSource

# Rough share of an Indian blood bank's stock by group. O+ and B+ dominate; AB− is
# vanishingly rare. Used to scale, not to claim precision.
GROUP_SHARE = {
    BloodGroup.O_POS: 1.00,
    BloodGroup.B_POS: 0.95,
    BloodGroup.A_POS: 0.75,
    BloodGroup.AB_POS: 0.35,
    BloodGroup.O_NEG: 0.14,
    BloodGroup.B_NEG: 0.12,
    BloodGroup.A_NEG: 0.10,
    BloodGroup.AB_NEG: 0.05,
}

# Ceiling for a large facility, per component, before the group share is applied.
CEILING = {BloodComponent.PRBC: 26, BloodComponent.WHOLE: 14}


class MockERaktKosh(BloodAdapter):
    def __init__(self, seed: int = 2026) -> None:
        # Fixed: the demo must look the same every run.
        self._rng = random.Random(seed)

    async def stock_for(self, *, hospital_code: str, scale: float = 1.0) -> list[BloodReading]:
        now = datetime.now(UTC)
        readings = []
        for group, share in GROUP_SHARE.items():
            for component, ceiling in CEILING.items():
                top = max(1, round(ceiling * share * scale))
                readings.append(
                    BloodReading(
                        group=group,
                        component=component,
                        units=self._rng.randint(0, top),
                        as_of=now,
                        source=BloodSource.SYNTHETIC,
                    )
                )
        return readings

    async def health(self) -> bool:
        return True
