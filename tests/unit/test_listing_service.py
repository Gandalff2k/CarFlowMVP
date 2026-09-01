import uuid
from types import SimpleNamespace

import pytest

from services.listing.service import (
    InvalidApprovalTransitionError,
    NotVehicleOwnerError,
    VehicleNotFoundError,
    approve_vehicle,
    create_vehicle,
    get_owned_vehicle,
    get_vehicle_for_viewer,
    reject_vehicle,
    update_vehicle,
)


class FakeVehicleRepository:
    def __init__(self) -> None:
        self._by_id: dict[uuid.UUID, SimpleNamespace] = {}

    async def get_by_id(self, vehicle_id: uuid.UUID) -> SimpleNamespace | None:
        return self._by_id.get(vehicle_id)

    async def create(
        self, *, host_id, make, model, year, daily_price_cents, daily_mileage_limit, booking_mode
    ):
        vehicle = SimpleNamespace(
            id=uuid.uuid4(),
            host_id=host_id,
            make=make,
            model=model,
            year=year,
            daily_price_cents=daily_price_cents,
            daily_mileage_limit=daily_mileage_limit,
            booking_mode=booking_mode,
            approval_status="pending",
        )
        self._by_id[vehicle.id] = vehicle
        return vehicle

    async def save(self, vehicle) -> None:
        self._by_id[vehicle.id] = vehicle


class FakeSession:
    """Swallows outbox writes; that side effect is covered by integration tests."""

    async def execute(self, *args, **kwargs) -> None:
        return None


async def _make_vehicle(repo: FakeVehicleRepository, *, host_id: uuid.UUID | None = None):
    return await create_vehicle(
        repo,
        host_id=host_id or uuid.uuid4(),
        make="Toyota",
        model="Corolla",
        year=2020,
        daily_price_cents=5000,
        daily_mileage_limit=200,
        booking_mode="instant",
    )


async def test_create_vehicle_starts_pending() -> None:
    repo = FakeVehicleRepository()

    vehicle = await _make_vehicle(repo)

    assert vehicle.approval_status == "pending"


async def test_get_owned_vehicle_rejects_non_owner() -> None:
    repo = FakeVehicleRepository()
    vehicle = await _make_vehicle(repo)

    with pytest.raises(NotVehicleOwnerError):
        await get_owned_vehicle(repo, vehicle_id=vehicle.id, host_id=uuid.uuid4())


async def test_get_owned_vehicle_rejects_unknown_id() -> None:
    repo = FakeVehicleRepository()

    with pytest.raises(VehicleNotFoundError):
        await get_owned_vehicle(repo, vehicle_id=uuid.uuid4(), host_id=uuid.uuid4())


async def test_approve_vehicle_moves_pending_to_approved() -> None:
    repo = FakeVehicleRepository()
    vehicle = await _make_vehicle(repo)

    approved = await approve_vehicle(repo, FakeSession(), vehicle_id=vehicle.id)

    assert approved.approval_status == "approved"


async def test_approve_vehicle_rejects_already_approved() -> None:
    repo = FakeVehicleRepository()
    vehicle = await _make_vehicle(repo)
    await approve_vehicle(repo, FakeSession(), vehicle_id=vehicle.id)

    with pytest.raises(InvalidApprovalTransitionError):
        await approve_vehicle(repo, FakeSession(), vehicle_id=vehicle.id)


async def test_approve_vehicle_rejects_unknown_id() -> None:
    repo = FakeVehicleRepository()

    with pytest.raises(VehicleNotFoundError):
        await approve_vehicle(repo, FakeSession(), vehicle_id=uuid.uuid4())


async def test_reject_vehicle_moves_pending_to_rejected() -> None:
    repo = FakeVehicleRepository()
    vehicle = await _make_vehicle(repo)

    rejected = await reject_vehicle(repo, vehicle_id=vehicle.id)

    assert rejected.approval_status == "rejected"


async def test_reject_vehicle_rejects_already_rejected() -> None:
    repo = FakeVehicleRepository()
    vehicle = await _make_vehicle(repo)
    await reject_vehicle(repo, vehicle_id=vehicle.id)

    with pytest.raises(InvalidApprovalTransitionError):
        await reject_vehicle(repo, vehicle_id=vehicle.id)


async def test_reject_vehicle_rejects_already_approved() -> None:
    repo = FakeVehicleRepository()
    vehicle = await _make_vehicle(repo)
    await approve_vehicle(repo, FakeSession(), vehicle_id=vehicle.id)

    with pytest.raises(InvalidApprovalTransitionError):
        await reject_vehicle(repo, vehicle_id=vehicle.id)


async def test_get_vehicle_for_viewer_allows_admin_regardless_of_owner() -> None:
    repo = FakeVehicleRepository()
    vehicle = await _make_vehicle(repo)

    viewed = await get_vehicle_for_viewer(
        repo, vehicle_id=vehicle.id, viewer_id=uuid.uuid4(), viewer_role="admin"
    )

    assert viewed.id == vehicle.id


async def test_get_vehicle_for_viewer_rejects_other_host() -> None:
    repo = FakeVehicleRepository()
    vehicle = await _make_vehicle(repo)

    with pytest.raises(NotVehicleOwnerError):
        await get_vehicle_for_viewer(
            repo, vehicle_id=vehicle.id, viewer_id=uuid.uuid4(), viewer_role="host"
        )


async def test_update_vehicle_only_changes_provided_fields() -> None:
    repo = FakeVehicleRepository()
    owner_id = uuid.uuid4()
    vehicle = await _make_vehicle(repo, host_id=owner_id)

    updated = await update_vehicle(
        repo, FakeSession(), vehicle_id=vehicle.id, host_id=owner_id, daily_price_cents=6000
    )

    assert updated.daily_price_cents == 6000
    assert updated.make == "Toyota"


async def test_update_vehicle_rejects_non_owner() -> None:
    repo = FakeVehicleRepository()
    vehicle = await _make_vehicle(repo)

    with pytest.raises(NotVehicleOwnerError):
        await update_vehicle(
            repo, FakeSession(), vehicle_id=vehicle.id, host_id=uuid.uuid4(), daily_price_cents=6000
        )
