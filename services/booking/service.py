import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from services.booking import domain
from services.booking.listing_client import ListingClient, VehicleNotFoundError
from services.booking.models import Booking
from services.booking.repository import BookingRepository
from shared.outbox import write_outbox_event


class BookingNotFoundError(Exception):
    pass


class NotBookingPartyError(Exception):
    pass


class VehicleNotBookableError(Exception):
    pass


def _apply_transition(booking: Booking, transition: domain.Transition) -> None:
    if transition.events[0][0] == "booking_handover_recorded":
        payload = transition.events[0][1]
        booking.start_odometer = payload["odometer"]
        booking.start_fuel_percent = payload["fuel_percent"]
        booking.start_photo_url = payload["photo_url"]
    if transition.events[0][0] == "booking_return_recorded":
        payload = transition.events[0][1]
        booking.end_odometer = payload["odometer"]
        booking.end_fuel_percent = payload["fuel_percent"]
        booking.end_photo_url = payload["photo_url"]
        booking.overage_cents = payload["overage_cents"]


async def _emit_domain_event(session: AsyncSession, booking: Booking, event_type: str) -> None:
    """Events for anyone interested in a booking's lifecycle (notification,
    admin, future consumers) — distinct from the authorize/capture *commands*
    this module also writes to the same outbox table for payment specifically.
    Ships on the same `booking.payment.commands` topic (see PLAN.md's Phase 6
    notes for why that name is now slightly stale but not worth renaming);
    consumers pick out the event_types they care about and ignore the rest,
    same as every other consumer in this codebase already does."""
    await write_outbox_event(
        session,
        aggregate_type="booking",
        aggregate_id=str(booking.id),
        event_type=event_type,
        data={
            "booking_id": str(booking.id),
            "renter_id": str(booking.renter_id),
            "host_id": str(booking.host_id),
            "status": booking.status,
        },
    )


async def _emit_authorize_payment_requested(session: AsyncSession, booking: Booking) -> None:
    days = max((booking.end_date - booking.start_date).days, 1)
    await write_outbox_event(
        session,
        aggregate_type="booking",
        aggregate_id=str(booking.id),
        event_type="authorize_payment_requested",
        data={
            "booking_id": str(booking.id),
            "renter_id": str(booking.renter_id),
            "amount_cents": booking.daily_price_cents * days,
        },
    )


async def request_booking(
    repo: BookingRepository,
    session: AsyncSession,
    listing_client: ListingClient,
    *,
    renter_id: uuid.UUID,
    vehicle_id: uuid.UUID,
    start_date,
    end_date,
    bearer_token: str,
) -> Booking:
    try:
        vehicle = await listing_client.get_vehicle(vehicle_id, bearer_token=bearer_token)
    except VehicleNotFoundError as exc:
        raise VehicleNotBookableError(vehicle_id) from exc
    if vehicle.approval_status != "approved":
        raise VehicleNotBookableError(vehicle_id)

    booking = await repo.create_requested(
        vehicle_id=vehicle_id,
        host_id=vehicle.host_id,
        renter_id=renter_id,
        start_date=start_date,
        end_date=end_date,
        daily_price_cents=vehicle.daily_price_cents,
        daily_mileage_limit=vehicle.daily_mileage_limit,
        booking_mode=vehicle.booking_mode,
    )
    await repo.append_events(
        booking=booking, events=[("booking_requested", {})], next_status="requested"
    )
    if vehicle.booking_mode == "instant":
        await _emit_authorize_payment_requested(session, booking)
    await repo.save(booking)
    return booking


async def accept_booking_request(
    repo: BookingRepository, session: AsyncSession, *, booking_id: uuid.UUID, host_id: uuid.UUID
) -> Booking:
    booking = await repo.get_by_id(booking_id)
    if booking is None:
        raise BookingNotFoundError(booking_id)
    if booking.host_id != host_id:
        raise NotBookingPartyError(booking_id)
    transition = domain.accept_request(repo.state_of(booking))
    await repo.append_events(
        booking=booking, events=transition.events, next_status=transition.next_status
    )
    await _emit_authorize_payment_requested(session, booking)
    await repo.save(booking)
    return booking


async def reject_booking_request(
    repo: BookingRepository, session: AsyncSession, *, booking_id: uuid.UUID, host_id: uuid.UUID
) -> Booking:
    booking = await repo.get_by_id(booking_id)
    if booking is None:
        raise BookingNotFoundError(booking_id)
    if booking.host_id != host_id:
        raise NotBookingPartyError(booking_id)
    transition = domain.reject_request(repo.state_of(booking))
    await repo.append_events(
        booking=booking, events=transition.events, next_status=transition.next_status
    )
    await _emit_domain_event(session, booking, "booking_rejected")
    await repo.save(booking)
    return booking


