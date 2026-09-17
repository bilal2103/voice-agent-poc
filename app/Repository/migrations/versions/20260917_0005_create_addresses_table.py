"""create addresses table linked to patients

Revision ID: 0005_create_addresses
Revises: 0004_create_calls
Create Date: 2026-09-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0005_create_addresses"
down_revision: str | None = "0004_create_calls"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "addresses",
        sa.Column(
            "address_id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("patient_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("address_line_1", sa.String(length=200), nullable=False),
        sa.Column("address_line_2", sa.String(length=200), nullable=True),
        sa.Column("city", sa.String(length=100), nullable=False),
        sa.Column("state", sa.String(length=2), nullable=False),
        sa.Column("zip_code", sa.String(length=10), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.PrimaryKeyConstraint("address_id", name="pk_addresses"),
        # One address per patient; a retry updates rather than duplicating.
        sa.UniqueConstraint("patient_id", name="uq_addresses_patient_id"),
        # The patient must exist first, and deleting one removes its address.
        sa.ForeignKeyConstraint(
            ["patient_id"],
            ["patients.patient_id"],
            name="fk_addresses_patient_id",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint("char_length(btrim(address_line_1)) > 0", name="ck_addresses_line1_not_blank"),
        sa.CheckConstraint("char_length(btrim(city)) > 0", name="ck_addresses_city_not_blank"),
        sa.CheckConstraint("state ~ '^[A-Z]{2}$'", name="ck_addresses_state_format"),
        sa.CheckConstraint("zip_code ~ '^[0-9]{5}(-[0-9]{4})?$'", name="ck_addresses_zip_format"),
    )
    op.create_index("ix_addresses_patient_id", "addresses", ["patient_id"])
    op.create_index("ix_addresses_zip_code", "addresses", ["zip_code"])


def downgrade() -> None:
    op.drop_index("ix_addresses_zip_code", table_name="addresses")
    op.drop_index("ix_addresses_patient_id", table_name="addresses")
    op.drop_table("addresses")
