import asyncio
import json
import logging
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import jwt as pyjwt
from fastapi import FastAPI, HTTPException, Request

from services.booking.config import BookingSettings
from services.booking.consumers import PAYMENT_EVENT_HANDLERS
from services.booking.listing_client import ListingClient
from services.booking.routes import create_router
from shared.db import create_engine, create_session_factory, session_dependency
from shared.idempotency import idempotency_guard_dependency, run_idempotency_cleanup_loop
from shared.jwt_auth import bearer_token, decode_token
from shared.kafka_consumer import postgres_inbox_processor, run_consumer
from shared.telemetry import add_health_endpoints, add_http_metrics
from shared.tracing import configure_telemetry


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return json.dumps({"level": record.levelname, "message": record.getMessage()})


def _consumer_id_resolver(settings: BookingSettings):
    def _resolve(request: Request) -> str:
        try:
            token = bearer_token(request.headers.get("authorization"))
            claims = decode_token(token, secret=settings.jwt_secret, issuer=settings.jwt_issuer)
        except (HTTPException, pyjwt.InvalidTokenError):
            return ""
        return claims.get("sub", "")

    return _resolve


def create_app(
    settings: BookingSettings | None = None, listing_client: ListingClient | None = None
) -> FastAPI:
    service_settings = settings or BookingSettings()
    logging.basicConfig(stream=sys.stdout, level=logging.INFO, force=True)
    for handler in logging.getLogger().handlers:
        handler.setFormatter(JsonFormatter())

    engine = create_engine(service_settings.database_url)
    session_factory = create_session_factory(engine)
    get_session = session_dependency(session_factory)
    get_guard = idempotency_guard_dependency(get_session, _consumer_id_resolver(service_settings))
    listing_client = listing_client or ListingClient(service_settings.listing_base_url)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        background_tasks = [asyncio.create_task(run_idempotency_cleanup_loop(session_factory))]
        if service_settings.enable_kafka_consumer:
            background_tasks.append(
                asyncio.create_task(
                    run_consumer(
                        bootstrap_servers=service_settings.kafka_bootstrap_servers,
                        topic=service_settings.payment_events_topic,
                        group_id="booking",
                        process=postgres_inbox_processor(session_factory, PAYMENT_EVENT_HANDLERS),
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

    app = FastAPI(title="CarFlow booking", lifespan=lifespan)
    add_health_endpoints(app)
    add_http_metrics(app, service_settings.service_name)
    configure_telemetry(
        service_settings.service_name,
        service_settings.otel_exporter_otlp_endpoint,
        app,
    )
    app.include_router(
        create_router(service_settings, get_session, get_guard, listing_client), prefix="/booking"
    )

    return app


app = create_app()
