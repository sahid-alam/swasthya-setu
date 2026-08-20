"""zone codes + face embeddings

Zones gain the stable `code` a beacon or reader is provisioned with — the signal
payload in docs/ARCHITECTURE.md addresses zones by code, and `name` is a display
string that may be renamed without reflashing hardware.

Doctors gain `face_embedding` so kiosk check-in has something to match against.
No image is stored, only the vector.

Revision ID: 0002_zone_code
Revises: d7d9c7c6cf60
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0002_zone_code"
down_revision: str | Sequence[str] | None = "d7d9c7c6cf60"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("zones", sa.Column("code", sa.String(length=64), nullable=True))
    # backfill existing rows before the NOT NULL: slugify the name, uniquified by row
    op.execute(
        "UPDATE zones SET code = upper(regexp_replace(name, '[^a-zA-Z0-9]+', '-', 'g'))"
        " || '-' || left(id::text, 4) WHERE code IS NULL"
    )
    op.alter_column("zones", "code", nullable=False)
    op.create_unique_constraint("uq_zones_hospital_id_code", "zones", ["hospital_id", "code"])

    op.add_column(
        "doctors",
        sa.Column("face_embedding", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("doctors", "face_embedding")
    op.drop_constraint("uq_zones_hospital_id_code", "zones", type_="unique")
    op.drop_column("zones", "code")
