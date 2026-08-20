"""patients.registered_via — who walked in through which door

A patient who registered themselves from a chat is not the same thing as one the
hospital entered into its own records, and a screen that cannot tell them apart is a
screen that quietly launders one into the other. Nullable: everyone seeded or entered
by staff has no channel, because nobody self-registered them.

Revision ID: 0006_self_registration
Revises: 0005_telegram
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0006_self_registration"
down_revision: str | Sequence[str] | None = "0005_telegram"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "patients",
        sa.Column(
            "registered_via",
            sa.Enum(name="channel", create_type=False, native_enum=True),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("patients", "registered_via")
