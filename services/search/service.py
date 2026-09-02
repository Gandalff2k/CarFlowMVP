from services.search.documents import vehicle_to_document
from services.search.repository import SearchRepository


class InvalidSearchQueryError(Exception):
    pass


async def handle_vehicle_event(repo: SearchRepository, *, data: dict) -> None:
    """Upsert on approval, delete otherwise. Currently only `vehicle_approved`
    fires with approval_status=approved and `vehicle_updated` can fire for a
    still-pending vehicle (nothing to remove — it was never indexed), but
    checking the flag on every event rather than trusting the event *type*
    means an approved vehicle that's ever unpublished in the future is
    handled correctly without touching this consumer again."""
    if data.get("approval_status") == "approved":
        await repo.upsert_vehicle(data["vehicle_id"], vehicle_to_document(data))
    else:
        await repo.delete_vehicle(data["vehicle_id"])


async def search_vehicles(
    repo: SearchRepository,
    *,
    make: str | None = None,
    booking_mode: str | None = None,
    min_price_cents: int | None = None,
    max_price_cents: int | None = None,
    lat: float | None = None,
    lon: float | None = None,
    radius_km: float | None = None,
    sort: str = "price_asc",
    limit: int = 20,
    offset: int = 0,
) -> list[dict]:
    if sort == "distance" and (lat is None or lon is None):
        raise InvalidSearchQueryError("sort=distance requires lat and lon")
    if radius_km is not None and (lat is None or lon is None):
        raise InvalidSearchQueryError("radius_km requires lat and lon")
    return await repo.search(
        make=make,
        booking_mode=booking_mode,
        min_price_cents=min_price_cents,
        max_price_cents=max_price_cents,
        lat=lat,
        lon=lon,
        radius_km=radius_km,
        sort=sort,
        limit=limit,
        offset=offset,
    )
