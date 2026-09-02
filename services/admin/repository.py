import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from services.admin.models import AdminAction


class AdminActionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def record(
        self,
        *,
        admin_id: uuid.UUID,
        action_type: str,
        target_type: str,
        target_id: str,
        payload: dict | None = None,
    ) -> AdminAction:
        action = AdminAction(
            admin_id=admin_id,
            action_type=action_type,
            target_type=target_type,
            target_id=target_id,
            payload=payload or {},
        )
        self._session.add(action)
        await self._session.flush()
        return action

    async def list_recent(self, *, limit: int, offset: int) -> list[AdminAction]:
        result = await self._session.execute(
            select(AdminAction).order_by(AdminAction.created_at.desc()).limit(limit).offset(offset)
        )
        return list(result.scalars().all())
