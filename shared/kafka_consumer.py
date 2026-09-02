import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from aiokafka import AIOKafkaConsumer
from opentelemetry import propagate, trace
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from shared.inbox import claim_event

logger = logging.getLogger(__name__)

EventHandler = Callable[[AsyncSession, dict[str, Any]], Awaitable[None]]


async def run_consumer(
    *,
    bootstrap_servers: str,
    topic: str,
    group_id: str,
    session_factory: async_sessionmaker[AsyncSession],
    handlers: dict[str, EventHandler],
    tracer_name: str,
) -> None:
    """Consume `topic` forever, dispatching each envelope to handlers[event_type].

    Unknown event types are acknowledged and skipped (a producer adding a new
    event type must not wedge older consumers). A handler that raises leaves
    the offset uncommitted so the broker redelivers the record.
    """
    tracer = trace.get_tracer(tracer_name)
    consumer = AIOKafkaConsumer(
        topic,
        bootstrap_servers=bootstrap_servers,
        group_id=group_id,
        enable_auto_commit=False,
        auto_offset_reset="earliest",
    )
    await consumer.start()
    try:
        async for record in consumer:
            envelope = json.loads(record.value)
            context = propagate.extract(envelope.get("trace_context", {}))
            with tracer.start_as_current_span(f"consume {envelope['event_type']}", context=context):
                async with session_factory() as session:
                    claimed = await claim_event(session, event_id=envelope["event_id"])
                    if claimed:
                        handler = handlers.get(envelope["event_type"])
                        if handler is not None:
                            await handler(session, envelope["data"])
                        else:
                            logger.info("no handler for event_type=%s", envelope["event_type"])
                    await session.commit()
            await consumer.commit()
    finally:
        await consumer.stop()
