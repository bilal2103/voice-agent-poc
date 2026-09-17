"""Data access for patient addresses."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.Models.Address import Address


class AddressRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_patient_id(self, patient_id: uuid.UUID) -> Address | None:
        stmt = select(Address).where(Address.patient_id == patient_id)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def add(self, address: Address) -> Address:
        self.session.add(address)
        await self.session.flush()
        await self.session.refresh(address)
        return address

    async def update(self, address: Address, changes: dict) -> Address:
        for field, value in changes.items():
            setattr(address, field, value)
        await self.session.flush()
        await self.session.refresh(address)
        return address

    async def delete(self, address: Address) -> None:
        await self.session.delete(address)
        await self.session.flush()
