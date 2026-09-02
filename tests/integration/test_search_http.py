import uuid

import httpx
import pytest

from services.search.app import create_app
from services.search.config import SearchSettings
from services.search.es_client import create_es_client, ensure_index
from services.search.repository import SearchRepository
from services.search.service import handle_vehicle_event


def _vehicle(**overrides) -> dict:
    data = {
        "vehicle_id": str(uuid.uuid4()),
        "host_id": str(uuid.uuid4()),
        "make": "Toyota",
        "model": "Corolla",
        "year": 2020,
        "daily_price_cents": 5000,
        "daily_mileage_limit": 200,
        "booking_mode": "instant",
        "approval_status": "approved",
        "latitude": 40.7128,
        "longitude": -74.0060,
    }
    data.update(overrides)
    return data


@pytest.fixture()
async def client(elasticsearch_url: str, redis_url: str):
    # A unique index per test: the ES container is session-scoped and shared
    # across every test in this module, so without this, documents from one
    # test would show up in another test's query results.
    index_name = f"vehicles-test-{uuid.uuid4().hex}"
    settings = SearchSettings(
        service_name="search-test",
        otel_exporter_otlp_endpoint="",
        elasticsearch_url=elasticsearch_url,
        redis_url=redis_url,
        index_name=index_name,
        enable_kafka_consumer=False,
        query_cache_ttl_seconds=30,
    )
    app = create_app(settings)
    transport = httpx.ASGITransport(app=app)

    es = create_es_client(elasticsearch_url)
    await ensure_index(es, index_name)
    indexing_repo = SearchRepository(es, index_name)

    async def index(vehicle: dict) -> None:
        await handle_vehicle_event(indexing_repo, data=vehicle)
        await es.indices.refresh(index=index_name)

    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=transport, base_url="http://search") as http_client:
            yield http_client, index
    await es.close()


async def test_query_returns_an_indexed_approved_vehicle(client) -> None:
    http_client, index = client
    vehicle = _vehicle()
    await index(vehicle)

    response = await http_client.get("/search/vehicles")

    assert response.status_code == 200
    ids = [item["vehicle_id"] for item in response.json()["items"]]
    assert vehicle["vehicle_id"] in ids


async def test_facet_filter_by_make(client) -> None:
    http_client, index = client
    toyota = _vehicle(make="Toyota")
    honda = _vehicle(make="Honda")
    await index(toyota)
    await index(honda)

    response = await http_client.get("/search/vehicles", params={"make": "Honda"})

    ids = [item["vehicle_id"] for item in response.json()["items"]]
    assert honda["vehicle_id"] in ids
    assert toyota["vehicle_id"] not in ids


async def test_price_range_and_sort(client) -> None:
    http_client, index = client
    cheap = _vehicle(daily_price_cents=2000)
    pricey = _vehicle(daily_price_cents=9000)
    await index(cheap)
    await index(pricey)

    response = await http_client.get(
        "/search/vehicles", params={"min_price_cents": 1000, "max_price_cents": 5000}
    )

    ids = [item["vehicle_id"] for item in response.json()["items"]]
    assert cheap["vehicle_id"] in ids
    assert pricey["vehicle_id"] not in ids


async def test_geo_distance_filter_excludes_far_away_vehicles(client) -> None:
    http_client, index = client
    nyc = _vehicle(latitude=40.7128, longitude=-74.0060)
    london = _vehicle(latitude=51.5074, longitude=-0.1278)
    await index(nyc)
    await index(london)

    response = await http_client.get(
        "/search/vehicles",
        params={"lat": 40.7128, "lon": -74.0060, "radius_km": 50},
    )

    ids = [item["vehicle_id"] for item in response.json()["items"]]
    assert nyc["vehicle_id"] in ids
    assert london["vehicle_id"] not in ids


async def test_sort_by_distance_orders_nearest_first(client) -> None:
    http_client, index = client
    near = _vehicle(latitude=40.7128, longitude=-74.0060)
    far = _vehicle(latitude=40.9, longitude=-74.3)
    await index(near)
    await index(far)

    response = await http_client.get(
        "/search/vehicles", params={"lat": 40.7128, "lon": -74.0060, "sort": "distance"}
    )

    ids = [item["vehicle_id"] for item in response.json()["items"]]
    assert ids.index(near["vehicle_id"]) < ids.index(far["vehicle_id"])


async def test_distance_sort_without_coordinates_is_rejected(client) -> None:
    http_client, _ = client

    response = await http_client.get("/search/vehicles", params={"sort": "distance"})

    assert response.status_code == 400


async def test_unapproved_vehicle_is_never_returned(client) -> None:
    http_client, index = client
    vehicle = _vehicle(approval_status="pending")
    await index(vehicle)

    response = await http_client.get("/search/vehicles")

    ids = [item["vehicle_id"] for item in response.json()["items"]]
    assert vehicle["vehicle_id"] not in ids


async def test_query_result_is_cached(client) -> None:
    http_client, index = client
    vehicle = _vehicle()
    await index(vehicle)

    first = await http_client.get("/search/vehicles", params={"make": vehicle["make"]})
    # Delete without invalidating the cache: if the second response still
    # contains the vehicle, the query actually served from Redis, not ES.
    await index({**vehicle, "approval_status": "rejected"})
    second = await http_client.get("/search/vehicles", params={"make": vehicle["make"]})

    assert first.json() == second.json()
    ids = [item["vehicle_id"] for item in second.json()["items"]]
    assert vehicle["vehicle_id"] in ids


async def test_query_against_a_missing_index_returns_empty_instead_of_erroring(
    elasticsearch_url: str,
) -> None:
    # Reproduces a real gap found live: deleting the index out-of-band (or
    # querying before startup's ensure_index has run) must not 500 a request
    # that has every right to just mean "no results yet".
    es = create_es_client(elasticsearch_url)
    repo = SearchRepository(es, f"vehicles-missing-{uuid.uuid4().hex}")

    result = await repo.search()

    await es.close()
    assert result == []
