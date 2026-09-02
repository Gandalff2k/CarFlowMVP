import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from services.payment.repository import PaymentRepository
from services.payment.service import (
    handle_authorize_payment_requested,
    handle_capture_payment_requested,
)
from services.payment.stripe_client import StripeClient


def build_booking_command_handlers(stripe_client: StripeClient) -> dict:
    async def authorize(session: AsyncSession, data: dict[str, Any]) -> None:
        await handle_authorize_payment_requested(
            session,
            PaymentRepository(session),
            stripe_client,
            booking_id=uuid.UUID(data["booking_id"]),
            renter_id=uuid.UUID(data["renter_id"]),
            amount_cents=data["amount_cents"],
        )

    async def capture(session: AsyncSession, data: dict[str, Any]) -> None:
        await handle_capture_payment_requested(
            session,
            PaymentRepository(session),
            stripe_client,
            booking_id=uuid.UUID(data["booking_id"]),
            host_id=uuid.UUID(data["host_id"]),
            hold_amount_cents=data["hold_amount_cents"],
            overage_cents=data["overage_cents"],
        )

    return {
        "authorize_payment_requested": authorize,
        "capture_payment_requested": capture,
    }
