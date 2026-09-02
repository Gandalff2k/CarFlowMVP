import uuid
from collections.abc import Callable

from fastapi import APIRouter, Depends, Header, HTTPException, Response
from sqlalchemy.ext.asyncio import AsyncSession

from services.booking.config import BookingSettings
from services.booking.domain import InvalidBookingTransitionError
from services.booking.listing_client import ListingClient
from services.booking.models import Booking
from services.booking.repository import BookingRepository, OverlappingBookingError
from services.booking.schemas import (
    BookingResponse,
    CreateBookingRequest,
    HandoverRequest,
    ListBookingsResponse,
    ReturnRequest,
)
from services.booking.service import (
    BookingNotFoundError,
    NotBookingPartyError,
    VehicleNotBookableError,
    accept_booking_request,
    get_booking_for_viewer,
    list_all_bookings,
    record_handover,
    record_return,
    reject_booking_request,
    request_booking,
)
from shared.idempotency import IdempotencyGuard, respond_idempotently
from shared.jwt_auth import claims_dependency, require_role


def _booking_response(booking: Booking) -> BookingResponse:
    return BookingResponse(
        id=str(booking.id),
        vehicle_id=str(booking.vehicle_id),
        host_id=str(booking.host_id),
        renter_id=str(booking.renter_id),
        start_date=booking.start_date,
        end_date=booking.end_date,
        daily_price_cents=booking.daily_price_cents,
        daily_mileage_limit=booking.daily_mileage_limit,
        booking_mode=booking.booking_mode,
        status=booking.status,
        start_odometer=booking.start_odometer,
        end_odometer=booking.end_odometer,
        start_fuel_percent=booking.start_fuel_percent,
        end_fuel_percent=booking.end_fuel_percent,
        start_photo_url=booking.start_photo_url,
        end_photo_url=booking.end_photo_url,
        overage_cents=booking.overage_cents,
    )


