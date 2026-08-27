from fastapi.testclient import TestClient

from services.hello.app import app


def test_hello_http_contract() -> None:
    with TestClient(app) as client:
        response = client.get("/")

    assert response.status_code == 200
    assert response.json()["message"] == "hello"
