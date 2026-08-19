"""SQLAlchemy models — mirrors docs/SCHEMA.md exactly. Update both in the same commit."""

import uuid
from datetime import date, datetime
from enum import Enum, StrEnum

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    UniqueConstraint,
)
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


def pg_enum(enum_cls: type[Enum], name: str) -> SAEnum:
    # create_type=False: migration 0001 creates the types explicitly (autogenerate misses them).
    return SAEnum(enum_cls, name=name, create_type=False)


def fk(target: str, ondelete: str | None = None, **kw) -> Mapped[uuid.UUID]:
    """A nullable FK is an optional relationship, so losing the target clears the
    reference; a required one means the row is owned and follows its parent.
    Deleting a bed must not delete the referral that once reserved it."""
    ondelete = ondelete or ("SET NULL" if kw.get("nullable") else "CASCADE")
    return mapped_column(UUID(as_uuid=True), ForeignKey(target, ondelete=ondelete), **kw)


# --------------------------------------------------------------------------- enums


class HospitalLevel(StrEnum):
    PHC = "PHC"
    CHC = "CHC"
    DISTRICT = "DISTRICT"
    REGIONAL = "REGIONAL"
    MEDICAL_COLLEGE = "MEDICAL_COLLEGE"


class UserRole(StrEnum):
    ADMIN = "ADMIN"
    DOCTOR = "DOCTOR"
    STAFF = "STAFF"
    PATIENT = "PATIENT"


class Language(StrEnum):
    HI = "HI"
    EN = "EN"


class ShiftKind(StrEnum):
    OPD = "OPD"
    WARD = "WARD"
    SURGERY = "SURGERY"
    ON_CALL = "ON_CALL"
    LEAVE = "LEAVE"


class SignalSource(StrEnum):
    BLE = "BLE"
    RFID = "RFID"
    FACE = "FACE"
    WIFI = "WIFI"
    ROSTER = "ROSTER"
    MANUAL = "MANUAL"


class ZoneKind(StrEnum):
    OPD = "OPD"
    WARD = "WARD"
    OT = "OT"
    GATE = "GATE"
    LOBBY = "LOBBY"


class PresenceState(StrEnum):
    PRESENT_IN_DEPT = "PRESENT_IN_DEPT"
    PRESENT_ELSEWHERE = "PRESENT_ELSEWHERE"
    ON_ROUNDS = "ON_ROUNDS"
    IN_SURGERY = "IN_SURGERY"
    ON_LEAVE = "ON_LEAVE"
    OFF_SHIFT = "OFF_SHIFT"
    UNKNOWN = "UNKNOWN"


class SlotStatus(StrEnum):
    OPEN = "OPEN"
    FULL = "FULL"
    BLOCKED = "BLOCKED"


class Channel(StrEnum):
    PWA = "PWA"
    WHATSAPP = "WHATSAPP"
    SMS = "SMS"
    IVR = "IVR"
    VOICE = "VOICE"
    KIOSK = "KIOSK"
    STAFF = "STAFF"


class PriorityClass(StrEnum):
    EMERGENCY = "EMERGENCY"
    REFERRED = "REFERRED"
    PRIORITY = "PRIORITY"
    GENERAL = "GENERAL"


class AppointmentStatus(StrEnum):
    BOOKED = "BOOKED"
    CHECKED_IN = "CHECKED_IN"
    IN_CONSULT = "IN_CONSULT"
    COMPLETED = "COMPLETED"
    NO_SHOW = "NO_SHOW"
    CANCELLED = "CANCELLED"
    RESCHEDULED = "RESCHEDULED"


class QueueState(StrEnum):
    WAITING = "WAITING"
    CALLED = "CALLED"
    SERVING = "SERVING"
    DONE = "DONE"
    SKIPPED = "SKIPPED"


class PlanTrigger(StrEnum):
    PRESENCE_CHANGE = "PRESENCE_CHANGE"
    MANUAL = "MANUAL"
    PERIODIC = "PERIODIC"


