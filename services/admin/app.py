import asyncio
import json
import logging
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import jwt as pyjwt
from fastapi import FastAPI, HTTPException, Request
from redis.asyncio import Redis

from services.admin.clients import BookingClient, ListingClient
from services.admin.config import AdminSettings
from services.admin.routes import create_router
from shared.db import create_engine, create_session_factory, session_dependency
from shared.idempotency import idempotency_guard_dependency, run_idempotency_cleanup_loop
from shared.jwt_auth import bearer_token, decode_token
from shared.telemetry import add_health_endpoints, add_http_metrics
from shared.tracing import configure_telemetry


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return json.dumps({"level": record.levelname, "message": record.getMessage()})


def _consumer_id_resolver(settings: AdminSettings):
    def _resolve(request: Request) -> str:
        try:
            token = bearer_token(request.headers.get("authorization"))
            claims = decode_token(token, secret=settings.jwt_secret, issuer=settings.jwt_issuer)
        except (HTTPException, pyjwt.InvalidTokenError):
            return ""
        return claims.get("sub", "")

    return _resolve


def create_app(
    settings: AdminSettings | None = None,
    listing_client: ListingClient | None = None,
    booking_client: BookingClient | None = None,
) -> FastAPI:
    service_settings = settings or AdminSettings()
    logging.basicConfig(stream=sys.stdout, level=logging.INFO, force=True)
    for handler in logging.getLogger().handlers:
        handler.setFormatter(JsonFormatter())

    engine = create_engine(service_settings.database_url)
    session_factory = create_session_factory(engine)
    get_session = session_dependency(session_factory)
    get_guard = idempotency_guard_dependency(get_session, _consumer_id_resolver(service_settings))
    listing_client = listing_client or ListingClient(service_settings.listing_base_url)
    booking_client = booking_client or BookingClient(service_settings.booking_base_url)
    redis = Redis.from_url(service_settings.redis_url)

    def get_redis() -> Redis:
        return redis

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        cleanup_task = asyncio.create_task(run_idempotency_cleanup_loop(session_factory))
        try:
            yield
        finally:
            cleanup_task.cancel()
            try:
                await cleanup_task
            except asyncio.CancelledError:
                pass
            await redis.aclose()

    app = FastAPI(title="CarFlow admin", lifespan=lifespan)
    add_health_endpoints(app)
    add_http_metrics(app, service_settings.service_name)
    configure_telemetry(
        service_settings.service_name,
        service_settings.otel_exporter_otlp_endpoint,
        app,
    )
    app.include_router(
        create_router(
            service_settings, get_session, get_guard, get_redis, listing_client, booking_client
        ),
        prefix="/admin",
    )

    return app


app = create_app()
