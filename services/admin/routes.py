import json
import uuid
from collections.abc import Callable

from fastapi import APIRouter, Depends, Header, HTTPException, Response
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from services.admin.clients import BookingClient, ListingClient, UpstreamError
from services.admin.config import AdminSettings
from services.admin.repository import AdminActionRepository
from services.admin.schemas import AdminActionResponse, ListAdminActionsResponse
from services.admin.service import (
    activate_kill_switch,
    approve_vehicle,
    deactivate_kill_switch,
    list_bookings,
    reject_vehicle,
)
from shared.idempotency import IdempotencyGuard, respond_idempotently
from shared.jwt_auth import claims_dependency, require_role


def _action_response(action) -> AdminActionResponse:
    return AdminActionResponse(
        id=str(action.id),
        admin_id=str(action.admin_id),
        action_type=action.action_type,
        target_type=action.target_type,
        target_id=action.target_id,
        payload=action.payload,
        created_at=action.created_at,
    )


def create_router(
    settings: AdminSettings,
    get_session: Callable,
    get_guard: Callable,
    get_redis: Callable,
    listing_client: ListingClient,
    booking_client: BookingClient,
) -> APIRouter:
    router = APIRouter()
    get_access_claims = claims_dependency(
        secret=settings.jwt_secret, issuer=settings.jwt_issuer, token_type="access"
    )

    @router.post("/vehicles/{vehicle_id}/approve", status_code=200)
    async def approve(
        vehicle_id: uuid.UUID,
        session: AsyncSession = Depends(get_session),
        guard: IdempotencyGuard = Depends(get_guard),
        claims: dict = Depends(get_access_claims),
        authorization: str = Header(),
    ) -> Response:
        require_role(claims, "admin")

        async def build() -> str:
            try:
                vehicle = await approve_vehicle(
                    listing_client,
                    AdminActionRepository(session),
                    admin_id=uuid.UUID(claims["sub"]),
                    vehicle_id=vehicle_id,
                    bearer_token=authorization.split(" ", 1)[1],
                )
            except UpstreamError as exc:
                raise HTTPException(status_code=exc.status_code, detail=exc.args[0]) from exc
            return json.dumps(vehicle)

        return await respond_idempotently(guard, 200, build)

    @router.post("/vehicles/{vehicle_id}/reject", status_code=200)
    async def reject(
        vehicle_id: uuid.UUID,
        session: AsyncSession = Depends(get_session),
        guard: IdempotencyGuard = Depends(get_guard),
        claims: dict = Depends(get_access_claims),
        authorization: str = Header(),
    ) -> Response:
        require_role(claims, "admin")

        async def build() -> str:
            try:
                vehicle = await reject_vehicle(
                    listing_client,
                    AdminActionRepository(session),
                    admin_id=uuid.UUID(claims["sub"]),
                    vehicle_id=vehicle_id,
                    bearer_token=authorization.split(" ", 1)[1],
                )
            except UpstreamError as exc:
                raise HTTPException(status_code=exc.status_code, detail=exc.args[0]) from exc
            return json.dumps(vehicle)

        return await respond_idempotently(guard, 200, build)

    @router.get("/bookings")
    async def bookings(
        limit: int = 100,
        offset: int = 0,
        claims: dict = Depends(get_access_claims),
        authorization: str = Header(),
    ) -> dict:
        require_role(claims, "admin")
        try:
            return await list_bookings(
                booking_client,
                bearer_token=authorization.split(" ", 1)[1],
                limit=limit,
                offset=offset,
            )
        except UpstreamError as exc:
            raise HTTPException(status_code=exc.status_code, detail=exc.args[0]) from exc

    @router.post("/vehicles/{vehicle_id}/kill-switch", status_code=204)
    async def enable_kill_switch(
        vehicle_id: uuid.UUID,
        session: AsyncSession = Depends(get_session),
        guard: IdempotencyGuard = Depends(get_guard),
        claims: dict = Depends(get_access_claims),
        redis: Redis = Depends(get_redis),
    ) -> Response:
        require_role(claims, "admin")

        async def build() -> str:
            await activate_kill_switch(
                redis,
                AdminActionRepository(session),
                admin_id=uuid.UUID(claims["sub"]),
                vehicle_id=vehicle_id,
            )
            return ""

        return await respond_idempotently(guard, 204, build)

    @router.delete("/vehicles/{vehicle_id}/kill-switch", status_code=204)
    async def disable_kill_switch(
        vehicle_id: uuid.UUID,
        session: AsyncSession = Depends(get_session),
        guard: IdempotencyGuard = Depends(get_guard),
        claims: dict = Depends(get_access_claims),
        redis: Redis = Depends(get_redis),
    ) -> Response:
        require_role(claims, "admin")

        async def build() -> str:
            await deactivate_kill_switch(
                redis,
                AdminActionRepository(session),
                admin_id=uuid.UUID(claims["sub"]),
                vehicle_id=vehicle_id,
            )
            return ""

        return await respond_idempotently(guard, 204, build)

    @router.get("/actions", response_model=ListAdminActionsResponse)
    async def list_actions(
        limit: int = 100,
        offset: int = 0,
        session: AsyncSession = Depends(get_session),
        claims: dict = Depends(get_access_claims),
    ) -> ListAdminActionsResponse:
        require_role(claims, "admin")
        actions = await AdminActionRepository(session).list_recent(limit=limit, offset=offset)
        return ListAdminActionsResponse(items=[_action_response(a) for a in actions])

    return router
