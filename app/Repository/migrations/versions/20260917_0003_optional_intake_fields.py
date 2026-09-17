"""add optional intake fields: insurance, emergency contact, preferred language

Revision ID: 0003_optional_intake
Revises: 0002_expand_patients
Create Date: 2026-09-17

All columns are nullable, so this is safe on a populated table with no backfill.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0003_optional_intake"
down_revision: str | None = "0002_expand_patients"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("patients", sa.Column("insurance_provider", sa.String(length=100), nullable=True))
    op.add_column("patients", sa.Column("insurance_member_id", sa.String(length=50), nullable=True))
    op.add_column(
        "patients", sa.Column("emergency_contact_name", sa.String(length=100), nullable=True)
    )
    op.add_column(
        "patients", sa.Column("emergency_contact_phone", sa.String(length=10), nullable=True)
    )
    op.add_column("patients", sa.Column("preferred_language", sa.String(length=50), nullable=True, default="English"))

    op.create_check_constraint(
        "ck_patients_emergency_phone_digits",
        "patients",
        "emergency_contact_phone IS NULL OR emergency_contact_phone ~ '^[0-9]{10}$'",
    )


def downgrade() -> None:
    op.drop_constraint("ck_patients_emergency_phone_digits", "patients", type_="check")
    op.drop_column("patients", "preferred_language")
    op.drop_column("patients", "emergency_contact_phone")
    op.drop_column("patients", "emergency_contact_name")
    op.drop_column("patients", "insurance_member_id")
    op.drop_column("patients", "insurance_provider")
