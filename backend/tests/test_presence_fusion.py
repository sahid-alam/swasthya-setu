"""Fusion behaviour, tested against the pure core — these are the judge questions
in PRD §M1 written as assertions.
"""

from datetime import UTC, datetime, timedelta

from app.models import PresenceState, ShiftKind, SignalSource, ZoneKind
from app.services.presence import (
    FLIP_THRESHOLD,
    Observation,
    decayed_score,
    fuse,
    state_for_shift,
    state_for_zone,
)

NOW = datetime(2026, 8, 20, 10, 0, tzinfo=UTC)
DEPT = "11111111-1111-1111-1111-111111111111"
OTHER_DEPT = "22222222-2222-2222-2222-222222222222"


def obs(source, state, ago_seconds=0, **kw):
    return Observation(
        source=source, state=state, observed_at=NOW - timedelta(seconds=ago_seconds), **kw
    )


# --- zone and roster mapping ------------------------------------------------


def test_own_opd_is_present_in_dept_other_opd_is_elsewhere():
    assert state_for_zone(ZoneKind.OPD, DEPT, DEPT) == PresenceState.PRESENT_IN_DEPT
    assert state_for_zone(ZoneKind.OPD, OTHER_DEPT, DEPT) == PresenceState.PRESENT_ELSEWHERE
    assert state_for_zone(ZoneKind.OT, None, DEPT) == PresenceState.IN_SURGERY
    assert state_for_zone(ZoneKind.WARD, None, DEPT) == PresenceState.ON_ROUNDS
    assert state_for_zone(ZoneKind.GATE, None, DEPT) == PresenceState.PRESENT_ELSEWHERE


def test_no_shift_means_off_shift_and_on_call_implies_nothing():
    assert state_for_shift(None) == PresenceState.OFF_SHIFT
    assert state_for_shift(ShiftKind.LEAVE) == PresenceState.ON_LEAVE
    # on call is not on site; guessing is exactly how rosters mislead
    assert state_for_shift(ShiftKind.ON_CALL) is None


# --- decay ------------------------------------------------------------------


def test_score_decays_with_age():
    fresh = decayed_score(obs(SignalSource.BLE, PresenceState.PRESENT_IN_DEPT), NOW)
    old = decayed_score(obs(SignalSource.BLE, PresenceState.PRESENT_IN_DEPT, 600), NOW)
    assert fresh > old
    assert round(fresh, 2) == 0.70  # trust at zero age


def test_sim_speed_ages_signals_faster():
    normal = decayed_score(obs(SignalSource.BLE, PresenceState.PRESENT_IN_DEPT, 300), NOW)
    compressed = decayed_score(
        obs(SignalSource.BLE, PresenceState.PRESENT_IN_DEPT, 300), NOW, sim_speed=10
    )
    assert compressed < normal


def test_dead_beacon_degrades_to_roster_never_stays_present():
    """PRD §M1: "What if the beacon battery dies?" """
    stale = [obs(SignalSource.BLE, PresenceState.PRESENT_IN_DEPT, 3600)]
    result = fuse(stale, PresenceState.ON_LEAVE, NOW, current_state=PresenceState.PRESENT_IN_DEPT)
    assert result.state == PresenceState.ON_LEAVE
    assert result.evidence["degraded_to_roster"] is True
    assert result.confidence < 0.5


def test_a_single_fresh_ble_ping_is_enough_to_assert_presence():
    result = fuse([obs(SignalSource.BLE, PresenceState.PRESENT_IN_DEPT)], None, NOW)
    assert result.state == PresenceState.PRESENT_IN_DEPT
    assert result.evidence["top_score"] >= FLIP_THRESHOLD


def test_repeated_sightings_reinforce_each_other():
    one = fuse([obs(SignalSource.BLE, PresenceState.PRESENT_IN_DEPT)], None, NOW)
    many = fuse(
        [obs(SignalSource.BLE, PresenceState.PRESENT_IN_DEPT, s) for s in (0, 60, 120)], None, NOW
    )
    assert many.evidence["top_score"] > one.evidence["top_score"]


# --- conflicting signals ----------------------------------------------------


def test_live_badge_overrides_a_stale_roster():
    """The "why not just an attendance app?" answer: presence beats paperwork."""
    result = fuse(
        [obs(SignalSource.BLE, PresenceState.PRESENT_IN_DEPT)],
        PresenceState.ON_LEAVE,
        NOW,
        # sitting on a roster guess, which is exactly what a real ping should displace
        current_state=PresenceState.ON_LEAVE,
        current_confidence=0.3,
    )
    assert result.state == PresenceState.PRESENT_IN_DEPT
    assert (
        result.evidence["candidates"]["ON_LEAVE"] < result.evidence["candidates"]["PRESENT_IN_DEPT"]
    )


