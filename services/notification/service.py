import logging
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from services.notification.repository import resolve_preference

logger = logging.getLogger(__name__)


async def notify_user(
    session: AsyncSession, *, user_id: uuid.UUID, event_type: str, booking_id: str
) -> None:
    preference = await resolve_preference(session, user_id=user_id)
    if preference.email_enabled:
        logger.info(
            "would_send channel=email user_id=%s event_type=%s booking_id=%s",
            user_id,
            event_type,
            booking_id,
        )
    if preference.sms_enabled:
        logger.info(
            "would_send channel=sms user_id=%s event_type=%s booking_id=%s",
            user_id,
            event_type,
            booking_id,
        )


async def notify_booking_event(session: AsyncSession, *, event_type: str, data: dict) -> None:
    booking_id = data["booking_id"]
    # Both parties care about a booking's lifecycle: the renter booked it,
    # the host's car is affected by it.
    await notify_user(
        session, user_id=uuid.UUID(data["renter_id"]), event_type=event_type, booking_id=booking_id
    )
    await notify_user(
        session, user_id=uuid.UUID(data["host_id"]), event_type=event_type, booking_id=booking_id
    )
