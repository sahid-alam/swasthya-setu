"""HMIS roster feed. Pushes shift changes the way a hospital information system would.

The roster is the weakest signal in the fusion (trust 0.3) precisely because it is
often wrong — this is the simulator that makes it wrong on purpose:

    python simulators/roster_feed.py HP-DOC-1001 LEAVE     # paper says away
    python simulators/roster_feed.py HP-DOC-1001 OPD       # back on the books
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from client import Setu  # noqa: E402

KINDS = ["OPD", "WARD", "SURGERY", "ON_CALL", "LEAVE"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("badge")
    ap.add_argument("kind", choices=KINDS)
    args = ap.parse_args()

    api = Setu()
    try:
        r = api.http.put(
            "/api/v1/roster/shift", json={"badge_id": args.badge, "kind": args.kind}
        )
        r.raise_for_status()
        out = r.json()
        print(
            f"roster now says {args.kind}; fused state is {out['state']} "
            f"({out['confidence']:.2f}) — presence wins when the two disagree"
        )
        return 0
    finally:
        api.close()


if __name__ == "__main__":
    raise SystemExit(main())