class NotificationStatus(StrEnum):
    QUEUED = "QUEUED"
    SENT = "SENT"
    DELIVERED = "DELIVERED"
    FAILED = "FAILED"


class BedKind(StrEnum):
    GENERAL = "GENERAL"
    ICU = "ICU"
    HDU = "HDU"
    MATERNITY = "MATERNITY"
    ISOLATION = "ISOLATION"


class BedState(StrEnum):
    FREE = "FREE"
    OCCUPIED = "OCCUPIED"
    RESERVED = "RESERVED"
    CLEANING = "CLEANING"
    OOO = "OOO"


class ReferralUrgency(StrEnum):
    ROUTINE = "ROUTINE"
    URGENT = "URGENT"
    EMERGENCY = "EMERGENCY"


class ReferralStatus(StrEnum):
    REQUESTED = "REQUESTED"
    RESERVED = "RESERVED"
    CONFIRMED = "CONFIRMED"
    ARRIVED = "ARRIVED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"


class BloodGroup(StrEnum):
    A_POS = "A_POS"
    A_NEG = "A_NEG"
    B_POS = "B_POS"
    B_NEG = "B_NEG"
    AB_POS = "AB_POS"
    AB_NEG = "AB_NEG"
    O_POS = "O_POS"
    O_NEG = "O_NEG"


class BloodComponent(StrEnum):
    WHOLE = "WHOLE"
    PRBC = "PRBC"
    FFP = "FFP"
    PLATELET = "PLATELET"


class BloodSource(StrEnum):
    ERAKTKOSH = "ERAKTKOSH"
    SYNTHETIC = "SYNTHETIC"


class FootfallSource(StrEnum):
    HMIS = "HMIS"
    SYNTHETIC = "SYNTHETIC"


class EmergencyStatus(StrEnum):
    OPEN = "OPEN"
    ROUTED = "ROUTED"
    CLOSED = "CLOSED"


# ----------------------------------------------------------------- core registry


class Hospital(Base):
    __tablename__ = "hospitals"
    name: Mapped[str] = mapped_column(String(200))
    code: Mapped[str] = mapped_column(String(32), unique=True)
    district: Mapped[str] = mapped_column(String(100))
    lat: Mapped[float] = mapped_column(Numeric(9, 6))
    lng: Mapped[float] = mapped_column(Numeric(9, 6))
    level: Mapped[HospitalLevel] = mapped_column(pg_enum(HospitalLevel, "hospital_level"))
    contact: Mapped[str | None] = mapped_column(String(100))


class Department(Base):
    __tablename__ = "departments"
    hospital_id: Mapped[uuid.UUID] = fk("hospitals.id")
    name: Mapped[str] = mapped_column(String(120))
    specialty_code: Mapped[str] = mapped_column(String(32))
    room_count: Mapped[int] = mapped_column(SmallInteger, default=1)


class User(Base):
    __tablename__ = "users"
    name: Mapped[str] = mapped_column(String(160))
    phone: Mapped[str] = mapped_column(String(20), unique=True)
    email: Mapped[str | None] = mapped_column(String(160))
    password_hash: Mapped[str | None] = mapped_column(String(200))
    role: Mapped[UserRole] = mapped_column(pg_enum(UserRole, "user_role"))
    hospital_id: Mapped[uuid.UUID | None] = fk("hospitals.id", nullable=True)


class Doctor(Base):
    __tablename__ = "doctors"
    user_id: Mapped[uuid.UUID] = fk("users.id")
    hospital_id: Mapped[uuid.UUID] = fk("hospitals.id")
    department_id: Mapped[uuid.UUID] = fk("departments.id")
    specialty: Mapped[str] = mapped_column(String(80))
    badge_id: Mapped[str] = mapped_column(String(64), unique=True)  # what BLE/RFID track
    face_enrolled: Mapped[bool] = mapped_column(Boolean, default=False)
    avg_consult_minutes: Mapped[int] = mapped_column(SmallInteger, default=10)


