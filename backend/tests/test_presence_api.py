"""End-to-end presence: signals in through the public API, fused state out.

The signal-simulator skill requires every scenario used in the demo script to have an
integration test asserting the expected transitions — these are those tests, driven
through the same HTTP endpoint the simulators and real hardware use.
"""

import pytest

BADGE = "HP-DOC-1001"


@pytest.fixture
def auth(admin_token):
    return {"Authorization": f"Bearer {admin_token}"}


@pytest.fixture
def roster(client, auth):
    return client.get("/api/v1/simulation/roster", headers=auth).json()


def zone_of(roster, badge, kind):
    doctor = next(d for d in roster["doctors"] if d["badge_id"] == badge)
    zones = [z for z in roster["zones"] if z["hospital_code"] == doctor["hospital_code"]]
    for z in zones:
        if z["kind"] == kind and z["department"] == doctor["department"]:
            return z["code"]
    return next(z["code"] for z in zones if z["kind"] == kind)


def send(client, auth, badge, source, zone_code, **raw):
    r = client.post(
        "/api/v1/signals",
        headers=auth,
        json={"source": source, "badge_id": badge, "zone_code": zone_code, "raw": raw},
    )
    assert r.status_code == 201, r.text
    return r.json()


def board_row(client, auth, badge):
    rows = client.get("/api/v1/presence", headers=auth).json()
    return next(r for r in rows if r["badge_id"] == badge)


# --- ingestion --------------------------------------------------------------


def test_signals_endpoint_requires_authentication(client):
    r = client.post("/api/v1/signals", json={"source": "BLE", "badge_id": BADGE})
    assert r.status_code == 401


def test_unknown_badge_is_rejected(client, auth):
    r = client.post(
        "/api/v1/signals", headers=auth, json={"source": "BLE", "badge_id": "NOPE-9999"}
    )
    assert r.status_code == 404


def test_unknown_zone_is_rejected_rather_than_silently_dropped(client, auth):
    r = client.post(
        "/api/v1/signals",
        headers=auth,
        json={"source": "BLE", "badge_id": BADGE, "zone_code": "NOT-A-ZONE"},
    )
    assert r.status_code == 404


def test_face_source_is_refused_on_the_plain_signal_endpoint(client, auth):
    r = client.post("/api/v1/signals", headers=auth, json={"source": "FACE", "badge_id": BADGE})
    assert r.status_code == 400


# --- the demo scenarios -----------------------------------------------------


def test_walking_from_opd_to_surgery_flips_the_board(client, auth, roster, fresh_badge):
    """PRD §M1 accept: "show me a doctor walking from OPD to surgery"."""
    fresh_badge(BADGE)
    opd, theatre = zone_of(roster, BADGE, "OPD"), zone_of(roster, BADGE, "OT")

    send(client, auth, BADGE, "BLE", opd, rssi=-64)
    assert send(client, auth, BADGE, "BLE", opd, rssi=-61)["state"] == "PRESENT_IN_DEPT"

    after = send(client, auth, BADGE, "RFID", theatre, reader="ot-door")
    assert after["state"] == "IN_SURGERY", "one high-trust tap must flip immediately"

    doctor_id = after["doctor_id"]
    trail = client.get(f"/api/v1/presence/{doctor_id}/transitions", headers=auth).json()
    assert trail[0]["to_state"] == "IN_SURGERY"
    top = trail[0]["evidence"]["contributors"][0]
    assert top["source"] == "RFID" and top["zone_code"] == theatre


def test_a_live_badge_beats_a_roster_that_says_on_leave(client, auth, roster, fresh_badge):
    """PRD §M1 accept: "why not just an attendance app?"."""
    badge = fresh_badge("HP-DOC-1014")
    r = client.put("/api/v1/roster/shift", headers=auth, json={"badge_id": badge, "kind": "LEAVE"})
    assert r.status_code == 200
    assert r.json()["state"] == "ON_LEAVE", "with no signals, the roster is all we have"

    opd = zone_of(roster, badge, "OPD")
    send(client, auth, badge, "BLE", opd, rssi=-60)
    after = send(client, auth, badge, "BLE", opd, rssi=-58)

    assert after["state"] == "PRESENT_IN_DEPT"
    row = board_row(client, auth, badge)
    assert row["evidence"]["roster_state"] == "ON_LEAVE"


def test_admin_override_wins_and_records_who_and_why(client, auth, roster, fresh_badge):
    badge = fresh_badge("HP-DOC-1016")
    opd = zone_of(roster, badge, "OPD")
    send(client, auth, badge, "RFID", opd)
    doctor_id = send(client, auth, badge, "BLE", opd)["doctor_id"]

    r = client.post(
        f"/api/v1/presence/{doctor_id}/override",
        headers=auth,
        json={"state": "ON_LEAVE", "reason": "Called in sick at 09:05"},
    )
    assert r.status_code == 200
    assert r.json()["state"] == "ON_LEAVE", "an override outranks a badge left on a desk"

    trail = client.get(f"/api/v1/presence/{doctor_id}/transitions", headers=auth).json()
    manual = next(c for c in trail[0]["evidence"]["contributors"] if c["source"] == "MANUAL")
    assert manual["state"] == "ON_LEAVE"


def test_override_is_admin_only(client, roster):
    from app.models import UserRole
    from app.security import make_token

    staff = make_token("00000000-0000-0000-0000-000000000000", UserRole.STAFF)
    doctor_id = roster["doctors"][0]["doctor_id"]
    r = client.post(
        f"/api/v1/presence/{doctor_id}/override",
        headers={"Authorization": f"Bearer {staff}"},
        json={"state": "ON_LEAVE", "reason": "should not be allowed"},
    )
    assert r.status_code == 403


# --- face kiosk -------------------------------------------------------------


def test_enrolled_face_checks_in(client, auth, roster):
    enrolled = next(d for d in roster["doctors"] if d["face_enrolled"])
    capture = client.get(f"/api/v1/dev/face-capture/{enrolled['badge_id']}", headers=auth)
    assert capture.status_code == 200

    r = client.post(
        "/api/v1/signals/face", headers=auth, json={"embedding": capture.json()["embedding"]}
    )
    body = r.json()
    assert body["matched"] is True
    assert body["doctor_id"] == enrolled["doctor_id"]
    assert body["similarity"] > 0.45


def test_an_unenrolled_doctor_has_no_capture_to_replay(client, auth, roster):
    """Check-in is voluntary, so a doctor who never enrolled must not be matchable."""
    unenrolled = next(d for d in roster["doctors"] if not d["face_enrolled"])
    r = client.get(f"/api/v1/dev/face-capture/{unenrolled['badge_id']}", headers=auth)
    assert r.status_code == 404


def test_a_stranger_is_not_matched_to_anyone(client, auth):
    stranger = [0.01] * 512
    body = client.post("/api/v1/signals/face", headers=auth, json={"embedding": stranger}).json()
    assert body["matched"] is False
    assert body["doctor_id"] is None


def test_roster_does_not_leak_face_embeddings(client, auth, roster):
    assert all("embedding" not in d for d in roster["doctors"])
