import dataclasses
import uuid

import httpx


class VehicleNotFoundError(Exception):
    pass


@dataclasses.dataclass
class VehicleInfo:
    id: uuid.UUID
    host_id: uuid.UUID
    daily_price_cents: int
    daily_mileage_limit: int
    booking_mode: str
    approval_status: str


class ListingClient:
    """Booking has no DB access to listing (datastore per service), so
    vehicle details are read over HTTP using the caller's own bearer token —
    the same token that already lets a renter view an approved listing."""

    def __init__(self, base_url: str, client: httpx.AsyncClient | None = None) -> None:
        self._base_url = base_url.rstrip("/")
        self._client = client or httpx.AsyncClient()

    async def get_vehicle(self, vehicle_id: uuid.UUID, *, bearer_token: str) -> VehicleInfo:
        response = await self._client.get(
            f"{self._base_url}/listing/vehicles/{vehicle_id}",
            headers={"Authorization": f"Bearer {bearer_token}"},
        )
        if response.status_code in (404, 403):
            raise VehicleNotFoundError(vehicle_id)
        response.raise_for_status()
        body = response.json()
        return VehicleInfo(
            id=uuid.UUID(body["id"]),
            host_id=uuid.UUID(body["host_id"]),
            daily_price_cents=body["daily_price_cents"],
            daily_mileage_limit=body["daily_mileage_limit"],
            booking_mode=body["booking_mode"],
            approval_status=body["approval_status"],
        )
