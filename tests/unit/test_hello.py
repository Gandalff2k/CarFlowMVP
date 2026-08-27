from fastapi.testclient import TestClient

from services.hello.app import create_app
from shared.settings import ServiceSettings


def test_hello_endpoint() -> None:
    settings = ServiceSettings(service_name="hello-test", otel_exporter_otlp_endpoint="")
    client = TestClient(create_app(settings))

    response = client.get("/")

    assert response.status_code == 200
    assert response.json() == {"service": "hello-test", "message": "hello"}


def test_health_and_readiness() -> None:
    settings = ServiceSettings(service_name="hello-test", otel_exporter_otlp_endpoint="")
    client = TestClient(create_app(settings))

    assert client.get("/healthz").json() == {"status": "ok"}
    assert client.get("/readyz").json() == {"status": "ok"}
