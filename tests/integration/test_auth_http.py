import concurrent.futures
import uuid

import httpx
import pytest
from fastapi.testclient import TestClient

from services.auth.app import create_app
from services.auth.config import AuthSettings

PASSWORD = "correct horse battery staple"
NAME = "Alex Renter"


def _unique_email() -> str:
    return f"user-{uuid.uuid4().hex[:8]}@example.com"


def _register(client: TestClient, email: str, idempotency_key: str | None = None) -> httpx.Response:
    return client.post(
        "/auth/register",
        json={"email": email, "name": NAME, "password": PASSWORD, "role": "renter"},
        headers={"Idempotency-Key": idempotency_key or str(uuid.uuid4())},
    )


@pytest.fixture()
def client(database_url: str) -> TestClient:
    settings = AuthSettings(
        service_name="auth-test",
        database_url=database_url,
        otel_exporter_otlp_endpoint="",
        jwt_secret="test-secret",
    )
    with TestClient(create_app(settings)) as test_client:
        yield test_client


def test_register_then_login_then_call_protected_route(client: TestClient) -> None:
    email = _unique_email()

    register_response = _register(client, email)
    assert register_response.status_code == 201
    assert register_response.json()["email"] == email
    assert register_response.json()["name"] == NAME

    login_response = client.post("/auth/login", json={"email": email, "password": PASSWORD})
    assert login_response.status_code == 200
    tokens = login_response.json()
    assert tokens["access_token"]
    assert tokens["refresh_token"]

    me_response = client.get(
        "/auth/me", headers={"Authorization": f"Bearer {tokens['access_token']}"}
    )
    assert me_response.status_code == 200
    assert me_response.json()["email"] == email


def test_register_rejects_duplicate_email(client: TestClient) -> None:
    email = _unique_email()
    assert _register(client, email).status_code == 201

    second = _register(client, email)

    assert second.status_code == 409


def test_register_concurrent_same_email_never_crashes(client: TestClient) -> None:
    email = _unique_email()

    def call() -> httpx.Response:
        return _register(client, email)

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        responses = [f.result() for f in [executor.submit(call), executor.submit(call)]]

    statuses = sorted(r.status_code for r in responses)
    assert statuses == [201, 409]

    login = client.post("/auth/login", json={"email": email, "password": PASSWORD})
    assert login.status_code == 200


def test_register_is_idempotent_under_key_replay(client: TestClient) -> None:
    email = _unique_email()
    key = str(uuid.uuid4())

    first = _register(client, email, idempotency_key=key)
    second = _register(client, email, idempotency_key=key)

    assert first.status_code == second.status_code == 201
    assert first.json() == second.json()


def test_register_rejects_key_reuse_with_different_payload(client: TestClient) -> None:
    key = str(uuid.uuid4())
    assert _register(client, _unique_email(), idempotency_key=key).status_code == 201

    conflict = _register(client, _unique_email(), idempotency_key=key)

    assert conflict.status_code == 409


def test_register_requires_idempotency_key(client: TestClient) -> None:
    response = client.post(
        "/auth/register",
        json={"email": _unique_email(), "name": NAME, "password": PASSWORD, "role": "renter"},
    )

    assert response.status_code == 400


def test_login_with_wrong_password_is_rejected(client: TestClient) -> None:
    email = _unique_email()
    _register(client, email)

    response = client.post("/auth/login", json={"email": email, "password": "wrong password"})

    assert response.status_code == 401


def test_login_with_unknown_email_is_rejected(client: TestClient) -> None:
    response = client.post("/auth/login", json={"email": _unique_email(), "password": PASSWORD})

    assert response.status_code == 401


def test_protected_route_rejects_missing_token(client: TestClient) -> None:
    assert client.get("/auth/me").status_code == 401


def test_protected_route_rejects_garbage_token(client: TestClient) -> None:
    response = client.get("/auth/me", headers={"Authorization": "Bearer not-a-real-token"})

    assert response.status_code == 401


def test_refresh_issues_a_working_new_access_token(client: TestClient) -> None:
    email = _unique_email()
    _register(client, email)
    login_response = client.post("/auth/login", json={"email": email, "password": PASSWORD})
    refresh_token = login_response.json()["refresh_token"]

    refresh_response = client.post("/auth/refresh", json={"refresh_token": refresh_token})
    assert refresh_response.status_code == 200
    new_access_token = refresh_response.json()["access_token"]

    me_response = client.get("/auth/me", headers={"Authorization": f"Bearer {new_access_token}"})
    assert me_response.status_code == 200
    assert me_response.json()["email"] == email


def test_refresh_rejects_an_access_token(client: TestClient) -> None:
    email = _unique_email()
    _register(client, email)
    login_response = client.post("/auth/login", json={"email": email, "password": PASSWORD})
    access_token = login_response.json()["access_token"]

    response = client.post("/auth/refresh", json={"refresh_token": access_token})

    assert response.status_code == 401
