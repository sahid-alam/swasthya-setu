"""Availability is the hinge between M1 and M2: the roster says when slots exist, a
confident presence state can take them away, a guess cannot."""

from datetime import UTC, datetime

from app.models import DoctorStatus, PresenceState
from app.services.availability import SURGERY_BLOCK, is_confident, unavailability_for

NOW = datetime(2026, 8, 20, 10, 0, tzinfo=UTC)


def status(state, confidence, **evidence):
    return DoctorStatus(
        doctor_id=None, state=state, confidence=confidence, since=NOW, evidence=evidence
    )


def test_a_confident_on_leave_removes_availability():
    blocked = unavailability_for(status(PresenceState.ON_LEAVE, 0.95), NOW)
    assert blocked is not None
    assert blocked.until is None  # gone for the day


def test_a_roster_guess_never_removes_availability():
    """The whole point: a degraded state IS the roster, so letting it cancel clinics
    would be the system arguing with itself."""
    guess = status(PresenceState.ON_LEAVE, 0.30, degraded_to_roster=True)
    assert unavailability_for(guess, NOW) is None


def test_low_confidence_is_not_treated_as_fact():
    assert unavailability_for(status(PresenceState.ON_LEAVE, 0.2), NOW) is None


def test_being_present_never_blocks_anything():
    for state in (
        PresenceState.PRESENT_IN_DEPT,
        PresenceState.PRESENT_ELSEWHERE,
        PresenceState.ON_ROUNDS,
    ):
        assert unavailability_for(status(state, 0.9), NOW) is None


def test_surgery_blocks_only_the_theatre_list_not_the_whole_day():
    blocked = unavailability_for(status(PresenceState.IN_SURGERY, 0.9), NOW)
    assert blocked is not None
    assert blocked.until == NOW + SURGERY_BLOCK


def test_an_override_says_so_in_the_reason():
    blocked = unavailability_for(status(PresenceState.ON_LEAVE, 1.0, manual_override=True), NOW)
    assert "administrator" in blocked.reason


def test_unknown_state_with_no_status_is_bookable():
    assert unavailability_for(None, NOW) is None
    assert is_confident(None) is False
