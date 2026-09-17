"""Call ORM model — one row per inbound call, with its transcript and summary."""

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    DateTime,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.Repository.database import Base

VAPI_CALL_ID_MAX_LENGTH = 100


class SummaryStatus(str, enum.Enum):
    """Why a summary is or is not present, so a NULL is never a mystery."""

    PENDING = "pending"
    READY = "ready"
    FAILED = "failed"
    SKIPPED = "skipped"


SUMMARY_STATUS_ENUM = Enum(
    SummaryStatus,
    name="summary_status_enum",
    values_callable=lambda enum_cls: [member.value for member in enum_cls],
)


class Call(Base):
    __tablename__ = "calls"

    call_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    #: Vapi's own id. Unique so repeated webhooks for one call upsert rather than duplicate.
    vapi_call_id: Mapped[str] = mapped_column(
        String(VAPI_CALL_ID_MAX_LENGTH), nullable=False, unique=True
    )
    #: As Vapi reports it (E.164), or NULL when the caller withheld it.
    caller_number: Mapped[str | None] = mapped_column(String(32), nullable=True)
    #: Set when a patient was created or updated during the call.
    patient_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("patients.patient_id", ondelete="SET NULL"),
        nullable=True,
    )

    ended_reason: Mapped[str | None] = mapped_column(String(100), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)

    transcript: Mapped[str | None] = mapped_column(Text, nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    summary_status: Mapped[SummaryStatus] = mapped_column(
        SUMMARY_STATUS_ENUM, nullable=False, default=SummaryStatus.PENDING
    )
    #: Why summarisation failed, for debugging without re-running the call.
    summary_error: Mapped[str | None] = mapped_column(String(500), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    __table_args__ = (
        Index("ix_calls_patient_id", "patient_id"),
        Index("ix_calls_created_at", "created_at"),
        Index("ix_calls_summary_status", "summary_status"),
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Call call_id={self.call_id} vapi_call_id={self.vapi_call_id!r}>"
