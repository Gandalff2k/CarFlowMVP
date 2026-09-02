import hashlib
import json
from collections.abc import Callable

from fastapi import APIRouter, Depends, HTTPException, Query
from redis.asyncio import Redis

from services.search.repository import SearchRepository
from services.search.schemas import SearchResponse, document_to_result
from services.search.service import InvalidSearchQueryError, search_vehicles


def _cache_key(params: dict) -> str:
    normalized = json.dumps(params, sort_keys=True)
    return "search-query:" + hashlib.sha256(normalized.encode()).hexdigest()


def create_router(
    query_cache_ttl_seconds: int,
    get_repo: Callable,
    get_redis: Callable,
) -> APIRouter:
    router = APIRouter()

    @router.get("/vehicles", response_model=SearchResponse)
    async def search(
        make: str | None = None,
        booking_mode: str | None = None,
        min_price_cents: int | None = Query(default=None, ge=0),
        max_price_cents: int | None = Query(default=None, ge=0),
        lat: float | None = Query(default=None, ge=-90, le=90),
        lon: float | None = Query(default=None, ge=-180, le=180),
        radius_km: float | None = Query(default=None, gt=0),
        sort: str = "price_asc",
        limit: int = Query(default=20, gt=0, le=100),
        offset: int = Query(default=0, ge=0),
        repo: SearchRepository = Depends(get_repo),
        redis: Redis = Depends(get_redis),
    ) -> SearchResponse:
        params = {
            "make": make,
            "booking_mode": booking_mode,
            "min_price_cents": min_price_cents,
            "max_price_cents": max_price_cents,
            "lat": lat,
            "lon": lon,
            "radius_km": radius_km,
            "sort": sort,
            "limit": limit,
            "offset": offset,
        }
        cache_key = _cache_key(params)
        cached = await redis.get(cache_key)
        if cached is not None:
            return SearchResponse.model_validate_json(cached)

        try:
            documents = await search_vehicles(repo, **params)
        except InvalidSearchQueryError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        response = SearchResponse(items=[document_to_result(doc) for doc in documents])
        await redis.set(cache_key, response.model_dump_json(), ex=query_cache_ttl_seconds)
        return response

    return router
