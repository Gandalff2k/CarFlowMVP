import uuid

import httpx


class UpstreamError(Exception):
    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code


class ListingClient:
    def __init__(self, base_url: str, client: httpx.AsyncClient | None = None) -> None:
        self._base_url = base_url.rstrip("/")
        self._client = client or httpx.AsyncClient()

    async def approve_vehicle(self, vehicle_id: uuid.UUID, *, bearer_token: str) -> dict:
        response = await self._client.post(
            f"{self._base_url}/listing/vehicles/{vehicle_id}/approve",
            headers={
                "Authorization": f"Bearer {bearer_token}",
                "Idempotency-Key": str(uuid.uuid4()),
            },
        )
        if response.status_code >= 400:
            raise UpstreamError(response.status_code, response.text)
        return response.json()

    async def reject_vehicle(self, vehicle_id: uuid.UUID, *, bearer_token: str) -> dict:
        response = await self._client.post(
            f"{self._base_url}/listing/vehicles/{vehicle_id}/reject",
            headers={
                "Authorization": f"Bearer {bearer_token}",
                "Idempotency-Key": str(uuid.uuid4()),
            },
        )
        if response.status_code >= 400:
            raise UpstreamError(response.status_code, response.text)
        return response.json()


class BookingClient:
    def __init__(self, base_url: str, client: httpx.AsyncClient | None = None) -> None:
        self._base_url = base_url.rstrip("/")
        self._client = client or httpx.AsyncClient()

    async def list_bookings(self, *, bearer_token: str, limit: int, offset: int) -> dict:
        response = await self._client.get(
            f"{self._base_url}/booking/bookings",
            params={"limit": limit, "offset": offset},
            headers={"Authorization": f"Bearer {bearer_token}"},
        )
        if response.status_code >= 400:
            raise UpstreamError(response.status_code, response.text)
        return response.json()
