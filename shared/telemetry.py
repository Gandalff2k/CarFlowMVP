from collections.abc import Callable
from time import perf_counter

from fastapi import FastAPI, Request, Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest

REQUEST_COUNT = Counter(
    "http_requests_total",
    "Total HTTP requests",
    ("service", "method", "route", "status"),
)
REQUEST_LATENCY = Histogram(
    "http_request_duration_seconds",
    "HTTP request duration in seconds",
    ("service", "method", "route"),
)


def add_health_endpoints(app: FastAPI, readiness_check: Callable[[], bool] | None = None) -> None:
    @app.get("/healthz", include_in_schema=False)
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/readyz", include_in_schema=False)
    async def readyz(response: Response) -> dict[str, str]:
        ready = readiness_check is None or readiness_check()
        if not ready:
            response.status_code = 503
        return {"status": "ok" if ready else "not_ready"}


def add_http_metrics(app: FastAPI, service_name: str) -> None:
    @app.middleware("http")
    async def metrics_middleware(request: Request, call_next: Callable) -> Response:
        started = perf_counter()
        response = await call_next(request)
        route = request.scope.get("route")
        route_name = getattr(route, "path", request.url.path)
        labels = (service_name, request.method, route_name)
        REQUEST_COUNT.labels(*labels, str(response.status_code)).inc()
        REQUEST_LATENCY.labels(*labels).observe(perf_counter() - started)
        return response

    @app.get("/metrics", include_in_schema=False)
    async def metrics() -> Response:
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
