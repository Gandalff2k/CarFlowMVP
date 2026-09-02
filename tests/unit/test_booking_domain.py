import datetime as dt
import uuid

import pytest

from services.booking.domain import (
    BookingState,
    InvalidBookingTransitionError,
    accept_request,
    cancel_after_payment_authorization_failed,
    complete_after_payment_captured,
    compute_overage_cents,
    confirm_after_payment_authorized,
    note_payment_capture_failed,
    record_handover,
    record_return,
    reject_request,
)


def _state(**overrides) -> BookingState:
    defaults = dict(
        id=uuid.uuid4(),
        vehicle_id=uuid.uuid4(),
        host_id=uuid.uuid4(),
        renter_id=uuid.uuid4(),
        start_date=dt.date(2026, 6, 1),
        end_date=dt.date(2026, 6, 4),
        daily_price_cents=5000,
        daily_mileage_limit=200,
        booking_mode="instant",
        status="requested",
        version=1,
    )
    defaults.update(overrides)
    return BookingState(**defaults)


def test_confirm_after_payment_authorized_settles_on_confirmed() -> None:
    transition = confirm_after_payment_authorized(_state())

    assert transition.next_status == "confirmed"
    assert [event_type for event_type, _ in transition.events] == [
        "payment_authorized",
        "booking_confirmed",
    ]


def test_confirm_rejects_a_booking_that_is_not_requested() -> None:
    with pytest.raises(InvalidBookingTransitionError):
        confirm_after_payment_authorized(_state(status="confirmed"))


def test_cancel_after_payment_authorization_failed_settles_on_cancelled() -> None:
    transition = cancel_after_payment_authorization_failed(_state())

    assert transition.next_status == "cancelled"


def test_accept_request_requires_request_booking_mode() -> None:
    with pytest.raises(InvalidBookingTransitionError):
        accept_request(_state(booking_mode="instant"))


def test_accept_request_moves_a_request_mode_booking_forward() -> None:
    transition = accept_request(_state(booking_mode="request"))

    assert transition.next_status == "requested"
    assert transition.events == [("booking_request_accepted", {})]


def test_reject_request_settles_on_rejected() -> None:
    transition = reject_request(_state(booking_mode="request"))

    assert transition.next_status == "rejected"


def test_reject_request_rejects_a_booking_that_is_not_requested() -> None:
    with pytest.raises(InvalidBookingTransitionError):
        reject_request(_state(status="confirmed"))


def test_record_handover_moves_confirmed_to_active() -> None:
    transition = record_handover(
        _state(status="confirmed"), odometer=1000, fuel_percent=100, photo_url="http://x/1.jpg"
    )

    assert transition.next_status == "active"


def test_record_handover_rejects_a_booking_that_is_not_confirmed() -> None:
    with pytest.raises(InvalidBookingTransitionError):
        record_handover(_state(status="requested"), odometer=1000, fuel_percent=100, photo_url="x")


def test_compute_overage_cents_is_zero_within_the_allowance() -> None:
    assert (
        compute_overage_cents(
            start_odometer=1000, end_odometer=1500, daily_mileage_limit=200, days=3
        )
        == 0
    )


def test_compute_overage_cents_charges_only_the_excess_miles() -> None:
    # allowance = 200 * 3 = 600 miles; driven 650 -> 50 miles over.
    overage = compute_overage_cents(
        start_odometer=1000, end_odometer=1650, daily_mileage_limit=200, days=3
    )

    assert overage == 50 * 50


def test_record_return_computes_overage_from_the_two_snapshots_not_live_telemetry() -> None:
    state = _state(status="active", start_odometer=1000, daily_mileage_limit=200)

    transition, overage_cents = record_return(
        state, odometer=1700, fuel_percent=50, photo_url="http://x/2.jpg"
    )

    assert overage_cents == 100 * 50  # 700 driven - 600 allowed = 100 miles over
    assert transition.events[0][1]["overage_cents"] == overage_cents


def test_record_return_rejects_a_booking_that_is_not_active() -> None:
    with pytest.raises(InvalidBookingTransitionError):
        record_return(_state(status="confirmed"), odometer=1, fuel_percent=1, photo_url="x")


def test_complete_after_payment_captured_settles_on_completed() -> None:
    transition = complete_after_payment_captured(_state(status="active"))

    assert transition.next_status == "completed"


def test_note_payment_capture_failed_leaves_booking_active() -> None:
    transition = note_payment_capture_failed(_state(status="active"))

    assert transition.next_status == "active"
    assert transition.events == [("payment_capture_failed", {})]
