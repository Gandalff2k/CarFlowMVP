from collections.abc import Callable

from fastapi import APIRouter, Depends, HTTPException
from redis.asyncio import Redis

from services.telemetry.repository import get_latest_position
from services.telemetry.schemas import VehicleLocationResponse
from shared.jwt_auth import claims_dependency


def create_router(settings, get_redis: Callable) -> APIRouter:
    router = APIRouter()
    get_access_claims = claims_dependency(
        secret=settings.jwt_secret, issuer=settings.jwt_issuer, token_type="access"
    )

    @router.get("/vehicles/{vehicle_id}/location", response_model=VehicleLocationResponse)
    async def get_location(
        vehicle_id: str,
        redis: Redis = Depends(get_redis),
        claims: dict = Depends(get_access_claims),
    ) -> VehicleLocationResponse:
        position = await get_latest_position(redis, vehicle_id=vehicle_id)
        if position is None:
            raise HTTPException(status_code=404, detail="no recent location for this vehicle")
        return VehicleLocationResponse(vehicle_id=vehicle_id, **position)

    return router