async def list_all_bookings(repo: BookingRepository, *, limit: int, offset: int) -> list[Booking]:
    return await repo.list_all(limit=limit, offset=offset)


async def get_booking_for_viewer(
    repo: BookingRepository, *, booking_id: uuid.UUID, viewer_id: uuid.UUID, viewer_role: str
) -> Booking:
    booking = await repo.get_by_id(booking_id)
    if booking is None:
        raise BookingNotFoundError(booking_id)
    is_party = viewer_id in (booking.renter_id, booking.host_id)
    if viewer_role != "admin" and not is_party:
        raise NotBookingPartyError(booking_id)
    return booking


async def record_handover(
    repo: BookingRepository,
    *,
    booking_id: uuid.UUID,
    host_id: uuid.UUID,
    odometer: int,
    fuel_percent: int,
    photo_url: str,
) -> Booking:
    booking = await repo.get_by_id(booking_id)
    if booking is None:
        raise BookingNotFoundError(booking_id)
    if booking.host_id != host_id:
        raise NotBookingPartyError(booking_id)
    transition = domain.record_handover(
        repo.state_of(booking), odometer=odometer, fuel_percent=fuel_percent, photo_url=photo_url
    )
    _apply_transition(booking, transition)
    await repo.append_events(
        booking=booking, events=transition.events, next_status=transition.next_status
    )
    await repo.save(booking)
    return booking


async def record_return(
    repo: BookingRepository,
    session: AsyncSession,
    *,
    booking_id: uuid.UUID,
    host_id: uuid.UUID,
    odometer: int,
    fuel_percent: int,
    photo_url: str,
) -> Booking:
    booking = await repo.get_by_id(booking_id)
    if booking is None:
        raise BookingNotFoundError(booking_id)
    if booking.host_id != host_id:
        raise NotBookingPartyError(booking_id)
    transition, overage_cents = domain.record_return(
        repo.state_of(booking), odometer=odometer, fuel_percent=fuel_percent, photo_url=photo_url
    )
    _apply_transition(booking, transition)
    await repo.append_events(
        booking=booking, events=transition.events, next_status=transition.next_status
    )
    days = max((booking.end_date - booking.start_date).days, 1)
    await write_outbox_event(
        session,
        aggregate_type="booking",
        aggregate_id=str(booking.id),
        event_type="capture_payment_requested",
        data={
            "booking_id": str(booking.id),
            "host_id": str(booking.host_id),
            "hold_amount_cents": booking.daily_price_cents * days,
            "overage_cents": overage_cents,
        },
    )
    await repo.save(booking)
    return booking


async def apply_payment_authorized(
    repo: BookingRepository, session: AsyncSession, *, booking_id: uuid.UUID
) -> Booking:
    booking = await repo.get_by_id(booking_id)
    if booking is None:
        raise BookingNotFoundError(booking_id)
    transition = domain.confirm_after_payment_authorized(repo.state_of(booking))
    await repo.append_events(
        booking=booking, events=transition.events, next_status=transition.next_status
    )
    await _emit_domain_event(session, booking, "booking_confirmed")
    await repo.save(booking)
    return booking


async def apply_payment_authorization_failed(
    repo: BookingRepository, session: AsyncSession, *, booking_id: uuid.UUID
) -> Booking:
    booking = await repo.get_by_id(booking_id)
    if booking is None:
        raise BookingNotFoundError(booking_id)
    transition = domain.cancel_after_payment_authorization_failed(repo.state_of(booking))
    await repo.append_events(
        booking=booking, events=transition.events, next_status=transition.next_status
    )
    await _emit_domain_event(session, booking, "booking_cancelled")
    await repo.save(booking)
    return booking


async def apply_payment_captured(
    repo: BookingRepository, session: AsyncSession, *, booking_id: uuid.UUID
) -> Booking:
    booking = await repo.get_by_id(booking_id)
    if booking is None:
        raise BookingNotFoundError(booking_id)
    transition = domain.complete_after_payment_captured(repo.state_of(booking))
    await repo.append_events(
        booking=booking, events=transition.events, next_status=transition.next_status
    )
    await _emit_domain_event(session, booking, "booking_completed")
    await repo.save(booking)
    return booking


async def apply_payment_capture_failed(
    repo: BookingRepository, session: AsyncSession, *, booking_id: uuid.UUID
) -> Booking:
    booking = await repo.get_by_id(booking_id)
    if booking is None:
        raise BookingNotFoundError(booking_id)
    transition = domain.note_payment_capture_failed(repo.state_of(booking))
    await repo.append_events(
        booking=booking, events=transition.events, next_status=transition.next_status
    )
    await _emit_domain_event(session, booking, "booking_payment_capture_failed")
    await repo.save(booking)
    return booking
