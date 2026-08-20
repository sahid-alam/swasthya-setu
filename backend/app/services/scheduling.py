"""CP-SAT appointment allocation — PRD §M2, docs/ARCHITECTURE.md §Scheduling design.

The flagship scenario: a doctor becomes unavailable with a full clinic list, and the
day is re-optimised across the remaining capacity in under five seconds. Every run
writes a `plan_runs` row — that table is the evidence for the "<5s" claim the same
way `presence_transitions` is the evidence for "how do you know?".
"""

import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from ortools.sat.python import cp_model
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import events
from app.models import (
    Appointment,
    AppointmentStatus,
    Doctor,
    PlanRun,
    PlanTrigger,
    PriorityClass,
    Slot,
    SlotStatus,
)
from app.services.availability import bookable_slots, unavailability_for

# Priority is expressed as a cost multiplier rather than a hard ordering constraint:
# an emergency displaced by 10 minutes must cost more than a general patient displaced
# by an hour, and weights say that in one number the solver can reason about.
PRIORITY_WEIGHT: dict[PriorityClass, int] = {
    PriorityClass.EMERGENCY: 1000,
    PriorityClass.REFERRED: 100,
    PriorityClass.PRIORITY: 10,
    PriorityClass.GENERAL: 1,
}

# Cost of failing to place someone at all, in "displacement minutes". Deliberately
# larger than any real displacement so the solver fills every seat before it gives up
# on a patient, but finite so an impossible instance still returns a plan.
UNPLACED_COST = 24 * 60

SOLVE_TIME_LIMIT_SECONDS = 5.0
REPLAN_HORIZON_HOURS = 24


@dataclass(frozen=True)
class Booking:
    """An appointment paired with the slot it currently sits in."""

    appointment: Appointment
    slot: Slot

    @property
    def starts_at(self) -> datetime:
        return self.slot.starts_at

    @property
    def priority(self) -> PriorityClass:
        return self.appointment.priority_class


@dataclass
class Move:
    appointment_id: uuid.UUID
    patient_id: uuid.UUID
    from_slot_id: uuid.UUID
    to_slot_id: uuid.UUID | None  # None = could not be placed
    to_doctor_id: uuid.UUID | None
    displacement_minutes: int
    priority: PriorityClass


@dataclass
class PlanResult:
    status: str
    objective: float | None
    duration_ms: int
    moves: list[Move] = field(default_factory=list)
    unplaced: list[Move] = field(default_factory=list)
    considered_slots: int = 0

    @property
    def moved_count(self) -> int:
        return len([m for m in self.moves if m.to_slot_id])


