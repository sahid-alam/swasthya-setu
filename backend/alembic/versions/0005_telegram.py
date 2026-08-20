"""patients.telegram_chat_id, and channel gains TELEGRAM

Telegram cannot be addressed by phone number: you can only reply to a chat that has
messaged the bot first. So a patient carries the chat id the bot learned when they
shared their contact, and without it they simply have no Telegram channel.

Revision ID: 0005_telegram
Revises: 0004_patient_email
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0005_telegram"
down_revision: str | Sequence[str] | None = "0004_patient_email"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

VALUES = ("PWA", "WHATSAPP", "SMS", "IVR", "VOICE", "KIOSK", "STAFF", "EMAIL")


def upgrade() -> None:
    # Text, not bigint: it is an opaque identifier from someone else's system that we
    # only ever echo back, and storing it as a number invites arithmetic on it.
    op.add_column("patients", sa.Column("telegram_chat_id", sa.String(length=32), nullable=True))
    op.create_index("ix_patients_telegram", "patients", ["telegram_chat_id"])
    op.execute("ALTER TYPE channel ADD VALUE IF NOT EXISTS 'TELEGRAM'")


def downgrade() -> None:
    op.drop_index("ix_patients_telegram", table_name="patients")
    op.drop_column("patients", "telegram_chat_id")
    listed = ", ".join(f"'{v}'" for v in VALUES)
    op.execute("DELETE FROM notifications WHERE channel = 'TELEGRAM'")
    op.execute(f"CREATE TYPE channel_old AS ENUM ({listed})")
    for table, column in (("notifications", "channel"), ("appointments", "channel")):
        op.execute(
            f"ALTER TABLE {table} ALTER COLUMN {column} TYPE channel_old"
            f" USING {column}::text::channel_old"
        )
    op.execute("DROP TYPE channel")
    op.execute("ALTER TYPE channel_old RENAME TO channel")
