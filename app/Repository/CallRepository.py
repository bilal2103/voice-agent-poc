"""Data access for calls. Upserts on Vapi's call id."""

import uuid
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.Models.Call import Call


class CallRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_vapi_id(self, vapi_call_id: str) -> Call | None:
        stmt = select(Call).where(Call.vapi_call_id == vapi_call_id)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def get_by_id(self, call_id: uuid.UUID) -> Call | None:
        return await self.session.get(Call, call_id)

    async def upsert(self, vapi_call_id: str, **fields) -> Call:
        """Vapi sends several messages per call, so rows are built up in place.

        Only non-None values overwrite: a later message must not blank out what
        an earlier one already established.
        """
        call = await self.get_by_vapi_id(vapi_call_id)
        if call is None:
            call = Call(vapi_call_id=vapi_call_id)
            self.session.add(call)

        for field, value in fields.items():
            if value is not None:
                setattr(call, field, value)

        await self.session.flush()
        await self.session.refresh(call)
        return call

    async def list(
        self,
        patient_id: uuid.UUID | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Sequence[Call]:
        stmt = select(Call)
        if patient_id is not None:
            stmt = stmt.where(Call.patient_id == patient_id)
        stmt = stmt.order_by(Call.created_at.desc()).limit(limit).offset(offset)
        return (await self.session.execute(stmt)).scalars().all()
