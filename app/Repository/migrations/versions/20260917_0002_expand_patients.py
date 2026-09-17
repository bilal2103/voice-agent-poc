"""rename id to patient_id; add sex, phone_number, email, deleted_at

Revision ID: 0002_expand_patients
Revises: 0001_create_patients
Create Date: 2026-09-17

New NOT NULL columns are added with a server_default so the migration is safe on
a table that already holds rows; the default is dropped immediately afterwards
so the application must supply a value. Any pre-existing rows would be left with
placeholder sex/phone values needing a backfill.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0002_expand_patients"
down_revision: str | None = "0001_create_patients"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SEX_VALUES = ("Male", "Female", "Other", "Decline to Answer")
PLACEHOLDER_PHONE = "0000000000"


def upgrade() -> None:
    op.alter_column("patients", "id", new_column_name="patient_id")

    sex_enum = postgresql.ENUM(*SEX_VALUES, name="sex_enum")
    sex_enum.create(op.get_bind(), checkfirst=True)

    op.add_column(
        "patients",
        sa.Column("sex", sex_enum, nullable=False, server_default="Decline to Answer"),
    )
    op.add_column(
        "patients",
        sa.Column(
            "phone_number", sa.String(length=10), nullable=False, server_default=PLACEHOLDER_PHONE
        ),
    )
    op.add_column("patients", sa.Column("email", sa.String(length=254), nullable=True))
    op.add_column(
        "patients", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True)
    )

    # Defaults existed only to backfill; new rows must provide their own values.
    op.alter_column("patients", "sex", server_default=None)
    op.alter_column("patients", "phone_number", server_default=None)

    op.create_check_constraint(
        "ck_patients_phone_number_digits", "patients", "phone_number ~ '^[0-9]{10}$'"
    )
    op.create_index("ix_patients_phone_number", "patients", ["phone_number"])
    op.create_index("ix_patients_deleted_at", "patients", ["deleted_at"])


def downgrade() -> None:
    op.drop_index("ix_patients_deleted_at", table_name="patients")
    op.drop_index("ix_patients_phone_number", table_name="patients")
    op.drop_constraint("ck_patients_phone_number_digits", "patients", type_="check")

    op.drop_column("patients", "deleted_at")
    op.drop_column("patients", "email")
    op.drop_column("patients", "phone_number")
    op.drop_column("patients", "sex")

    postgresql.ENUM(name="sex_enum").drop(op.get_bind(), checkfirst=True)

    op.alter_column("patients", "patient_id", new_column_name="id")
