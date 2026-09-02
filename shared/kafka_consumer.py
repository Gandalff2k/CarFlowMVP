import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from aiokafka import AIOKafkaConsumer
from opentelemetry import propagate, trace
from prometheus_client import Gauge
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from shared.inbox import claim_event

logger = logging.getLogger(__name__)

EventHandler = Callable[[AsyncSession, dict[str, Any]], Awaitable[None]]
EventProcessor = Callable[[str, str, dict[str, Any]], Awaitable[None]]

# Labeled by service + topic only — never by partition or consumer-group
# member, which would be unbounded/high-cardinality for no operational
# benefit (there's one group per service per topic in this codebase anyway).
KAFKA_CONSUMER_LAG = Gauge(
    "kafka_consumer_lag",
    "Messages behind the topic's latest offset, summed across assigned partitions",
    ("service", "topic"),
)


async def report_consumer_lag(consumer: AIOKafkaConsumer, *, service: str, topic: str) -> None:
    total_lag = 0
    for partition in consumer.assignment():
        highwater = consumer.highwater(partition)
        if highwater is None:
            continue
        position = await consumer.position(partition)
        total_lag += max(highwater - position, 0)
    KAFKA_CONSUMER_LAG.labels(service, topic).set(total_lag)


def decode_envelope(raw: bytes) -> dict[str, Any]:
    """Debezium never parses a Postgres json/jsonb column into a structured
    Connect value — io.debezium.data.Json is always backed by a plain
    string, so the outbox EventRouter SMT's payload field is a string too,
    and JsonConverter (schemas disabled) serializes that string as a JSON
    string literal. The real message value is therefore JSON-encoded twice,
    not once; a hand-shipped test payload (one encoding) must still work."""
    envelope = json.loads(raw)
    if isinstance(envelope, str):
        envelope = json.loads(envelope)
    return envelope


async def run_consumer(
    *,
    bootstrap_servers: str,
    topic: str,
    group_id: str,
    process: EventProcessor,
    tracer_name: str,
) -> None:
    """Consume `topic` forever, handing each envelope to `process(event_id,
    event_type, data)`. `process` owns dedup and dispatch — how and where it
    tracks "already handled" is entirely up to the caller (a Postgres inbox
    table transactionally tied to the effect, a Redis SETNX, ...); this loop
    only knows about Kafka and tracing. A `process` that raises leaves the
    offset uncommitted so the broker redelivers the record.
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
            envelope = decode_envelope(record.value)
            try:
                context = propagate.extract(envelope.get("trace_context", {}))
                with tracer.start_as_current_span(
                    f"consume {envelope['event_type']}", context=context
                ):
                    await process(envelope["event_id"], envelope["event_type"], envelope["data"])
            except Exception:
                # Without this, an unhandled error here only ever surfaces
                # via asyncio's default handler when the Task object is
                # garbage-collected — which, held alive in a service's
                # background_tasks list for its whole lifetime, may never
                # happen. Log immediately, then still fail loudly (offset
                # stays uncommitted; the process is expected to be restarted
                # by the orchestrator and redeliver the record).
                logger.exception("failed to process event_type=%s", envelope.get("event_type"))
                raise
            await consumer.commit()
            await report_consumer_lag(consumer, service=tracer_name, topic=topic)
    finally:
        await consumer.stop()


def postgres_inbox_processor(
    session_factory: async_sessionmaker[AsyncSession],
    handlers: dict[str, EventHandler],
) -> EventProcessor:
    """The `process` callable for services whose consumer effects live in
    Postgres: claim + dispatch + commit happen in one transaction, so a crash
    between claiming the event and applying its effect rolls both back
    together and the event is retried whole, never half-applied."""

    async def process(event_id: str, event_type: str, data: dict[str, Any]) -> None:
        async with session_factory() as session:
            if await claim_event(session, event_id=event_id):
                handler = handlers.get(event_type)
                if handler is not None:
                    await handler(session, data)
                else:
                    logger.info("no handler for event_type=%s", event_type)
            await session.commit()

    return process
