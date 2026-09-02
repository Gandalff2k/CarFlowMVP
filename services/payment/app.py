import asyncio
import json
import logging
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from services.payment.config import PaymentSettings
from services.payment.consumers import build_booking_command_handlers
from services.payment.routes import create_router
from services.payment.stripe_client import StripeClient, StripeTestModeClient
from shared.db import create_engine, create_session_factory, session_dependency
from shared.kafka_consumer import run_consumer
from shared.telemetry import add_health_endpoints, add_http_metrics
from shared.tracing import configure_telemetry


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return json.dumps({"level": record.levelname, "message": record.getMessage()})


def create_app(
    settings: PaymentSettings | None = None, stripe_client: StripeClient | None = None
) -> FastAPI:
    service_settings = settings or PaymentSettings()
    logging.basicConfig(stream=sys.stdout, level=logging.INFO, force=True)
    for handler in logging.getLogger().handlers:
        handler.setFormatter(JsonFormatter())

    engine = create_engine(service_settings.database_url)
    session_factory = create_session_factory(engine)
    get_session = session_dependency(session_factory)
    client = stripe_client or StripeTestModeClient(
        api_key=service_settings.stripe_api_key,
        test_payment_method=service_settings.stripe_test_payment_method,
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        background_tasks = []
        if service_settings.enable_kafka_consumer:
            background_tasks.append(
                asyncio.create_task(
                    run_consumer(
                        bootstrap_servers=service_settings.kafka_bootstrap_servers,
                        topic=service_settings.booking_commands_topic,
                        group_id="payment",
                        session_factory=session_factory,
                        handlers=build_booking_command_handlers(client),
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

    app = FastAPI(title="CarFlow payment", lifespan=lifespan)
    add_health_endpoints(app)
    add_http_metrics(app, service_settings.service_name)
    configure_telemetry(
        service_settings.service_name,
        service_settings.otel_exporter_otlp_endpoint,
        app,
    )
    app.include_router(create_router(service_settings, get_session), prefix="/payment")

    return app


app = create_app()
