import json
import uuid

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession




async def write_outbox_event(
    session: AsyncSession,
    *,
    aggregate_type: str,
    aggregate_id: str,
    event_type: str,
    payload: dict,
) -> None:
    await session.execute(
        text(
            "INSERT INTO outbox (id, aggregatetype, aggregateid, type, payload) "
            "VALUES (:id, :aggregatetype, :aggregateid, :type, CAST(:payload AS JSONB))"
        ),
        {
            "id": str(uuid.uuid4()),
            "aggregatetype": aggregate_type,
            "aggregateid": aggregate_id,
            "type": event_type,
            "payload": json.dumps(payload),
        },
    )
