import datetime as dt
import uuid
from types import SimpleNamespace

import pytest

from services.booking.domain import InvalidBookingTransitionError
from services.booking.listing_client import VehicleInfo, VehicleNotFoundError
from services.booking.repository import ConcurrentBookingUpdateError
from services.booking.service import (
    BookingNotFoundError,
    NotBookingPartyError,
    VehicleNotBookableError,
    accept_booking_request,
    apply_payment_authorization_failed,
    apply_payment_authorized,
    apply_payment_captured,
    get_booking_for_viewer,
    record_handover,
    record_return,
    reject_booking_request,
    request_booking,
)


class FakeBookingRepository:
    def __init__(self) -> None:
        self._by_id: dict[uuid.UUID, SimpleNamespace] = {}
        self.fail_next_append = False

    async def get_by_id(self, booking_id):
        return self._by_id.get(booking_id)

    async def create_requested(
        self,
        *,
        vehicle_id,
        host_id,
        renter_id,
        start_date,
        end_date,
        daily_price_cents,
        daily_mileage_limit,
        booking_mode,
    ):
        booking = SimpleNamespace(
            id=uuid.uuid4(),
            vehicle_id=vehicle_id,
            host_id=host_id,
            renter_id=renter_id,
            start_date=start_date,
            end_date=end_date,
            daily_price_cents=daily_price_cents,
            daily_mileage_limit=daily_mileage_limit,
            booking_mode=booking_mode,
            status="requested",
            version=1,
            start_odometer=None,
            end_odometer=None,
            start_fuel_percent=None,
            end_fuel_percent=None,
            start_photo_url=None,
            end_photo_url=None,
            overage_cents=0,
        )
        self._by_id[booking.id] = booking
        return booking

    async def append_events(self, *, booking, events, next_status):
        if self.fail_next_append:
            self.fail_next_append = False
            raise ConcurrentBookingUpdateError(booking.id)
        booking.version += len(events)
        booking.status = next_status

    async def save(self, booking):
        self._by_id[booking.id] = booking

    def state_of(self, booking):
        return booking


class FakeSession:
    async def execute(self, *args, **kwargs):
        return None

    async def rollback(self):
        return None


class FakeListingClient:
    def __init__(self, vehicle: VehicleInfo | None) -> None:
        self._vehicle = vehicle

    async def get_vehicle(self, vehicle_id, *, bearer_token):
        if self._vehicle is None:
            raise VehicleNotFoundError(vehicle_id)
        return self._vehicle


def _approved_vehicle(*, booking_mode="instant", host_id=None) -> VehicleInfo:
    return VehicleInfo(
        id=uuid.uuid4(),
        host_id=host_id or uuid.uuid4(),
        daily_price_cents=5000,
        daily_mileage_limit=200,
        booking_mode=booking_mode,
        approval_status="approved",
    )


async def test_request_booking_rejects_a_vehicle_that_is_not_approved() -> None:
    repo = FakeBookingRepository()
    vehicle = _approved_vehicle()
    vehicle.approval_status = "pending"
    listing_client = FakeListingClient(vehicle)

    with pytest.raises(VehicleNotBookableError):
        await request_booking(
            repo,
            FakeSession(),
            listing_client,
            renter_id=uuid.uuid4(),
            vehicle_id=vehicle.id,
            start_date=dt.date(2026, 6, 1),
            end_date=dt.date(2026, 6, 4),
            bearer_token="t",
        )


async def test_request_booking_rejects_an_unknown_vehicle() -> None:
    repo = FakeBookingRepository()
    listing_client = FakeListingClient(None)

    with pytest.raises(VehicleNotBookableError):
        await request_booking(
            repo,
            FakeSession(),
            listing_client,
            renter_id=uuid.uuid4(),
            vehicle_id=uuid.uuid4(),
            start_date=dt.date(2026, 6, 1),
            end_date=dt.date(2026, 6, 4),
            bearer_token="t",
        )


async def test_request_booking_on_an_instant_vehicle_stays_requested_pending_authorization() -> (
    None
):
    repo = FakeBookingRepository()
    listing_client = FakeListingClient(_approved_vehicle(booking_mode="instant"))

    booking = await request_booking(
        repo,
        FakeSession(),
        listing_client,
        renter_id=uuid.uuid4(),
        vehicle_id=uuid.uuid4(),
        start_date=dt.date(2026, 6, 1),
        end_date=dt.date(2026, 6, 4),
        bearer_token="t",
    )

    assert booking.status == "requested"


async def test_accept_booking_request_requires_the_vehicles_host() -> None:
    repo = FakeBookingRepository()
    listing_client = FakeListingClient(_approved_vehicle(booking_mode="request"))
    booking = await request_booking(
        repo,
        FakeSession(),
        listing_client,
        renter_id=uuid.uuid4(),
        vehicle_id=uuid.uuid4(),
        start_date=dt.date(2026, 6, 1),
        end_date=dt.date(2026, 6, 4),
        bearer_token="t",
    )

    with pytest.raises(NotBookingPartyError):
        await accept_booking_request(
            repo, FakeSession(), booking_id=booking.id, host_id=uuid.uuid4()
        )


