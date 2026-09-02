import dataclasses
import datetime as dt
import uuid

# Fixed MVP-thin overage rate: real per-vehicle pricing tiers are out of scope.
OVERAGE_RATE_CENTS_PER_MILE = 50


class InvalidBookingTransitionError(Exception):
    pass


@dataclasses.dataclass
class BookingState:
    id: uuid.UUID
    vehicle_id: uuid.UUID
    host_id: uuid.UUID
    renter_id: uuid.UUID
    start_date: dt.date
    end_date: dt.date
    daily_price_cents: int
    daily_mileage_limit: int
    booking_mode: str
    status: str
    version: int
    start_odometer: int | None = None
    end_odometer: int | None = None
    start_fuel_percent: int | None = None
    end_fuel_percent: int | None = None
    start_photo_url: str | None = None
    end_photo_url: str | None = None
    overage_cents: int = 0


@dataclasses.dataclass
class Transition:
    """One or more events to append, in order, and the status they settle on.

    A transition can carry more than one event because some reactions are
    causally atomic (e.g. "payment was authorized" always immediately yields
    "booking confirmed" — nothing else can happen in between) while the event
    log still records both as distinct facts.
    """

    events: list[tuple[str, dict]]
    next_status: str


def rental_days(state: BookingState) -> int:
    return max((state.end_date - state.start_date).days, 1)


def _require_status(state: BookingState, expected: str) -> None:
    if state.status != expected:
        raise InvalidBookingTransitionError(
            f"cannot do this from status '{state.status}' (expected '{expected}')"
        )


def accept_request(state: BookingState) -> Transition:
    if state.booking_mode != "request":
        raise InvalidBookingTransitionError("booking is not in request-to-book mode")
    _require_status(state, "requested")
    return Transition(events=[("booking_request_accepted", {})], next_status="requested")


def reject_request(state: BookingState) -> Transition:
    _require_status(state, "requested")
    return Transition(events=[("booking_rejected", {})], next_status="rejected")


def confirm_after_payment_authorized(state: BookingState) -> Transition:
    _require_status(state, "requested")
    return Transition(
        events=[("payment_authorized", {}), ("booking_confirmed", {})],
        next_status="confirmed",
    )


def cancel_after_payment_authorization_failed(state: BookingState) -> Transition:
    _require_status(state, "requested")
    return Transition(
        events=[("payment_authorization_failed", {}), ("booking_cancelled", {})],
        next_status="cancelled",
    )


def record_handover(
    state: BookingState, *, odometer: int, fuel_percent: int, photo_url: str
) -> Transition:
    _require_status(state, "confirmed")
    return Transition(
        events=[
            (
                "booking_handover_recorded",
                {"odometer": odometer, "fuel_percent": fuel_percent, "photo_url": photo_url},
            )
        ],
        next_status="active",
    )


def compute_overage_cents(
    *, start_odometer: int, end_odometer: int, daily_mileage_limit: int, days: int
) -> int:
    miles_driven = end_odometer - start_odometer
    miles_allowed = daily_mileage_limit * days
    if miles_driven <= miles_allowed:
        return 0
    return (miles_driven - miles_allowed) * OVERAGE_RATE_CENTS_PER_MILE


def record_return(
    state: BookingState, *, odometer: int, fuel_percent: int, photo_url: str
) -> tuple[Transition, int]:
    _require_status(state, "active")
    overage_cents = compute_overage_cents(
        start_odometer=state.start_odometer,
        end_odometer=odometer,
        daily_mileage_limit=state.daily_mileage_limit,
        days=rental_days(state),
    )
    transition = Transition(
        events=[
            (
                "booking_return_recorded",
                {
                    "odometer": odometer,
                    "fuel_percent": fuel_percent,
                    "photo_url": photo_url,
                    "overage_cents": overage_cents,
                },
            )
        ],
        next_status="active",
    )
    return transition, overage_cents


def complete_after_payment_captured(state: BookingState) -> Transition:
    _require_status(state, "active")
    return Transition(
        events=[("payment_captured", {}), ("booking_completed", {})],
        next_status="completed",
    )


def note_payment_capture_failed(state: BookingState) -> Transition:
    _require_status(state, "active")
    return Transition(events=[("payment_capture_failed", {})], next_status="active")
