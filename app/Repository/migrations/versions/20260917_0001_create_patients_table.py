"""create patients table

Revision ID: 0001_create_patients
Revises:
Create Date: 2026-09-17

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0001_create_patients"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "patients",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("first_name", sa.String(length=50), nullable=False),
        sa.Column("last_name", sa.String(length=50), nullable=False),
        sa.Column("date_of_birth", sa.Date(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_patients"),
        # VARCHAR(50) caps the upper bound; these reject blank/whitespace-only names.
        sa.CheckConstraint(
            "char_length(btrim(first_name)) > 0", name="ck_patients_first_name_not_blank"
        ),
        sa.CheckConstraint(
            "char_length(btrim(last_name)) > 0", name="ck_patients_last_name_not_blank"
        ),
    )
    # A caller identifies a patient by name + DOB, so index that lookup path.
    op.create_index(
        "ix_patients_name_dob",
        "patients",
        ["last_name", "first_name", "date_of_birth"],
    )


def downgrade() -> None:
    op.drop_index("ix_patients_name_dob", table_name="patients")
    op.drop_table("patients")
