import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from services.booking.repository import BookingRepository
from services.booking.service import (
    apply_payment_authorization_failed,
    apply_payment_authorized,
    apply_payment_capture_failed,
    apply_payment_captured,
)


async def _handle(session: AsyncSession, data: dict[str, Any], apply) -> None:
    repo = BookingRepository(session)
    await apply(repo, booking_id=uuid.UUID(data["booking_id"]))


async def handle_payment_authorized(session: AsyncSession, data: dict[str, Any]) -> None:
    await _handle(session, data, apply_payment_authorized)


async def handle_payment_authorization_failed(session: AsyncSession, data: dict[str, Any]) -> None:
    await _handle(session, data, apply_payment_authorization_failed)


async def handle_payment_captured(session: AsyncSession, data: dict[str, Any]) -> None:
    await _handle(session, data, apply_payment_captured)


async def handle_payment_capture_failed(session: AsyncSession, data: dict[str, Any]) -> None:
    await _handle(session, data, apply_payment_capture_failed)


PAYMENT_EVENT_HANDLERS = {
    "payment_authorized": handle_payment_authorized,
    "payment_authorization_failed": handle_payment_authorization_failed,
    "payment_captured": handle_payment_captured,
    "payment_capture_failed": handle_payment_capture_failed,
}