def create_router(
    settings: BookingSettings,
    get_session: Callable,
    get_guard: Callable,
    listing_client: ListingClient,
) -> APIRouter:
    router = APIRouter()
    get_access_claims = claims_dependency(
        secret=settings.jwt_secret, issuer=settings.jwt_issuer, token_type="access"
    )

    @router.post("/bookings", status_code=201)
    async def create(
        payload: CreateBookingRequest,
        session: AsyncSession = Depends(get_session),
        guard: IdempotencyGuard = Depends(get_guard),
        claims: dict = Depends(get_access_claims),
        authorization: str = Header(),
    ) -> Response:
        require_role(claims, "renter")
        repo = BookingRepository(session)

        async def build() -> str:
            try:
                booking = await request_booking(
                    repo,
                    session,
                    listing_client,
                    renter_id=uuid.UUID(claims["sub"]),
                    vehicle_id=payload.vehicle_id,
                    start_date=payload.start_date,
                    end_date=payload.end_date,
                    bearer_token=authorization.split(" ", 1)[1],
                )
            except VehicleNotBookableError as exc:
                raise HTTPException(status_code=404, detail="vehicle not bookable") from exc
            except OverlappingBookingError as exc:
                await session.rollback()
                raise HTTPException(
                    status_code=409, detail="vehicle is already booked for these dates"
                ) from exc
            return _booking_response(booking).model_dump_json()

        return await respond_idempotently(guard, 201, build)

    @router.get("/bookings", response_model=ListBookingsResponse)
    async def list_bookings(
        limit: int = 100,
        offset: int = 0,
        session: AsyncSession = Depends(get_session),
        claims: dict = Depends(get_access_claims),
    ) -> ListBookingsResponse:
        # Admin/operational only — this backs the admin service; a renter or
        # host sees their own bookings via GET /bookings/{id}.
        require_role(claims, "admin")
        repo = BookingRepository(session)
        bookings = await list_all_bookings(repo, limit=limit + 1, offset=offset)
        next_offset = offset + limit if len(bookings) > limit else None
        return ListBookingsResponse(
            items=[_booking_response(b) for b in bookings[:limit]], next_offset=next_offset
        )

    @router.get("/bookings/{booking_id}", response_model=BookingResponse)
    async def get_booking(
        booking_id: uuid.UUID,
        session: AsyncSession = Depends(get_session),
        claims: dict = Depends(get_access_claims),
    ) -> BookingResponse:
        repo = BookingRepository(session)
        try:
            booking = await get_booking_for_viewer(
                repo,
                booking_id=booking_id,
                viewer_id=uuid.UUID(claims["sub"]),
                viewer_role=claims.get("role", ""),
            )
        except BookingNotFoundError as exc:
            raise HTTPException(status_code=404, detail="booking not found") from exc
        except NotBookingPartyError as exc:
            raise HTTPException(status_code=403, detail="not your booking") from exc
        return _booking_response(booking)

    @router.post("/bookings/{booking_id}/accept", status_code=200)
    async def accept(
        booking_id: uuid.UUID,
        session: AsyncSession = Depends(get_session),
        guard: IdempotencyGuard = Depends(get_guard),
        claims: dict = Depends(get_access_claims),
    ) -> Response:
        require_role(claims, "host")
        repo = BookingRepository(session)

        async def build() -> str:
            try:
                booking = await accept_booking_request(
                    repo, session, booking_id=booking_id, host_id=uuid.UUID(claims["sub"])
                )
            except BookingNotFoundError as exc:
                raise HTTPException(status_code=404, detail="booking not found") from exc
            except NotBookingPartyError as exc:
                raise HTTPException(status_code=403, detail="not your booking") from exc
            except InvalidBookingTransitionError as exc:
                raise HTTPException(status_code=409, detail=str(exc)) from exc
            return _booking_response(booking).model_dump_json()

        return await respond_idempotently(guard, 200, build)

    @router.post("/bookings/{booking_id}/reject", status_code=200)
    async def reject(
        booking_id: uuid.UUID,
        session: AsyncSession = Depends(get_session),
        guard: IdempotencyGuard = Depends(get_guard),
        claims: dict = Depends(get_access_claims),
    ) -> Response:
        require_role(claims, "host")
        repo = BookingRepository(session)

        async def build() -> str:
            try:
                booking = await reject_booking_request(
                    repo, session, booking_id=booking_id, host_id=uuid.UUID(claims["sub"])
                )
            except BookingNotFoundError as exc:
                raise HTTPException(status_code=404, detail="booking not found") from exc
            except NotBookingPartyError as exc:
                raise HTTPException(status_code=403, detail="not your booking") from exc
            except InvalidBookingTransitionError as exc:
                raise HTTPException(status_code=409, detail=str(exc)) from exc
            return _booking_response(booking).model_dump_json()

        return await respond_idempotently(guard, 200, build)

    @router.post("/bookings/{booking_id}/handover", status_code=200)
    async def handover(
        booking_id: uuid.UUID,
        payload: HandoverRequest,
        session: AsyncSession = Depends(get_session),
        guard: IdempotencyGuard = Depends(get_guard),
        claims: dict = Depends(get_access_claims),
    ) -> Response:
        require_role(claims, "host")
        repo = BookingRepository(session)

        async def build() -> str:
            try:
                booking = await record_handover(
                    repo,
                    booking_id=booking_id,
                    host_id=uuid.UUID(claims["sub"]),
                    odometer=payload.odometer,
                    fuel_percent=payload.fuel_percent,
                    photo_url=payload.photo_url,
                )
            except BookingNotFoundError as exc:
                raise HTTPException(status_code=404, detail="booking not found") from exc
            except NotBookingPartyError as exc:
                raise HTTPException(status_code=403, detail="not your booking") from exc
            except InvalidBookingTransitionError as exc:
                raise HTTPException(status_code=409, detail=str(exc)) from exc
            return _booking_response(booking).model_dump_json()

        return await respond_idempotently(guard, 200, build)

    @router.post("/bookings/{booking_id}/return", status_code=200)
    async def return_car(
        booking_id: uuid.UUID,
        payload: ReturnRequest,
        session: AsyncSession = Depends(get_session),
        guard: IdempotencyGuard = Depends(get_guard),
        claims: dict = Depends(get_access_claims),
    ) -> Response:
        require_role(claims, "host")
        repo = BookingRepository(session)

        async def build() -> str:
            try:
                booking = await record_return(
                    repo,
                    session,
                    booking_id=booking_id,
                    host_id=uuid.UUID(claims["sub"]),
                    odometer=payload.odometer,
                    fuel_percent=payload.fuel_percent,
                    photo_url=payload.photo_url,
                )
            except BookingNotFoundError as exc:
                raise HTTPException(status_code=404, detail="booking not found") from exc
            except NotBookingPartyError as exc:
                raise HTTPException(status_code=403, detail="not your booking") from exc
            except InvalidBookingTransitionError as exc:
                raise HTTPException(status_code=409, detail=str(exc)) from exc
            return _booking_response(booking).model_dump_json()

        return await respond_idempotently(guard, 200, build)

    return router
