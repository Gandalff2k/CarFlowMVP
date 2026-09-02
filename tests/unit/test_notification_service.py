import uuid

from services.notification.repository import ResolvedPreference
from services.notification.service import notify_booking_event, notify_user


class FakeSession:
    pass


async def test_notify_user_logs_for_each_enabled_channel(monkeypatch, caplog) -> None:
    monkeypatch.setattr(
        "services.notification.service.resolve_preference",
        lambda session, *, user_id: _resolved(email=True, sms=True),
    )
    user_id = uuid.uuid4()

    with caplog.at_level("INFO"):
        await notify_user(
            FakeSession(), user_id=user_id, event_type="booking_confirmed", booking_id="b1"
        )

    messages = [r.message for r in caplog.records]
    assert any("channel=email" in m for m in messages)
    assert any("channel=sms" in m for m in messages)


async def test_notify_user_skips_a_disabled_channel(monkeypatch, caplog) -> None:
    monkeypatch.setattr(
        "services.notification.service.resolve_preference",
        lambda session, *, user_id: _resolved(email=True, sms=False),
    )

    with caplog.at_level("INFO"):
        await notify_user(
            FakeSession(), user_id=uuid.uuid4(), event_type="booking_confirmed", booking_id="b1"
        )

    messages = [r.message for r in caplog.records]
    assert any("channel=email" in m for m in messages)
    assert not any("channel=sms" in m for m in messages)


async def test_notify_booking_event_notifies_both_renter_and_host(monkeypatch, caplog) -> None:
    monkeypatch.setattr(
        "services.notification.service.resolve_preference",
        lambda session, *, user_id: _resolved(email=True, sms=False),
    )
    renter_id = uuid.uuid4()
    host_id = uuid.uuid4()

    with caplog.at_level("INFO"):
        await notify_booking_event(
            FakeSession(),
            event_type="booking_confirmed",
            data={"booking_id": "b1", "renter_id": str(renter_id), "host_id": str(host_id)},
        )

    messages = " ".join(r.message for r in caplog.records)
    assert str(renter_id) in messages
    assert str(host_id) in messages


async def _resolved(*, email: bool, sms: bool) -> ResolvedPreference:
    return ResolvedPreference(email_enabled=email, sms_enabled=sms)
