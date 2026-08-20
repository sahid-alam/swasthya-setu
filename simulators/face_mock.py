"""Kiosk face check-in. Asks the dev capture endpoint for what the camera "saw"
(the enrolled vector plus noise) and posts it to the real matching endpoint.

    python simulators/face_mock.py HP-DOC-1001
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from client import Setu  # noqa: E402


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: face_mock.py <badge_id> [zone_code]")
        return 2
    badge, zone = sys.argv[1], (sys.argv[2] if len(sys.argv) > 2 else None)

    api = Setu()
    try:
        capture = api.http.get(f"/api/v1/dev/face-capture/{badge}")
        if capture.status_code == 404:
            print(f"{badge} has not enrolled a face — check-in is voluntary, so this is expected")
            return 1
        capture.raise_for_status()

        result = api.face(capture.json()["embedding"], zone)
        if result["matched"]:
            print(f"matched {result['doctor_name']} at {result['similarity']:.3f} "
                  f"-> {result['state']}")
        else:
            print(f"no match (best similarity {result['similarity']:.3f})")
        return 0
    finally:
        api.close()


if __name__ == "__main__":
    raise SystemExit(main())
