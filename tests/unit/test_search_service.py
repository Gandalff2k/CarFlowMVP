import pytest

from services.search.documents import vehicle_to_document
from services.search.schemas import document_to_result
from services.search.service import InvalidSearchQueryError, handle_vehicle_event, search_vehicles


class FakeSearchRepository:
    def __init__(self) -> None:
        self.upserted: dict[str, dict] = {}
        self.deleted: list[str] = []
        self.search_calls: list[dict] = []

    async def upsert_vehicle(self, vehicle_id, document):
        self.upserted[vehicle_id] = document

    async def delete_vehicle(self, vehicle_id):
        self.deleted.append(vehicle_id)

    async def search(self, **kwargs):
        self.search_calls.append(kwargs)
        return []


def _event_data(**overrides) -> dict:
    data = {
        "vehicle_id": "v1",
        "host_id": "h1",
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


async def test_handle_vehicle_event_upserts_an_approved_vehicle() -> None:
    repo = FakeSearchRepository()

    await handle_vehicle_event(repo, data=_event_data())

    assert "v1" in repo.upserted
    assert repo.upserted["v1"]["make"] == "Toyota"
    assert repo.deleted == []


async def test_handle_vehicle_event_deletes_a_non_approved_vehicle() -> None:
    repo = FakeSearchRepository()

    await handle_vehicle_event(repo, data=_event_data(approval_status="pending"))

    assert repo.deleted == ["v1"]
    assert repo.upserted == {}


def test_vehicle_to_document_shapes_a_geo_point() -> None:
    document = vehicle_to_document(_event_data())

    assert document["location"] == {"lat": 40.7128, "lon": -74.0060}
    assert document["vehicle_id"] == "v1"


def test_document_to_result_round_trips_the_geo_point() -> None:
    document = vehicle_to_document(_event_data())

    result = document_to_result(document)

    assert result.latitude == 40.7128
    assert result.longitude == -74.0060
    assert result.vehicle_id == "v1"


async def test_search_vehicles_rejects_distance_sort_without_coordinates() -> None:
    repo = FakeSearchRepository()

    with pytest.raises(InvalidSearchQueryError):
        await search_vehicles(repo, sort="distance")


async def test_search_vehicles_rejects_radius_without_coordinates() -> None:
    repo = FakeSearchRepository()

    with pytest.raises(InvalidSearchQueryError):
        await search_vehicles(repo, radius_km=10)


async def test_search_vehicles_passes_filters_through_to_the_repository() -> None:
    repo = FakeSearchRepository()

    await search_vehicles(repo, make="Toyota", min_price_cents=1000, sort="price_desc", limit=5)

    assert repo.search_calls == [
        {
            "make": "Toyota",
            "booking_mode": None,
            "min_price_cents": 1000,
            "max_price_cents": None,
            "lat": None,
            "lon": None,
            "radius_km": None,
            "sort": "price_desc",
            "limit": 5,
            "offset": 0,
        }
    ]