class Patient(Base):
    __tablename__ = "patients"
    user_id: Mapped[uuid.UUID | None] = fk("users.id", nullable=True)
    name: Mapped[str] = mapped_column(String(160))
    phone: Mapped[str] = mapped_column(String(20), index=True)
    age: Mapped[int | None] = mapped_column(SmallInteger)
    gender: Mapped[str | None] = mapped_column(String(16))
    village: Mapped[str | None] = mapped_column(String(120))
    district: Mapped[str | None] = mapped_column(String(100))
    priority_flags: Mapped[dict] = mapped_column(JSONB, default=dict)
    preferred_language: Mapped[Language] = mapped_column(
        pg_enum(Language, "language"), default=Language.HI
    )


# ---------------------------------------------------------------- presence (M1)


class Shift(Base):
    __tablename__ = "shifts"
    doctor_id: Mapped[uuid.UUID] = fk("doctors.id")
    department_id: Mapped[uuid.UUID] = fk("departments.id")
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    kind: Mapped[ShiftKind] = mapped_column(pg_enum(ShiftKind, "shift_kind"))


class Zone(Base):
    __tablename__ = "zones"
    hospital_id: Mapped[uuid.UUID] = fk("hospitals.id")
    department_id: Mapped[uuid.UUID | None] = fk("departments.id", nullable=True)
    name: Mapped[str] = mapped_column(String(120))
    kind: Mapped[ZoneKind] = mapped_column(pg_enum(ZoneKind, "zone_kind"))


class PresenceSignal(Base):
    __tablename__ = "presence_signals"
    __table_args__ = (Index("ix_signals_doctor_observed", "doctor_id", "observed_at"),)
    doctor_id: Mapped[uuid.UUID] = fk("doctors.id")
    source: Mapped[SignalSource] = mapped_column(pg_enum(SignalSource, "signal_source"))
    zone_id: Mapped[uuid.UUID | None] = fk("zones.id", nullable=True)
    raw: Mapped[dict] = mapped_column(JSONB, default=dict)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    trust: Mapped[float] = mapped_column(Numeric(4, 3))


class DoctorStatus(Base):
    """Current fused state — exactly one row per doctor."""

    __tablename__ = "doctor_status"
    doctor_id: Mapped[uuid.UUID] = fk("doctors.id", unique=True)
    state: Mapped[PresenceState] = mapped_column(pg_enum(PresenceState, "presence_state"))
    confidence: Mapped[float] = mapped_column(Numeric(4, 3))
    zone_id: Mapped[uuid.UUID | None] = fk("zones.id", nullable=True)
    since: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    evidence: Mapped[dict] = mapped_column(JSONB, default=dict)


class PresenceTransition(Base):
    """The audit/judge trail — every state flip with its contributing evidence."""

    __tablename__ = "presence_transitions"
    doctor_id: Mapped[uuid.UUID] = fk("doctors.id")
    from_state: Mapped[PresenceState] = mapped_column(pg_enum(PresenceState, "presence_state"))
    to_state: Mapped[PresenceState] = mapped_column(pg_enum(PresenceState, "presence_state"))
    confidence: Mapped[float] = mapped_column(Numeric(4, 3))
    evidence: Mapped[dict] = mapped_column(JSONB, default=dict)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


# -------------------------------------------------------------- scheduling (M2)


class Slot(Base):
    __tablename__ = "slots"
    doctor_id: Mapped[uuid.UUID] = fk("doctors.id")
    department_id: Mapped[uuid.UUID] = fk("departments.id")
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    capacity: Mapped[int] = mapped_column(SmallInteger, default=1)  # >1 = overbook allowance
    status: Mapped[SlotStatus] = mapped_column(
        pg_enum(SlotStatus, "slot_status"), default=SlotStatus.OPEN
    )