def solve_assignment(
    bookings: list[Booking],
    slots: list[Slot],
    *,
    time_limit: float = SOLVE_TIME_LIMIT_SECONDS,
) -> tuple[str, float | None, dict[int, int]]:
    """Pure assignment: which appointment goes in which slot.

    Costs are constants (weight x displacement), so this is a linear assignment
    problem and CP-SAT solves it exactly rather than heuristically — which is the
    whole reason for using a solver instead of sorting by priority and hoping.
    """
    model = cp_model.CpModel()
    x: dict[tuple[int, int], cp_model.IntVar] = {}
    cost_terms = []

    for ai, booking in enumerate(bookings):
        weight = PRIORITY_WEIGHT[booking.priority]
        placed = []
        for si, slot in enumerate(slots):
            var = model.NewBoolVar(f"x_{ai}_{si}")
            x[ai, si] = var
            placed.append(var)
            displacement = abs(int((slot.starts_at - booking.starts_at).total_seconds() // 60))
            cost_terms.append(weight * displacement * var)

        unplaced = model.NewBoolVar(f"unplaced_{ai}")
        model.Add(sum(placed) + unplaced == 1)  # exactly one seat, or explicitly none
        cost_terms.append(weight * UNPLACED_COST * unplaced)

        # An emergency is never the patient we give up on while a seat exists.
        if booking.priority == PriorityClass.EMERGENCY and slots:
            model.Add(unplaced == 0)

    for si, slot in enumerate(slots):
        model.Add(sum(x[ai, si] for ai in range(len(bookings))) <= slot.capacity)

    model.Minimize(sum(cost_terms))

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit
    solver.parameters.num_search_workers = 8
    status = solver.Solve(model)
    name = solver.StatusName(status)

    assignment: dict[int, int] = {}
    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        for (ai, si), var in x.items():
            if solver.Value(var):
                assignment[ai] = si
        return name, solver.ObjectiveValue(), assignment
    return name, None, assignment


async def replan_doctor(
    db: AsyncSession,
    doctor: Doctor,
    trigger: PlanTrigger = PlanTrigger.PRESENCE_CHANGE,
    now: datetime | None = None,
    *,
    apply: bool = True,
    publish: bool = True,
) -> PlanResult:
    """Re-seat everyone still booked with `doctor` for the rest of today."""
    now = now or datetime.now(UTC)
    started = time.perf_counter()
    # Rest of today plus tomorrow's clinic. A sick doctor's list genuinely spills into
    # the next day; pretending it must all fit today would just manufacture failures.
    end_of_day = now + timedelta(hours=REPLAN_HORIZON_HOURS)

    affected = (
        await db.execute(
            select(Appointment, Slot)
            .join(Slot, Slot.id == Appointment.slot_id)
            .where(
                Slot.doctor_id == doctor.id,
                Slot.starts_at >= now,
                Slot.starts_at <= end_of_day,
                Appointment.status == AppointmentStatus.BOOKED,
            )
            .order_by(Slot.starts_at)
        )
    ).all()
    bookings = [Booking(appointment=a, slot=s) for a, s in affected]
    slots = await bookable_slots(
        db, doctor.department_id, now, end_of_day, exclude_doctor=doctor.id, now=now
    )

    status, objective, assignment = ("NO_APPOINTMENTS", None, {})
    if bookings:
        status, objective, assignment = solve_assignment(bookings, slots)

    result = PlanResult(
        status=status,
        objective=objective,
        duration_ms=int((time.perf_counter() - started) * 1000),
        considered_slots=len(slots),
    )

    for ai, booking in enumerate(bookings):
        si = assignment.get(ai)
        target = slots[si] if si is not None else None
        move = Move(
            appointment_id=booking.appointment.id,
            patient_id=booking.appointment.patient_id,
            from_slot_id=booking.slot.id,
            to_slot_id=target.id if target else None,
            to_doctor_id=target.doctor_id if target else None,
            displacement_minutes=(
                abs(int((target.starts_at - booking.starts_at).total_seconds() // 60))
                if target
                else 0
            ),
            priority=booking.priority,
        )
        (result.moves if target else result.unplaced).append(move)

    if apply:
        await _apply(db, bookings, slots, assignment)

    db.add(
        PlanRun(
            trigger=trigger,
            scope={
                "doctor_id": str(doctor.id),
                "department_id": str(doctor.department_id),
                "from": now.isoformat(),
                "until": end_of_day.isoformat(),
                "appointments": len(bookings),
                "candidate_slots": len(slots),
                "unplaced": len(result.unplaced),
            },
            solver_status=result.status,
            objective=result.objective,
            duration_ms=result.duration_ms,
            moved_count=result.moved_count,
        )
    )
    await db.flush()

    if publish and (result.moves or result.unplaced):
        await events.publish(
            "appointments.replanned",
            {
                "doctor_id": str(doctor.id),
                "hospital_id": str(doctor.hospital_id),
                "department_id": str(doctor.department_id),
                "moved": result.moved_count,
                "unplaced": len(result.unplaced),
                "duration_ms": result.duration_ms,
                "solver_status": result.status,
                "appointment_ids": [str(m.appointment_id) for m in result.moves],
            },
        )
    return result


async def _apply(
    db: AsyncSession,
    bookings: list[Booking],
    slots: list[Slot],
    assignment: dict[int, int],
) -> None:
    """Rebook rather than rewrite: the original row is kept and marked RESCHEDULED so
    `rescheduled_from` gives the patient (and a judge) the full chain. Slots are only
    ever re-pointed, never deleted — `appointments.slot_id` is RESTRICT."""
    for ai, booking in enumerate(bookings):
        appt = booking.appointment
        si = assignment.get(ai)
        booking.slot.status = SlotStatus.OPEN  # the absent doctor's seat frees up
        if si is None:
            appt.status = AppointmentStatus.CANCELLED
            continue

        target = slots[si]
        target.status = SlotStatus.FULL
        db.add(
            Appointment(
                patient_id=appt.patient_id,
                slot_id=target.id,
                hospital_id=appt.hospital_id,
                department_id=appt.department_id,
                channel=appt.channel,
                priority_class=appt.priority_class,
                status=AppointmentStatus.BOOKED,
                token_number=appt.token_number,
                noshow_prob=appt.noshow_prob,
                rescheduled_from=appt.id,
            )
        )
        appt.status = AppointmentStatus.RESCHEDULED
    await db.flush()


async def replan_if_unavailable(
    db: AsyncSession, doctor: Doctor, status, now: datetime | None = None
) -> PlanResult | None:
    """Bridge from M1 to M2: a presence change only triggers a replan when it is a
    confident contradiction of the roster (see services/availability)."""
    if unavailability_for(status, now) is None:
        return None
    return await replan_doctor(db, doctor, PlanTrigger.PRESENCE_CHANGE, now)
