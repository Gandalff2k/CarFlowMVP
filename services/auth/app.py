import json
import logging
import sys

from fastapi import FastAPI

from services.auth.config import AuthSettings
from services.auth.routes import create_router
from shared.db import create_engine, create_session_factory, session_dependency
from shared.idempotency import idempotency_guard_dependency
from shared.telemetry import add_health_endpoints, add_http_metrics
from shared.tracing import configure_telemetry


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return json.dumps({"level": record.levelname, "message": record.getMessage()})


def create_app(settings: AuthSettings | None = None) -> FastAPI:
    service_settings = settings or AuthSettings()
    logging.basicConfig(stream=sys.stdout, level=logging.INFO, force=True)
    for handler in logging.getLogger().handlers:
        handler.setFormatter(JsonFormatter())

    engine = create_engine(service_settings.database_url)
    session_factory = create_session_factory(engine)
    get_session = session_dependency(session_factory)
    get_guard = idempotency_guard_dependency(get_session)

    app = FastAPI(title="CarFlow auth")
    add_health_endpoints(app)
    add_http_metrics(app, service_settings.service_name)
    configure_telemetry(
        service_settings.service_name,
        service_settings.otel_exporter_otlp_endpoint,
        app,
    )
    app.include_router(create_router(service_settings, get_session, get_guard), prefix="/auth")

    return app


app = create_app()
