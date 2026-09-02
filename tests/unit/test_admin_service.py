import uuid

from services.admin.clients import UpstreamError
from services.admin.service import (
    activate_kill_switch,
    approve_vehicle,
    deactivate_kill_switch,
    reject_vehicle,
)
from shared import kill_switch


class FakeListingClient:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.approved: list[uuid.UUID] = []
        self.rejected: list[uuid.UUID] = []

    async def approve_vehicle(self, vehicle_id, *, bearer_token):
        if self.fail:
            raise UpstreamError(409, "cannot approve")
        self.approved.append(vehicle_id)
        return {"id": str(vehicle_id), "approval_status": "approved"}

    async def reject_vehicle(self, vehicle_id, *, bearer_token):
        self.rejected.append(vehicle_id)
        return {"id": str(vehicle_id), "approval_status": "rejected"}


class FakeActionRepository:
    def __init__(self) -> None:
        self.recorded: list[dict] = []

    async def record(self, **kwargs):
        self.recorded.append(kwargs)


class FakeRedis:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    async def set(self, key, value, **kwargs):
        self.store[key] = value

    async def delete(self, key):
        self.store.pop(key, None)

    async def exists(self, key):
        return 1 if key in self.store else 0


async def test_approve_vehicle_records_an_audit_action() -> None:
    listing_client = FakeListingClient()
    actions = FakeActionRepository()
    vehicle_id = uuid.uuid4()
    admin_id = uuid.uuid4()

    await approve_vehicle(
        listing_client, actions, admin_id=admin_id, vehicle_id=vehicle_id, bearer_token="t"
    )

    assert vehicle_id in listing_client.approved
    assert actions.recorded[0]["action_type"] == "vehicle_approved"
    assert actions.recorded[0]["target_id"] == str(vehicle_id)


async def test_approve_vehicle_does_not_record_an_action_when_upstream_fails() -> None:
    listing_client = FakeListingClient(fail=True)
    actions = FakeActionRepository()

    try:
        await approve_vehicle(
            listing_client,
            actions,
            admin_id=uuid.uuid4(),
            vehicle_id=uuid.uuid4(),
            bearer_token="t",
        )
    except UpstreamError:
        pass

    assert actions.recorded == []


async def test_reject_vehicle_records_an_audit_action() -> None:
    listing_client = FakeListingClient()
    actions = FakeActionRepository()
    vehicle_id = uuid.uuid4()

    await reject_vehicle(
        listing_client, actions, admin_id=uuid.uuid4(), vehicle_id=vehicle_id, bearer_token="t"
    )

    assert vehicle_id in listing_client.rejected
    assert actions.recorded[0]["action_type"] == "vehicle_rejected"


async def test_activate_then_deactivate_kill_switch_round_trips() -> None:
    redis = FakeRedis()
    actions = FakeActionRepository()
    vehicle_id = uuid.uuid4()

    await activate_kill_switch(redis, actions, admin_id=uuid.uuid4(), vehicle_id=vehicle_id)
    assert await kill_switch.is_active(redis, vehicle_id=str(vehicle_id)) is True
    assert actions.recorded[-1]["action_type"] == "kill_switch_activated"

    await deactivate_kill_switch(redis, actions, admin_id=uuid.uuid4(), vehicle_id=vehicle_id)
    assert await kill_switch.is_active(redis, vehicle_id=str(vehicle_id)) is False
    assert actions.recorded[-1]["action_type"] == "kill_switch_deactivated"
