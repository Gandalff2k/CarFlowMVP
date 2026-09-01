import uuid
from collections.abc import Callable

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.ext.asyncio import AsyncSession

from services.listing.config import ListingSettings
from services.listing.models import Vehicle
from services.listing.repository import (
    AvailabilityBlockRepository,
    OverlappingAvailabilityBlockError,
    VehicleRepository,
)
from services.listing.schemas import (
    AvailabilityBlockResponse,
    CreateAvailabilityBlockRequest,
    CreateVehicleRequest,
    UpdateVehicleRequest,
    VehicleResponse,
)
from services.listing.service import (
    InvalidApprovalTransitionError,
    NotVehicleOwnerError,
    VehicleNotFoundError,
    add_availability_block,
    approve_vehicle,
    create_vehicle,
    get_vehicle_for_viewer,
    reject_vehicle,
    update_vehicle,
)
from shared.idempotency import IdempotencyGuard, respond_idempotently
from shared.jwt_auth import claims_dependency, require_role


def _vehicle_response(vehicle: Vehicle) -> VehicleResponse:
    return VehicleResponse(
        id=str(vehicle.id),
        host_id=str(vehicle.host_id),
        make=vehicle.make,
        model=vehicle.model,
        year=vehicle.year,
        daily_price_cents=vehicle.daily_price_cents,
        daily_mileage_limit=vehicle.daily_mileage_limit,
        booking_mode=vehicle.booking_mode,
        approval_status=vehicle.approval_status,
    )


