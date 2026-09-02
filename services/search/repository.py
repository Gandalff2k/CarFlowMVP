from elasticsearch import AsyncElasticsearch, NotFoundError


class SearchRepository:
    def __init__(self, es: AsyncElasticsearch, index_name: str) -> None:
        self._es = es
        self._index = index_name

    async def upsert_vehicle(self, vehicle_id: str, document: dict) -> None:
        await self._es.index(index=self._index, id=vehicle_id, document=document)

    async def delete_vehicle(self, vehicle_id: str) -> None:
        try:
            await self._es.delete(index=self._index, id=vehicle_id)
        except NotFoundError:
            pass  # never indexed, or already removed — deleting is a no-op either way

    async def search(
        self,
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
        filters: list[dict] = []
        if make is not None:
            filters.append({"term": {"make": make}})
        if booking_mode is not None:
            filters.append({"term": {"booking_mode": booking_mode}})

        price_range = {}
        if min_price_cents is not None:
            price_range["gte"] = min_price_cents
        if max_price_cents is not None:
            price_range["lte"] = max_price_cents
        if price_range:
            filters.append({"range": {"daily_price_cents": price_range}})

        has_point = lat is not None and lon is not None
        if has_point and radius_km is not None:
            filters.append(
                {
                    "geo_distance": {
                        "distance": f"{radius_km}km",
                        "location": {"lat": lat, "lon": lon},
                    }
                }
            )

        query = {"bool": {"filter": filters}} if filters else {"match_all": {}}

        if sort == "distance":
            sort_clause = [
                {
                    "_geo_distance": {
                        "location": {"lat": lat, "lon": lon},
                        "order": "asc",
                        "unit": "km",
                    }
                }
            ]
        elif sort == "price_desc":
            sort_clause = [{"daily_price_cents": "desc"}]
        else:
            sort_clause = [{"daily_price_cents": "asc"}]

        try:
            result = await self._es.search(
                index=self._index, query=query, sort=sort_clause, from_=offset, size=limit
            )
        except NotFoundError:
            return []  # index not created yet (or deleted out-of-band) — nothing to find
        return [hit["_source"] for hit in result["hits"]["hits"]]