async def test_accept_booking_request_rejects_an_instant_mode_booking() -> None:
    repo = FakeBookingRepository()
    listing_client = FakeListingClient(_approved_vehicle(booking_mode="instant"))
    booking = await request_booking(
        repo,
        FakeSession(),
        listing_client,
        renter_id=uuid.uuid4(),
        vehicle_id=uuid.uuid4(),
        start_date=dt.date(2026, 6, 1),
        end_date=dt.date(2026, 6, 4),
        bearer_token="t",
    )

    with pytest.raises(InvalidBookingTransitionError):
        await accept_booking_request(
            repo, FakeSession(), booking_id=booking.id, host_id=booking.host_id
        )


async def test_reject_booking_request_settles_on_rejected() -> None:
    repo = FakeBookingRepository()
    listing_client = FakeListingClient(_approved_vehicle(booking_mode="request"))
    booking = await request_booking(
        repo,
        FakeSession(),
        listing_client,
        renter_id=uuid.uuid4(),
        vehicle_id=uuid.uuid4(),
        start_date=dt.date(2026, 6, 1),
        end_date=dt.date(2026, 6, 4),
        bearer_token="t",
    )

    rejected = await reject_booking_request(
        repo, FakeSession(), booking_id=booking.id, host_id=booking.host_id
    )

    assert rejected.status == "rejected"


async def test_apply_payment_authorized_confirms_the_booking() -> None:
    repo = FakeBookingRepository()
    listing_client = FakeListingClient(_approved_vehicle())
    booking = await request_booking(
        repo,
        FakeSession(),
        listing_client,
        renter_id=uuid.uuid4(),
        vehicle_id=uuid.uuid4(),
        start_date=dt.date(2026, 6, 1),
        end_date=dt.date(2026, 6, 4),
        bearer_token="t",
    )

    confirmed = await apply_payment_authorized(repo, FakeSession(), booking_id=booking.id)

    assert confirmed.status == "confirmed"


async def test_apply_payment_authorization_failed_cancels_the_booking() -> None:
    repo = FakeBookingRepository()
    listing_client = FakeListingClient(_approved_vehicle())
    booking = await request_booking(
        repo,
        FakeSession(),
        listing_client,
        renter_id=uuid.uuid4(),
        vehicle_id=uuid.uuid4(),
        start_date=dt.date(2026, 6, 1),
        end_date=dt.date(2026, 6, 4),
        bearer_token="t",
    )

    cancelled = await apply_payment_authorization_failed(repo, FakeSession(), booking_id=booking.id)

    assert cancelled.status == "cancelled"


async def test_full_happy_path_reaches_completed() -> None:
    repo = FakeBookingRepository()
    listing_client = FakeListingClient(_approved_vehicle())
    booking = await request_booking(
        repo,
        FakeSession(),
        listing_client,
        renter_id=uuid.uuid4(),
        vehicle_id=uuid.uuid4(),
        start_date=dt.date(2026, 6, 1),
        end_date=dt.date(2026, 6, 4),
        bearer_token="t",
    )
    await apply_payment_authorized(repo, FakeSession(), booking_id=booking.id)
    await record_handover(
        repo,
        booking_id=booking.id,
        host_id=booking.host_id,
        odometer=1000,
        fuel_percent=100,
        photo_url="http://x/1.jpg",
    )
    returned = await record_return(
        repo,
        FakeSession(),
        booking_id=booking.id,
        host_id=booking.host_id,
        odometer=1900,
        fuel_percent=50,
        photo_url="http://x/2.jpg",
    )
    completed = await apply_payment_captured(repo, FakeSession(), booking_id=booking.id)

    assert returned.overage_cents == 300 * 50  # 900 driven - 600 allowed = 300 miles over
    assert completed.status == "completed"


async def test_get_booking_for_viewer_rejects_a_stranger() -> None:
    repo = FakeBookingRepository()
    listing_client = FakeListingClient(_approved_vehicle())
    booking = await request_booking(
        repo,
        FakeSession(),
        listing_client,
        renter_id=uuid.uuid4(),
        vehicle_id=uuid.uuid4(),
        start_date=dt.date(2026, 6, 1),
        end_date=dt.date(2026, 6, 4),
        bearer_token="t",
    )

    with pytest.raises(NotBookingPartyError):
        await get_booking_for_viewer(
            repo, booking_id=booking.id, viewer_id=uuid.uuid4(), viewer_role="renter"
        )


async def test_get_booking_for_viewer_rejects_unknown_id() -> None:
    repo = FakeBookingRepository()

    with pytest.raises(BookingNotFoundError):
        await get_booking_for_viewer(
            repo, booking_id=uuid.uuid4(), viewer_id=uuid.uuid4(), viewer_role="renter"
        )


async def test_accept_booking_request_surfaces_a_concurrent_modification_as_an_error() -> None:
    repo = FakeBookingRepository()
    listing_client = FakeListingClient(_approved_vehicle(booking_mode="request"))
    booking = await request_booking(
        repo,
        FakeSession(),
        listing_client,
        renter_id=uuid.uuid4(),
        vehicle_id=uuid.uuid4(),
        start_date=dt.date(2026, 6, 1),
        end_date=dt.date(2026, 6, 4),
        bearer_token="t",
    )
    repo.fail_next_append = True

    with pytest.raises(ConcurrentBookingUpdateError):
        await accept_booking_request(
            repo, FakeSession(), booking_id=booking.id, host_id=booking.host_id
        )
