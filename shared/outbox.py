import json
import uuid

from opentelemetry import propagate
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession




def _current_trace_context() -> dict[str, str]:
    carrier: dict[str, str] = {}
    propagate.inject(carrier)
    return carrier


async def write_outbox_event(
    session: AsyncSession,
    *,
    aggregate_type: str,
    aggregate_id: str,
    event_type: str,
    data: dict,
) -> str:
    event_id = str(uuid.uuid4())
    envelope = {
        "event_id": event_id,
        "event_type": event_type,
        "data": data,
        "trace_context": _current_trace_context(),
    }
    await session.execute(
        text(
            "INSERT INTO outbox (id, aggregatetype, aggregateid, type, payload) "
            "VALUES (:id, :aggregatetype, :aggregateid, :type, CAST(:payload AS JSONB))"
        ),
        {
            "id": event_id,
            "aggregatetype": aggregate_type,
            "aggregateid": aggregate_id,
            "type": event_type,
            "payload": json.dumps(envelope),
        },
    )
    return event_id