def create_router(
    settings: ListingSettings,
    get_session: Callable,
    get_guard: Callable,
) -> APIRouter:
    router = APIRouter()
    get_access_claims = claims_dependency(
        secret=settings.jwt_secret, issuer=settings.jwt_issuer, token_type="access"
    )

    @router.post("/vehicles", status_code=201)
    async def create(
        payload: CreateVehicleRequest,
        session: AsyncSession = Depends(get_session),
        guard: IdempotencyGuard = Depends(get_guard),
        claims: dict = Depends(get_access_claims),
    ) -> Response:
        require_role(claims, "host")
        repo = VehicleRepository(session)

        async def build() -> str:
            vehicle = await create_vehicle(
                repo,
                host_id=uuid.UUID(claims["sub"]),
                make=payload.make,
                model=payload.model,
                year=payload.year,
                daily_price_cents=payload.daily_price_cents,
                daily_mileage_limit=payload.daily_mileage_limit,
                booking_mode=payload.booking_mode,
            )
            return _vehicle_response(vehicle).model_dump_json()

        return await respond_idempotently(guard, 201, build)

    @router.get("/vehicles/{vehicle_id}", response_model=VehicleResponse)
    async def get_vehicle(
        vehicle_id: uuid.UUID,
        session: AsyncSession = Depends(get_session),
        claims: dict = Depends(get_access_claims),
    ) -> VehicleResponse:
        repo = VehicleRepository(session)
        try:
            vehicle = await get_vehicle_for_viewer(
                repo,
                vehicle_id=vehicle_id,
                viewer_id=uuid.UUID(claims["sub"]),
                viewer_role=claims.get("role", ""),
            )
        except VehicleNotFoundError as exc:
            raise HTTPException(status_code=404, detail="vehicle not found") from exc
        except NotVehicleOwnerError as exc:
            raise HTTPException(status_code=403, detail="not your vehicle") from exc
        return _vehicle_response(vehicle)

    @router.patch("/vehicles/{vehicle_id}", status_code=200)
    async def update(
        vehicle_id: uuid.UUID,
        payload: UpdateVehicleRequest,
        session: AsyncSession = Depends(get_session),
        guard: IdempotencyGuard = Depends(get_guard),
        claims: dict = Depends(get_access_claims),
    ) -> Response:
        require_role(claims, "host")
        repo = VehicleRepository(session)

        async def build() -> str:
            try:
                vehicle = await update_vehicle(
                    repo,
                    session,
                    vehicle_id=vehicle_id,
                    host_id=uuid.UUID(claims["sub"]),
                    **payload.model_dump(exclude_unset=True),
                )
            except VehicleNotFoundError as exc:
                raise HTTPException(status_code=404, detail="vehicle not found") from exc
            except NotVehicleOwnerError as exc:
                raise HTTPException(status_code=403, detail="not your vehicle") from exc
            return _vehicle_response(vehicle).model_dump_json()

        return await respond_idempotently(guard, 200, build)

    @router.post("/vehicles/{vehicle_id}/approve", status_code=200)
    async def approve(
        vehicle_id: uuid.UUID,
        session: AsyncSession = Depends(get_session),
        guard: IdempotencyGuard = Depends(get_guard),
        claims: dict = Depends(get_access_claims),
    ) -> Response:
        require_role(claims, "admin")
        repo = VehicleRepository(session)

        async def build() -> str:
            try:
                vehicle = await approve_vehicle(repo, session, vehicle_id=vehicle_id)
            except VehicleNotFoundError as exc:
                raise HTTPException(status_code=404, detail="vehicle not found") from exc
            except InvalidApprovalTransitionError as exc:
                raise HTTPException(
                    status_code=409, detail=f"cannot approve from status '{exc}'"
                ) from exc
            return _vehicle_response(vehicle).model_dump_json()

        return await respond_idempotently(guard, 200, build)

    @router.post("/vehicles/{vehicle_id}/reject", status_code=200)
    async def reject(
        vehicle_id: uuid.UUID,
        session: AsyncSession = Depends(get_session),
        guard: IdempotencyGuard = Depends(get_guard),
        claims: dict = Depends(get_access_claims),
    ) -> Response:
        require_role(claims, "admin")
        repo = VehicleRepository(session)

        async def build() -> str:
            try:
                vehicle = await reject_vehicle(repo, vehicle_id=vehicle_id)
            except VehicleNotFoundError as exc:
                raise HTTPException(status_code=404, detail="vehicle not found") from exc
            except InvalidApprovalTransitionError as exc:
                raise HTTPException(
                    status_code=409, detail=f"cannot reject from status '{exc}'"
                ) from exc
            return _vehicle_response(vehicle).model_dump_json()

        return await respond_idempotently(guard, 200, build)

    @router.post("/vehicles/{vehicle_id}/availability-blocks", status_code=201)
    async def create_availability_block(
        vehicle_id: uuid.UUID,
        payload: CreateAvailabilityBlockRequest,
        session: AsyncSession = Depends(get_session),
        guard: IdempotencyGuard = Depends(get_guard),
        claims: dict = Depends(get_access_claims),
    ) -> Response:
        require_role(claims, "host")
        vehicle_repo = VehicleRepository(session)
        availability_repo = AvailabilityBlockRepository(session)

        async def build() -> str:
            try:
                block = await add_availability_block(
                    availability_repo,
                    vehicle_repo,
                    vehicle_id=vehicle_id,
                    host_id=uuid.UUID(claims["sub"]),
                    start_date=payload.start_date,
                    end_date=payload.end_date,
                )
            except VehicleNotFoundError as exc:
                raise HTTPException(status_code=404, detail="vehicle not found") from exc
            except NotVehicleOwnerError as exc:
                raise HTTPException(status_code=403, detail="not your vehicle") from exc
            except OverlappingAvailabilityBlockError as exc:
                await session.rollback()
                raise HTTPException(
                    status_code=409, detail="availability block overlaps an existing one"
                ) from exc
            return AvailabilityBlockResponse(
                id=str(block.id),
                vehicle_id=str(block.vehicle_id),
                start_date=block.start_date,
                end_date=block.end_date,
            ).model_dump_json()

        return await respond_idempotently(guard, 201, build)

    return router
