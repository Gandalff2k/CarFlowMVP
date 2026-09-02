import asyncio
import json
import logging
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from redis.asyncio import Redis

from services.search.config import SearchSettings
from services.search.consumers import build_listing_event_processor
from services.search.es_client import create_es_client, ensure_index
from services.search.repository import SearchRepository
from services.search.routes import create_router
from shared.kafka_consumer import run_consumer
from shared.telemetry import add_health_endpoints, add_http_metrics
from shared.tracing import configure_telemetry


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return json.dumps({"level": record.levelname, "message": record.getMessage()})


def create_app(settings: SearchSettings | None = None) -> FastAPI:
    service_settings = settings or SearchSettings()
    logging.basicConfig(stream=sys.stdout, level=logging.INFO, force=True)
    for handler in logging.getLogger().handlers:
        handler.setFormatter(JsonFormatter())

    es = create_es_client(service_settings.elasticsearch_url)
    redis = Redis.from_url(service_settings.redis_url)
    repo = SearchRepository(es, service_settings.index_name)

    def get_repo() -> SearchRepository:
        return repo

    def get_redis() -> Redis:
        return redis

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        await ensure_index(es, service_settings.index_name)
        background_tasks = []
        if service_settings.enable_kafka_consumer:
            background_tasks.append(
                asyncio.create_task(
                    run_consumer(
                        bootstrap_servers=service_settings.kafka_bootstrap_servers,
                        topic=service_settings.listing_events_topic,
                        group_id="search",
                        process=build_listing_event_processor(redis, repo),
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
            await es.close()
            await redis.aclose()

    app = FastAPI(title="CarFlow search", lifespan=lifespan)
    add_health_endpoints(app)
    add_http_metrics(app, service_settings.service_name)
    configure_telemetry(
        service_settings.service_name,
        service_settings.otel_exporter_otlp_endpoint,
        app,
    )
    app.include_router(
        create_router(service_settings.query_cache_ttl_seconds, get_repo, get_redis),
        prefix="/search",
    )

    return app


app = create_app()