class Appointment(Base):
    __tablename__ = "appointments"
    __table_args__ = (
        Index("ix_appointments_slot", "slot_id"),
        Index("ix_appointments_patient_status", "patient_id", "status"),
    )
    patient_id: Mapped[uuid.UUID] = fk("patients.id")
    # RESTRICT: a replan rewrites slots, and it must not take booked appointments
    # (or the rescheduled_from chain behind them) down with it.
    slot_id: Mapped[uuid.UUID] = fk("slots.id", ondelete="RESTRICT")
    hospital_id: Mapped[uuid.UUID] = fk("hospitals.id")
    department_id: Mapped[uuid.UUID] = fk("departments.id")
    channel: Mapped[Channel] = mapped_column(pg_enum(Channel, "channel"))
    priority_class: Mapped[PriorityClass] = mapped_column(
        pg_enum(PriorityClass, "priority_class"), default=PriorityClass.GENERAL
    )
    status: Mapped[AppointmentStatus] = mapped_column(
        pg_enum(AppointmentStatus, "appointment_status"), default=AppointmentStatus.BOOKED
    )
    token_number: Mapped[int | None] = mapped_column(Integer)
    noshow_prob: Mapped[float | None] = mapped_column(Numeric(4, 3))
    predicted_wait_min: Mapped[int | None] = mapped_column(Integer)
    rescheduled_from: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("appointments.id", ondelete="SET NULL"), nullable=True
    )


class QueueEntry(Base):
    __tablename__ = "queue_entries"
    appointment_id: Mapped[uuid.UUID] = fk("appointments.id", unique=True)
    department_id: Mapped[uuid.UUID] = fk("departments.id")
    position: Mapped[int] = mapped_column(Integer)
    checked_in_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    called_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    state: Mapped[QueueState] = mapped_column(
        pg_enum(QueueState, "queue_state"), default=QueueState.WAITING
    )


class PlanRun(Base):
    """Every CP-SAT run — this table is the evidence for the '<5s replan' claim."""

    __tablename__ = "plan_runs"
    trigger: Mapped[PlanTrigger] = mapped_column(pg_enum(PlanTrigger, "plan_trigger"))
    scope: Mapped[dict] = mapped_column(JSONB, default=dict)
    solver_status: Mapped[str] = mapped_column(String(32))
    objective: Mapped[float | None] = mapped_column(Numeric(14, 3))
    duration_ms: Mapped[int] = mapped_column(Integer)
    moved_count: Mapped[int] = mapped_column(Integer, default=0)


class Notification(Base):
    """The demo 'outbox' — mock adapters write real rows here (ARCHITECTURE D4)."""

    __tablename__ = "notifications"
    appointment_id: Mapped[uuid.UUID | None] = fk("appointments.id", nullable=True)
    patient_id: Mapped[uuid.UUID] = fk("patients.id")
    channel: Mapped[Channel] = mapped_column(pg_enum(Channel, "channel"))
    template: Mapped[str] = mapped_column(String(80))
    payload: Mapped[dict] = mapped_column(JSONB, default=dict)
    mock: Mapped[bool] = mapped_column(Boolean, default=True)
    status: Mapped[NotificationStatus] = mapped_column(
        pg_enum(NotificationStatus, "notification_status"), default=NotificationStatus.QUEUED
    )
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


# --------------------------------------------------------- beds & referrals (M5)


class Bed(Base):
    __tablename__ = "beds"
    __table_args__ = (UniqueConstraint("hospital_id", "code"),)
    hospital_id: Mapped[uuid.UUID] = fk("hospitals.id")
    ward: Mapped[str] = mapped_column(String(80))
    code: Mapped[str] = mapped_column(String(32))
    kind: Mapped[BedKind] = mapped_column(pg_enum(BedKind, "bed_kind"))
    state: Mapped[BedState] = mapped_column(pg_enum(BedState, "bed_state"), default=BedState.FREE)


