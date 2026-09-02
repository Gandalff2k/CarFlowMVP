import asyncio
import json
import logging
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import jwt as pyjwt
from aiokafka import AIOKafkaProducer
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from motor.motor_asyncio import AsyncIOMotorClient
from redis.asyncio import Redis

from services.telemetry.config import TelemetrySettings
from services.telemetry.consumer import run_telemetry_consumer
from services.telemetry.ingest import (
    InvalidPacketError,
    apply_kill_switch,
    parse_packet,
    publish_packet,
)
from services.telemetry.metrics import TELEMETRY_PACKETS_INGESTED
from services.telemetry.routes import create_router
from shared import kill_switch
from shared.jwt_auth import decode_token
from shared.telemetry import add_health_endpoints, add_http_metrics
from shared.tracing import configure_telemetry


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return json.dumps({"level": record.levelname, "message": record.getMessage()})


class _Runtime:
    """Kafka/Mongo/Redis clients, created inside the lifespan's running event
    loop rather than in create_app()'s synchronous body: unlike SQLAlchemy's
    create_async_engine, AIOKafkaProducer's constructor calls
    get_running_loop() immediately and raises if there isn't one yet."""

    producer: AIOKafkaProducer
    mongo_client: AsyncIOMotorClient
    redis: Redis


def create_app(settings: TelemetrySettings | None = None) -> FastAPI:
    service_settings = settings or TelemetrySettings()
    logging.basicConfig(stream=sys.stdout, level=logging.INFO, force=True)
    for handler in logging.getLogger().handlers:
        handler.setFormatter(JsonFormatter())

    runtime = _Runtime()

    def get_redis() -> Redis:
        return runtime.redis

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        runtime.producer = AIOKafkaProducer(
            bootstrap_servers=service_settings.kafka_bootstrap_servers
        )
        runtime.mongo_client = AsyncIOMotorClient(service_settings.mongo_url)
        runtime.redis = Redis.from_url(service_settings.redis_url)
        mongo_db = runtime.mongo_client[service_settings.mongo_db]

        await runtime.producer.start()
        background_tasks = []
        if service_settings.enable_consumer:
            background_tasks.append(
                asyncio.create_task(
                    run_telemetry_consumer(
                        bootstrap_servers=service_settings.kafka_bootstrap_servers,
                        topic=service_settings.raw_topic,
                        group_id="telemetry",
                        mongo_db=mongo_db,
                        redis=runtime.redis,
                        redis_ttl_seconds=service_settings.redis_position_ttl_seconds,
                        batch_size=service_settings.batch_size,
                        batch_interval_seconds=service_settings.batch_interval_seconds,
                        service_name=service_settings.service_name,
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
            await runtime.producer.stop()
            await runtime.redis.aclose()
            runtime.mongo_client.close()

    app = FastAPI(title="CarFlow telemetry", lifespan=lifespan)
    add_health_endpoints(app)
    add_http_metrics(app, service_settings.service_name)
    configure_telemetry(
        service_settings.service_name,
        service_settings.otel_exporter_otlp_endpoint,
        app,
    )
    app.include_router(create_router(service_settings, get_redis), prefix="/telemetry")

    @app.websocket("/telemetry/ingest/{vehicle_id}")
    async def ingest(websocket: WebSocket, vehicle_id: str) -> None:
        token = websocket.query_params.get("token", "")
        try:
            decode_token(
                token, secret=service_settings.jwt_secret, issuer=service_settings.jwt_issuer
            )
        except pyjwt.InvalidTokenError:
            await websocket.close(code=4401)
            return

        await websocket.accept()
        try:
            while True:
                raw = await websocket.receive_text()
                try:
                    packet = parse_packet(raw)
                except InvalidPacketError as exc:
                    await websocket.send_json({"status": "rejected", "detail": str(exc)})
                    continue
                active = await kill_switch.is_active(runtime.redis, vehicle_id=vehicle_id)
                packet = apply_kill_switch(packet, active=active)
                await publish_packet(
                    runtime.producer,
                    topic=service_settings.raw_topic,
                    vehicle_id=vehicle_id,
                    packet=packet,
                )
                TELEMETRY_PACKETS_INGESTED.labels(service_settings.service_name).inc()
                await websocket.send_json({"status": "ok"})
        except WebSocketDisconnect:
            pass

    return app


app = create_app()
