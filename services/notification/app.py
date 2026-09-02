import asyncio
import json
import logging
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from services.notification.config import NotificationSettings
from services.notification.consumers import BOOKING_EVENT_HANDLERS
from shared.db import create_engine, create_session_factory
from shared.kafka_consumer import postgres_inbox_processor, run_consumer
from shared.telemetry import add_health_endpoints, add_http_metrics
from shared.tracing import configure_telemetry


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return json.dumps({"level": record.levelname, "message": record.getMessage()})


def create_app(settings: NotificationSettings | None = None) -> FastAPI:
    service_settings = settings or NotificationSettings()
    logging.basicConfig(stream=sys.stdout, level=logging.INFO, force=True)
    for handler in logging.getLogger().handlers:
        handler.setFormatter(JsonFormatter())

    engine = create_engine(service_settings.database_url)
    session_factory = create_session_factory(engine)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        background_tasks = []
        if service_settings.enable_kafka_consumer:
            background_tasks.append(
                asyncio.create_task(
                    run_consumer(
                        bootstrap_servers=service_settings.kafka_bootstrap_servers,
                        topic=service_settings.booking_events_topic,
                        group_id="notification",
                        process=postgres_inbox_processor(session_factory, BOOKING_EVENT_HANDLERS),
                        tracer_name=service_settings.service_name,
                    )
                )
            )
        try:
            yield
        finally:
            for task in background_tasks:
                task.cancel()
            for task in background_tasks:
                try:
                    await task
                except asyncio.CancelledError:
                    pass

    app = FastAPI(title="CarFlow notification", lifespan=lifespan)
    add_health_endpoints(app)
    add_http_metrics(app, service_settings.service_name)
    configure_telemetry(
        service_settings.service_name,
        service_settings.otel_exporter_otlp_endpoint,
        app,
    )

    return app


app = create_app()
