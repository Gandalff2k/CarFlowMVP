from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from services.notification.service import notify_booking_event

BOOKING_EVENT_TYPES = (
    "booking_confirmed",
    "booking_cancelled",
    "booking_completed",
    "booking_rejected",
    "booking_payment_capture_failed",
)


def _make_handler(event_type: str):
    async def handle(session: AsyncSession, data: dict[str, Any]) -> None:
        await notify_booking_event(session, event_type=event_type, data=data)

    return handle


BOOKING_EVENT_HANDLERS = {
    event_type: _make_handler(event_type) for event_type in BOOKING_EVENT_TYPES
}
