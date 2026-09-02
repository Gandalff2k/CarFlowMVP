import uuid

import httpx
import pytest
from redis.asyncio import Redis

from services.admin.app import create_app as create_admin_app
from services.admin.clients import ListingClient
from services.admin.config import AdminSettings
from services.auth.security import create_token
from services.listing.app import create_app as create_listing_app
from services.listing.config import ListingSettings
from shared import kill_switch

SECRET = "test-secret"
ISSUER = "carflow-auth"


def _token(*, role: str, user_id: uuid.UUID | None = None) -> str:
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


class FakeBookingClient:
    async def list_bookings(self, *, bearer_token, limit, offset):
        return {"items": [], "next_offset": None}


@pytest.fixture()
async def listing_client(listing_database_url: str):
    settings = ListingSettings(
        service_name="listing-test",
        database_url=listing_database_url,
        otel_exporter_otlp_endpoint="",
        jwt_secret=SECRET,
        jwt_issuer=ISSUER,
    )
    transport = httpx.ASGITransport(app=create_listing_app(settings))
    async with httpx.AsyncClient(transport=transport, base_url="http://listing") as http_client:
        yield http_client


@pytest.fixture()
async def pending_vehicle(listing_client: httpx.AsyncClient) -> str:
    host_token = _token(role="host")
    created = (
        await listing_client.post(
            "/listing/vehicles",
            json={
                "make": "Toyota",
                "model": "Corolla",
                "year": 2020,
                "daily_price_cents": 5000,
                "daily_mileage_limit": 200,
                "booking_mode": "instant",
                "latitude": 40.7128,
                "longitude": -74.0060,
            },
            headers=_headers(host_token, str(uuid.uuid4())),
        )
    ).json()
    return created["id"]


@pytest.fixture()
async def client(admin_database_url: str, redis_url: str, listing_client: httpx.AsyncClient):
    settings = AdminSettings(
        service_name="admin-test",
        database_url=admin_database_url,
        otel_exporter_otlp_endpoint="",
        jwt_secret=SECRET,
        jwt_issuer=ISSUER,
        redis_url=redis_url,
    )
    admin_app = create_admin_app(
        settings,
        listing_client=ListingClient("http://listing", client=listing_client),
        booking_client=FakeBookingClient(),
    )
    transport = httpx.ASGITransport(app=admin_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://admin") as http_client:
        yield http_client


async def test_admin_approves_a_vehicle_and_records_the_action(
    client: httpx.AsyncClient, pending_vehicle: str
) -> None:
    admin_token = _token(role="admin")

    response = await client.post(
        f"/admin/vehicles/{pending_vehicle}/approve",
        headers=_headers(admin_token, str(uuid.uuid4())),
    )
    assert response.status_code == 200
    assert response.json()["approval_status"] == "approved"

    actions = await client.get("/admin/actions", headers=_headers(admin_token))
    assert actions.status_code == 200
    items = actions.json()["items"]
    assert any(a["action_type"] == "vehicle_approved" for a in items)
    assert any(a["target_id"] == pending_vehicle for a in items)


async def test_non_admin_cannot_approve(client: httpx.AsyncClient, pending_vehicle: str) -> None:
    response = await client.post(
        f"/admin/vehicles/{pending_vehicle}/approve",
        headers=_headers(_token(role="host"), str(uuid.uuid4())),
    )

    assert response.status_code == 403


async def test_approve_is_idempotent_under_key_replay(
    client: httpx.AsyncClient, pending_vehicle: str
) -> None:
    admin_token = _token(role="admin")
    key = str(uuid.uuid4())

    first = await client.post(
        f"/admin/vehicles/{pending_vehicle}/approve", headers=_headers(admin_token, key)
    )
    second = await client.post(
        f"/admin/vehicles/{pending_vehicle}/approve", headers=_headers(admin_token, key)
    )

    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()

    actions = (await client.get("/admin/actions", headers=_headers(admin_token))).json()["items"]
    approvals = [a for a in actions if a["target_id"] == pending_vehicle]
    assert len(approvals) == 1  # replayed request never re-ran the handler


async def test_kill_switch_activate_and_deactivate_round_trip(
    client: httpx.AsyncClient, redis_url: str
) -> None:
    admin_token = _token(role="admin")
    vehicle_id = str(uuid.uuid4())
    redis = Redis.from_url(redis_url)

    activate = await client.post(
        f"/admin/vehicles/{vehicle_id}/kill-switch",
        headers=_headers(admin_token, str(uuid.uuid4())),
    )
    assert activate.status_code == 204
    assert await kill_switch.is_active(redis, vehicle_id=vehicle_id) is True

    deactivate = await client.delete(
        f"/admin/vehicles/{vehicle_id}/kill-switch",
        headers=_headers(admin_token, str(uuid.uuid4())),
    )
    assert deactivate.status_code == 204
    assert await kill_switch.is_active(redis, vehicle_id=vehicle_id) is False

    await redis.aclose()


async def test_reject_is_recorded_and_rejects_a_second_approval(
    client: httpx.AsyncClient, pending_vehicle: str
) -> None:
    admin_token = _token(role="admin")

    rejected = await client.post(
        f"/admin/vehicles/{pending_vehicle}/reject",
        headers=_headers(admin_token, str(uuid.uuid4())),
    )
    assert rejected.status_code == 200
    assert rejected.json()["approval_status"] == "rejected"

    approve_after_reject = await client.post(
        f"/admin/vehicles/{pending_vehicle}/approve",
        headers=_headers(admin_token, str(uuid.uuid4())),
    )
    assert approve_after_reject.status_code == 409
