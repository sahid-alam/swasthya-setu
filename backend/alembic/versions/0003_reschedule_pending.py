"""appointment_status gains RESCHEDULE_PENDING

A replan that cannot seat someone must not silently cancel them: they are still owed
an appointment, and a cancelled row means the patient finds out by turning up.

Revision ID: 0003_resched_pending
Revises: 0002_zone_code
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0003_resched_pending"
down_revision: str | Sequence[str] | None = "0002_zone_code"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

VALUES = (
    "BOOKED",
    "CHECKED_IN",
    "IN_CONSULT",
    "COMPLETED",
    "NO_SHOW",
    "CANCELLED",
    "RESCHEDULED",
)


def upgrade() -> None:
    # PG 12+ allows ADD VALUE inside a transaction as long as the new value is not
    # *used* in the same transaction. This migration only declares it.
    op.execute("ALTER TYPE appointment_status ADD VALUE IF NOT EXISTS 'RESCHEDULE_PENDING'")


def downgrade() -> None:
    # Postgres cannot drop an enum value, so rebuild the type. Anyone left pending
    # becomes CANCELLED, which is exactly the behaviour this migration replaced.
    listed = ", ".join(f"'{v}'" for v in VALUES)
    op.execute("UPDATE appointments SET status = 'CANCELLED' WHERE status = 'RESCHEDULE_PENDING'")
    op.execute(f"CREATE TYPE appointment_status_old AS ENUM ({listed})")
    op.execute(
        "ALTER TABLE appointments ALTER COLUMN status TYPE appointment_status_old"
        " USING status::text::appointment_status_old"
    )
    op.execute("DROP TYPE appointment_status")
    op.execute("ALTER TYPE appointment_status_old RENAME TO appointment_status")
