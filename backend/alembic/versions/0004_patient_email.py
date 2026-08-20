"""patients.email, and channel gains EMAIL

Email OTP sits beside phone OTP: same service, same JWT, a second way in for a patient
who has an inbox but a phone that drops SMS. The channel value is needed because every
delivery attempt writes a `notifications` row, including this one.

Revision ID: 0004_patient_email
Revises: 0003_resched_pending
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0004_patient_email"
down_revision: str | Sequence[str] | None = "0003_resched_pending"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

VALUES = ("PWA", "WHATSAPP", "SMS", "IVR", "VOICE", "KIOSK", "STAFF")


def upgrade() -> None:
    # Nullable: most patients in Himachal have a phone and no inbox, and an email
    # column that pretends otherwise would be a column of invented addresses.
    op.add_column("patients", sa.Column("email", sa.String(length=160), nullable=True))
    # Case-insensitive, because nobody types their own address the same way twice.
    op.create_index("ix_patients_email_lower", "patients", [sa.text("lower(email)")], unique=False)
    # PG 12+ allows ADD VALUE inside a transaction as long as the new value is not
    # *used* in the same transaction. This migration only declares it.
    op.execute("ALTER TYPE channel ADD VALUE IF NOT EXISTS 'EMAIL'")


def downgrade() -> None:
    op.drop_index("ix_patients_email_lower", table_name="patients")
    op.drop_column("patients", "email")
    # Postgres cannot drop an enum value, so rebuild the type. Any email delivery
    # already logged goes with it — the column it belonged to is going too.
    listed = ", ".join(f"'{v}'" for v in VALUES)
    op.execute("DELETE FROM notifications WHERE channel = 'EMAIL'")
    op.execute(f"CREATE TYPE channel_old AS ENUM ({listed})")
    for table, column in (("notifications", "channel"), ("appointments", "channel")):
        op.execute(
            f"ALTER TABLE {table} ALTER COLUMN {column} TYPE channel_old"
            f" USING {column}::text::channel_old"
        )
    op.execute("DROP TYPE channel")
    op.execute("ALTER TYPE channel_old RENAME TO channel")
