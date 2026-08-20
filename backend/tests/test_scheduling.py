"""CP-SAT allocation — PRD §M2. The solver core is exercised directly so priority
behaviour is provable without a database."""

import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from app.models import PriorityClass
from app.services.scheduling import PRIORITY_WEIGHT, solve_assignment

NOW = datetime(2026, 8, 20, 9, 0, tzinfo=UTC)


@dataclass
class FakeAppt:
    priority_class: PriorityClass
    id: str = "a"
    patient_id: str = "p"


@dataclass
class FakeSlot:
    starts_at: datetime
    capacity: int = 1
    id: str = "s"
    doctor_id: str = "d"


@dataclass
class FakeBooking:
    appointment: FakeAppt
    slot: FakeSlot

    @property
    def starts_at(self):
        return self.slot.starts_at

    @property
    def priority(self):
        return self.appointment.priority_class


def booking(priority, minute):
    return FakeBooking(FakeAppt(priority_class=priority), FakeSlot(NOW + timedelta(minutes=minute)))


def slot(minute, capacity=1):
    return FakeSlot(NOW + timedelta(minutes=minute), capacity=capacity)


def test_everyone_is_seated_when_there_is_room():
    bookings = [booking(PriorityClass.GENERAL, m) for m in (0, 10, 20)]
    status, _, assignment = solve_assignment(bookings, [slot(m) for m in (0, 10, 20)])
    assert status == "OPTIMAL"
    assert len(assignment) == 3


def test_the_solver_keeps_people_close_to_their_original_time():
    _, _, assignment = solve_assignment([booking(PriorityClass.GENERAL, 0)], [slot(240), slot(5)])
    assert assignment[0] == 1, "should pick the 5-minute displacement, not the 4-hour one"


def test_scarcity_goes_to_the_higher_priority_patient():
    """One seat, two patients. Priority is a cost multiplier, so the emergency wins."""
    bookings = [booking(PriorityClass.GENERAL, 0), booking(PriorityClass.EMERGENCY, 0)]
    _, _, assignment = solve_assignment(bookings, [slot(0)])
    assert 1 in assignment and 0 not in assignment


def test_an_emergency_is_never_the_one_left_unplaced():
    bookings = [booking(PriorityClass.EMERGENCY, 0)] + [
        booking(PriorityClass.GENERAL, 0) for _ in range(5)
    ]
    _, _, assignment = solve_assignment(bookings, [slot(0)])
    assert 0 in assignment


def test_priority_ordering_is_strictly_ranked():
    assert (
        PRIORITY_WEIGHT[PriorityClass.EMERGENCY]
        > PRIORITY_WEIGHT[PriorityClass.REFERRED]
        > PRIORITY_WEIGHT[PriorityClass.PRIORITY]
        > PRIORITY_WEIGHT[PriorityClass.GENERAL]
    )


def test_slot_capacity_is_respected():
    bookings = [booking(PriorityClass.GENERAL, 0) for _ in range(5)]
    _, _, assignment = solve_assignment(bookings, [slot(0, capacity=2)])
    assert len(assignment) == 2, "an overbooked slot must not absorb the whole clinic"


def test_no_slots_means_nobody_is_placed_rather_than_a_crash():
    status, _, assignment = solve_assignment([booking(PriorityClass.GENERAL, 0)], [])
    assert status in ("OPTIMAL", "FEASIBLE")
    assert assignment == {}


def test_a_full_clinic_list_solves_well_inside_the_five_second_budget():
    """PRD §M2 names 40 patients; this is that shape with room to spare."""
    bookings = [booking(PriorityClass.GENERAL, m * 10) for m in range(40)]
    slots = [slot(m * 10) for m in range(120)]
    started = time.perf_counter()
    status, _, assignment = solve_assignment(bookings, slots)
    elapsed = time.perf_counter() - started
    assert status == "OPTIMAL"
    assert len(assignment) == 40
    assert elapsed < 5.0, f"took {elapsed:.2f}s"
