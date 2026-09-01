import uuid

import httpx
import pytest
from fastapi.testclient import TestClient

from services.auth.security import create_token
from services.listing.app import create_app
from services.listing.config import ListingSettings

SECRET = "test-secret"
ISSUER = "carflow-auth"

VEHICLE_PAYLOAD = {
    "make": "Toyota",
    "model": "Corolla",
    "year": 2020,
    "daily_price_cents": 5000,
    "daily_mileage_limit": 200,
    "booking_mode": "instant",
}


def _access_token(*, role: str, user_id: uuid.UUID | None = None) -> str:
    return create_token(
        user_id=user_id or uuid.uuid4(),
        role=role,
        token_type="access",
        secret=SECRET,
        issuer=ISSUER,
        ttl_seconds=900,
    )


def _headers(token: str, idempotency_key: str | None = None) -> dict[str, str]:
    headers = {"Authorization": f"Bearer {token}"}
    if idempotency_key is not None:
        headers["Idempotency-Key"] = idempotency_key
    return headers


def _create_vehicle(
    client: TestClient, host_token: str, idempotency_key: str | None = None
) -> httpx.Response:
    return client.post(
        "/listing/vehicles",
        json=VEHICLE_PAYLOAD,
        headers=_headers(host_token, idempotency_key or str(uuid.uuid4())),
    )


@pytest.fixture()
def client(listing_database_url: str) -> TestClient:
    settings = ListingSettings(
        service_name="listing-test",
        database_url=listing_database_url,
        otel_exporter_otlp_endpoint="",
        jwt_secret=SECRET,
        jwt_issuer=ISSUER,
    )
    with TestClient(create_app(settings)) as test_client:
        yield test_client


def test_host_creates_vehicle_pending(client: TestClient) -> None:
    response = _create_vehicle(client, _access_token(role="host"))

    assert response.status_code == 201
    body = response.json()
    assert body["approval_status"] == "pending"
    assert body["make"] == "Toyota"


def test_renter_cannot_create_vehicle(client: TestClient) -> None:
    response = _create_vehicle(client, _access_token(role="renter"))

    assert response.status_code == 403


def test_host_creates_then_admin_approves(client: TestClient) -> None:
    vehicle_id = _create_vehicle(client, _access_token(role="host")).json()["id"]

    response = client.post(
        f"/listing/vehicles/{vehicle_id}/approve",
        headers=_headers(_access_token(role="admin"), str(uuid.uuid4())),
    )

    assert response.status_code == 200
    assert response.json()["approval_status"] == "approved"


def test_host_cannot_approve_own_vehicle(client: TestClient) -> None:
    host_token = _access_token(role="host")
    vehicle_id = _create_vehicle(client, host_token).json()["id"]

    response = client.post(
        f"/listing/vehicles/{vehicle_id}/approve", headers=_headers(host_token, str(uuid.uuid4()))
    )

    assert response.status_code == 403


def test_approving_twice_is_rejected_by_the_state_machine(client: TestClient) -> None:
    admin_token = _access_token(role="admin")
    vehicle_id = _create_vehicle(client, _access_token(role="host")).json()["id"]
    client.post(
        f"/listing/vehicles/{vehicle_id}/approve", headers=_headers(admin_token, str(uuid.uuid4()))
    )

    second = client.post(
        f"/listing/vehicles/{vehicle_id}/approve", headers=_headers(admin_token, str(uuid.uuid4()))
    )

    assert second.status_code == 409


def test_rejecting_an_approved_vehicle_is_rejected_by_the_state_machine(client: TestClient) -> None:
    admin_token = _access_token(role="admin")
    vehicle_id = _create_vehicle(client, _access_token(role="host")).json()["id"]
    client.post(
        f"/listing/vehicles/{vehicle_id}/approve", headers=_headers(admin_token, str(uuid.uuid4()))
    )

    response = client.post(
        f"/listing/vehicles/{vehicle_id}/reject", headers=_headers(admin_token, str(uuid.uuid4()))
    )

    assert response.status_code == 409


def test_host_can_view_own_vehicle_other_host_cannot(client: TestClient) -> None:
    host_token = _access_token(role="host")
    other_host_token = _access_token(role="host")
    vehicle_id = _create_vehicle(client, host_token).json()["id"]

    own = client.get(f"/listing/vehicles/{vehicle_id}", headers=_headers(host_token))
    other = client.get(f"/listing/vehicles/{vehicle_id}", headers=_headers(other_host_token))

    assert own.status_code == 200
    assert other.status_code == 403


def test_admin_can_view_any_vehicle(client: TestClient) -> None:
    vehicle_id = _create_vehicle(client, _access_token(role="host")).json()["id"]

    response = client.get(
        f"/listing/vehicles/{vehicle_id}", headers=_headers(_access_token(role="admin"))
    )

    assert response.status_code == 200


def test_update_vehicle_changes_price(client: TestClient) -> None:
    host_token = _access_token(role="host")
    vehicle_id = _create_vehicle(client, host_token).json()["id"]

    response = client.patch(
        f"/listing/vehicles/{vehicle_id}",
        json={"daily_price_cents": 7500},
        headers=_headers(host_token, str(uuid.uuid4())),
    )

    assert response.status_code == 200
    assert response.json()["daily_price_cents"] == 7500


def test_create_vehicle_is_idempotent_under_key_replay(client: TestClient) -> None:
    host_token = _access_token(role="host")
    key = str(uuid.uuid4())

    first = _create_vehicle(client, host_token, idempotency_key=key)
    second = _create_vehicle(client, host_token, idempotency_key=key)

    assert first.status_code == second.status_code == 201
    assert first.json() == second.json()


def test_different_hosts_do_not_collide_on_the_same_idempotency_key(client: TestClient) -> None:
    key = str(uuid.uuid4())

    response_a = _create_vehicle(client, _access_token(role="host"), idempotency_key=key)
    response_b = _create_vehicle(client, _access_token(role="host"), idempotency_key=key)

    assert response_a.status_code == response_b.status_code == 201
    assert response_a.json()["id"] != response_b.json()["id"]


def test_availability_block_rejects_overlap(client: TestClient) -> None:
    host_token = _access_token(role="host")
    vehicle_id = _create_vehicle(client, host_token).json()["id"]

    first = client.post(
        f"/listing/vehicles/{vehicle_id}/availability-blocks",
        json={"start_date": "2026-06-01", "end_date": "2026-06-10"},
        headers=_headers(host_token, str(uuid.uuid4())),
    )
    overlapping = client.post(
        f"/listing/vehicles/{vehicle_id}/availability-blocks",
        json={"start_date": "2026-06-05", "end_date": "2026-06-15"},
        headers=_headers(host_token, str(uuid.uuid4())),
    )
    non_overlapping = client.post(
        f"/listing/vehicles/{vehicle_id}/availability-blocks",
        json={"start_date": "2026-06-11", "end_date": "2026-06-20"},
        headers=_headers(host_token, str(uuid.uuid4())),
    )

    assert first.status_code == 201
    assert overlapping.status_code == 409
    assert non_overlapping.status_code == 201


def test_availability_block_rejects_for_non_owner(client: TestClient) -> None:
    other_host_token = _access_token(role="host")
    vehicle_id = _create_vehicle(client, _access_token(role="host")).json()["id"]

    response = client.post(
        f"/listing/vehicles/{vehicle_id}/availability-blocks",
        json={"start_date": "2026-06-01", "end_date": "2026-06-10"},
        headers=_headers(other_host_token, str(uuid.uuid4())),
    )

    assert response.status_code == 403
