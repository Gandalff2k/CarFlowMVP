import json
import logging
import sys

from fastapi import FastAPI

from shared.settings import ServiceSettings
from shared.telemetry import add_health_endpoints, add_http_metrics
from shared.tracing import configure_telemetry


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return json.dumps({"level": record.levelname, "message": record.getMessage()})


def create_app(settings: ServiceSettings | None = None) -> FastAPI:
    service_settings = settings or ServiceSettings(service_name="hello")
    logging.basicConfig(stream=sys.stdout, level=logging.INFO, force=True)
    for handler in logging.getLogger().handlers:
        handler.setFormatter(JsonFormatter())

    app = FastAPI(title="CarFlow hello")
    add_health_endpoints(app)
    add_http_metrics(app, service_settings.service_name)
    configure_telemetry(
        service_settings.service_name,
        service_settings.otel_exporter_otlp_endpoint,
        app,
    )

    @app.get("/")
    async def hello() -> dict[str, str]:
        logging.getLogger(__name__).info("hello request")
        return {"service": service_settings.service_name, "message": "hello"}

    return app


app = create_app()
