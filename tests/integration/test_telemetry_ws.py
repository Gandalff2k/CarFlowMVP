import asyncio
import datetime as dt
import time
import uuid

import pytest
from fastapi.testclient import TestClient
from motor.motor_asyncio import AsyncIOMotorClient

from services.auth.security import create_token
from services.telemetry.app import create_app
from services.telemetry.config import TelemetrySettings

SECRET = "test-secret"
ISSUER = "carflow-auth"


def _wait_until(predicate, *, timeout: float = 15.0, interval: float = 0.5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = predicate()
        if result:
            return result
        time.sleep(interval)
    raise AssertionError(f"condition not met within {timeout}s")


def _token() -> str:
    return create_token(
        user_id=uuid.uuid4(),
        role="host",
        token_type="access",
        secret=SECRET,
        issuer=ISSUER,
        ttl_seconds=900,
    )


def _packet(**overrides) -> dict:
    data = {
        "lat": 40.7128,
        "lng": -74.0060,
        "speed_kph": 42.0,
        "recorded_at": dt.datetime.now(dt.UTC).isoformat(),
    }
    data.update(overrides)
    return data


@pytest.fixture()
def settings(kafka_bootstrap_servers: str, mongo_url: str, redis_url: str) -> TelemetrySettings:
    return TelemetrySettings(
        service_name="telemetry-test",
        otel_exporter_otlp_endpoint="",
        kafka_bootstrap_servers=kafka_bootstrap_servers,
        raw_topic=f"telemetry.raw.test-{uuid.uuid4().hex}",
        mongo_url=mongo_url,
        mongo_db=f"telemetry_test_{uuid.uuid4().hex}",
        redis_url=redis_url,
        jwt_secret=SECRET,
        jwt_issuer=ISSUER,
        batch_size=10,
        batch_interval_seconds=0.5,
    )


@pytest.fixture()
def client(settings: TelemetrySettings) -> TestClient:
    with TestClient(create_app(settings)) as test_client:
        yield test_client


def test_ingest_rejects_a_missing_or_invalid_token(client: TestClient) -> None:
    vehicle_id = str(uuid.uuid4())

    with pytest.raises(Exception):
        with client.websocket_connect(f"/telemetry/ingest/{vehicle_id}") as ws:
            ws.receive_text()


def test_ingest_rejects_a_malformed_packet_without_closing_the_connection(
    client: TestClient,
) -> None:
    vehicle_id = str(uuid.uuid4())
    with client.websocket_connect(f"/telemetry/ingest/{vehicle_id}?token={_token()}") as ws:
        ws.send_text("not json")
        response = ws.receive_json()
        assert response["status"] == "rejected"

        ws.send_json(_packet())
        response = ws.receive_json()
        assert response["status"] == "ok"


def test_streamed_packets_land_in_mongo_and_latest_position_in_redis(
    client: TestClient, settings: TelemetrySettings
) -> None:
    vehicle_id = str(uuid.uuid4())
    with client.websocket_connect(f"/telemetry/ingest/{vehicle_id}?token={_token()}") as ws:
        for _ in range(3):
            ws.send_json(_packet())
            assert ws.receive_json()["status"] == "ok"

    def _fetch_location():
        response = client.get(
            f"/telemetry/vehicles/{vehicle_id}/location",
            headers={"Authorization": f"Bearer {_token()}"},
        )
        return response if response.status_code == 200 else None

    location_response = _wait_until(_fetch_location)
    body = location_response.json()
    assert body["vehicle_id"] == vehicle_id
    assert body["lat"] == 40.7128


async def _count_documents(mongo_url: str, db_name: str) -> int:
    client = AsyncIOMotorClient(mongo_url)
    try:
        return await client[db_name].packets.count_documents({})
    finally:
        client.close()


def test_streamed_packets_are_persisted_to_mongo(
    client: TestClient, settings: TelemetrySettings
) -> None:
    vehicle_id = str(uuid.uuid4())
    with client.websocket_connect(f"/telemetry/ingest/{vehicle_id}?token={_token()}") as ws:
        for _ in range(3):
            ws.send_json(_packet())
            ws.receive_json()

    def _count():
        count = asyncio.run(_count_documents(settings.mongo_url, settings.mongo_db))
        return count if count >= 3 else None

    _wait_until(_count)


def test_unknown_vehicle_location_is_404(client: TestClient) -> None:
    response = client.get(
        f"/telemetry/vehicles/{uuid.uuid4()}/location",
        headers={"Authorization": f"Bearer {_token()}"},
    )

    assert response.status_code == 404