class Referral(Base):
    __tablename__ = "referrals"
    from_hospital_id: Mapped[uuid.UUID] = fk("hospitals.id")
    to_hospital_id: Mapped[uuid.UUID] = fk("hospitals.id")
    patient_id: Mapped[uuid.UUID] = fk("patients.id")
    specialty: Mapped[str] = mapped_column(String(80))
    urgency: Mapped[ReferralUrgency] = mapped_column(pg_enum(ReferralUrgency, "referral_urgency"))
    status: Mapped[ReferralStatus] = mapped_column(
        pg_enum(ReferralStatus, "referral_status"), default=ReferralStatus.REQUESTED
    )
    reserved_bed_id: Mapped[uuid.UUID | None] = fk("beds.id", nullable=True)
    reserved_slot_id: Mapped[uuid.UUID | None] = fk("slots.id", nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    notes: Mapped[str | None] = mapped_column(String(1000))


class BedAllocation(Base):
    __tablename__ = "bed_allocations"
    bed_id: Mapped[uuid.UUID] = fk("beds.id")
    patient_id: Mapped[uuid.UUID | None] = fk("patients.id", nullable=True)
    referral_id: Mapped[uuid.UUID | None] = fk("referrals.id", nullable=True)
    from_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    to_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


# ------------------------------------------------- blood, forecast, routing (M6-M8)


class BloodStock(Base):
    __tablename__ = "blood_stock"
    hospital_id: Mapped[uuid.UUID] = fk("hospitals.id")
    group: Mapped[BloodGroup] = mapped_column(pg_enum(BloodGroup, "blood_group"))
    component: Mapped[BloodComponent] = mapped_column(pg_enum(BloodComponent, "blood_component"))
    units: Mapped[int] = mapped_column(Integer, default=0)
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    source: Mapped[BloodSource] = mapped_column(pg_enum(BloodSource, "blood_source"))


class FootfallHistory(Base):
    __tablename__ = "footfall_history"
    hospital_id: Mapped[uuid.UUID] = fk("hospitals.id")
    department_id: Mapped[uuid.UUID | None] = fk("departments.id", nullable=True)
    date: Mapped[date] = mapped_column(Date)
    visits: Mapped[int] = mapped_column(Integer)
    source: Mapped[FootfallSource] = mapped_column(pg_enum(FootfallSource, "footfall_source"))


class FootfallForecast(Base):
    __tablename__ = "footfall_forecasts"
    hospital_id: Mapped[uuid.UUID] = fk("hospitals.id")
    department_id: Mapped[uuid.UUID | None] = fk("departments.id", nullable=True)
    date: Mapped[date] = mapped_column(Date)
    yhat: Mapped[float] = mapped_column(Numeric(10, 2))
    yhat_lower: Mapped[float] = mapped_column(Numeric(10, 2))
    yhat_upper: Mapped[float] = mapped_column(Numeric(10, 2))
    model_version: Mapped[str] = mapped_column(String(40))


class EmergencyRequest(Base):
    __tablename__ = "emergency_requests"
    lat: Mapped[float] = mapped_column(Numeric(9, 6))
    lng: Mapped[float] = mapped_column(Numeric(9, 6))
    description: Mapped[str | None] = mapped_column(String(1000))
    specialty_needed: Mapped[str | None] = mapped_column(String(80))
    created_by: Mapped[uuid.UUID | None] = fk("users.id", nullable=True)
    status: Mapped[EmergencyStatus] = mapped_column(
        pg_enum(EmergencyStatus, "emergency_status"), default=EmergencyStatus.OPEN
    )


class RouteRanking(Base):
    """Persisted so the Golden Hour judge demo is replayable."""

    __tablename__ = "route_rankings"
    emergency_request_id: Mapped[uuid.UUID] = fk("emergency_requests.id")
    hospital_id: Mapped[uuid.UUID] = fk("hospitals.id")
    rank: Mapped[int] = mapped_column(SmallInteger)
    drive_minutes: Mapped[float] = mapped_column(Numeric(8, 2))
    capability_score: Mapped[float] = mapped_column(Numeric(6, 3))
    reasons: Mapped[dict] = mapped_column(JSONB, default=dict)