def test_higher_trust_source_wins_a_disagreement():
    result = fuse(
        [
            obs(SignalSource.WIFI, PresenceState.PRESENT_ELSEWHERE),
            obs(SignalSource.RFID, PresenceState.IN_SURGERY),
        ],
        None,
        NOW,
    )
    assert result.state == PresenceState.IN_SURGERY


def test_manual_override_outranks_every_sensor():
    result = fuse(
        [
            obs(SignalSource.BLE, PresenceState.PRESENT_IN_DEPT),
            obs(SignalSource.RFID, PresenceState.PRESENT_IN_DEPT),
            obs(SignalSource.MANUAL, PresenceState.ON_LEAVE),
        ],
        PresenceState.PRESENT_IN_DEPT,
        NOW,
        current_state=PresenceState.PRESENT_IN_DEPT,
        current_confidence=0.9,
    )
    assert result.state == PresenceState.ON_LEAVE
    assert result.evidence["manual_override"] is True


# --- hysteresis -------------------------------------------------------------


def test_a_weak_signal_needs_two_consecutive_wins_to_flip():
    weak = [obs(SignalSource.WIFI, PresenceState.PRESENT_ELSEWHERE)]
    first = fuse(
        weak, None, NOW, current_state=PresenceState.PRESENT_IN_DEPT, current_confidence=0.8
    )
    assert first.state == PresenceState.PRESENT_IN_DEPT, "should not flip on one weak win"
    assert first.evidence["held_by_hysteresis"] is True

    second = fuse(
        weak,
        None,
        NOW,
        current_state=PresenceState.PRESENT_IN_DEPT,
        current_confidence=0.8,
        pending=first.evidence["pending"],
    )
    assert second.state == PresenceState.PRESENT_ELSEWHERE


def test_a_high_trust_signal_flips_immediately():
    """Walking into theatre must show within 10s, not after two sweeps."""
    result = fuse(
        [obs(SignalSource.RFID, PresenceState.IN_SURGERY)],
        None,
        NOW,
        current_state=PresenceState.PRESENT_IN_DEPT,
        current_confidence=0.9,
    )
    assert result.state == PresenceState.IN_SURGERY
    assert result.evidence["held_by_hysteresis"] is False


# --- honesty ----------------------------------------------------------------


def test_no_signals_and_no_roster_is_unknown_not_a_guess():
    result = fuse([], None, NOW)
    assert result.state == PresenceState.UNKNOWN
    assert result.confidence == 0.0


def test_evidence_names_every_contributing_observation():
    result = fuse(
        [obs(SignalSource.BLE, PresenceState.PRESENT_IN_DEPT, signal_id="sig-1", zone_code="Z1")],
        PresenceState.PRESENT_IN_DEPT,
        NOW,
    )
    ids = [c["signal_id"] for c in result.evidence["contributors"]]
    assert "sig-1" in ids
    assert result.evidence["contributors"][0]["zone_code"] == "Z1"


def test_one_rfid_tap_beats_an_hour_of_ble_pings_elsewhere():
    """The core M1 demo: "show me a doctor walking from OPD to surgery".

    Locations compete, they do not accumulate. If OPD sightings summed, ninety
    minutes of badge pings would outweigh the theatre-door reader forever and the
    board would never show the doctor moving.
    """
    opd_pings = [
        obs(SignalSource.BLE, PresenceState.PRESENT_IN_DEPT, ago_seconds=s)
        for s in range(0, 90 * 60, 60)
    ]
    result = fuse(
        [*opd_pings, obs(SignalSource.RFID, PresenceState.IN_SURGERY)],
        PresenceState.PRESENT_IN_DEPT,
        NOW,
        current_state=PresenceState.PRESENT_IN_DEPT,
        current_confidence=0.9,
    )
    assert result.state == PresenceState.IN_SURGERY


def test_corroboration_cannot_overturn_a_stronger_single_source():
    many_weak = [obs(SignalSource.WIFI, PresenceState.PRESENT_ELSEWHERE, s) for s in (0, 5, 10, 15)]
    result = fuse([*many_weak, obs(SignalSource.RFID, PresenceState.IN_SURGERY)], None, NOW)
    assert result.state == PresenceState.IN_SURGERY
