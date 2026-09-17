"""create calls table for transcripts and summaries

Revision ID: 0004_create_calls
Revises: 0003_optional_intake
Create Date: 2026-09-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0004_create_calls"
down_revision: str | None = "0003_optional_intake"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SUMMARY_STATUSES = ("pending", "ready", "failed", "skipped")


def upgrade() -> None:
    # create_type=False: the explicit create() below owns it, otherwise
    # create_table() emits a second CREATE TYPE and the migration fails.
    summary_status = postgresql.ENUM(
        *SUMMARY_STATUSES, name="summary_status_enum", create_type=False
    )
    summary_status.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "calls",
        sa.Column(
            "call_id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("vapi_call_id", sa.String(length=100), nullable=False),
        sa.Column("caller_number", sa.String(length=32), nullable=True),
        sa.Column("patient_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("ended_reason", sa.String(length=100), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_seconds", sa.Integer(), nullable=True),
        sa.Column("transcript", sa.Text(), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("summary_status", summary_status, nullable=False, server_default="pending"),
        sa.Column("summary_error", sa.String(length=500), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.PrimaryKeyConstraint("call_id", name="pk_calls"),
        # Repeated webhooks for one call must update the row, not duplicate it.
        sa.UniqueConstraint("vapi_call_id", name="uq_calls_vapi_call_id"),
        # Deleting a patient must not delete the record that the call happened.
        sa.ForeignKeyConstraint(
            ["patient_id"],
            ["patients.patient_id"],
            name="fk_calls_patient_id",
            ondelete="SET NULL",
        ),
    )
    op.create_index("ix_calls_patient_id", "calls", ["patient_id"])
    op.create_index("ix_calls_created_at", "calls", ["created_at"])
    op.create_index("ix_calls_summary_status", "calls", ["summary_status"])


def downgrade() -> None:
    op.drop_index("ix_calls_summary_status", table_name="calls")
    op.drop_index("ix_calls_created_at", table_name="calls")
    op.drop_index("ix_calls_patient_id", table_name="calls")
    op.drop_table("calls")
    postgresql.ENUM(name="summary_status_enum").drop(op.get_bind(), checkfirst=True)
