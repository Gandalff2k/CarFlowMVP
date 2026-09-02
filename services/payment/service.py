import logging
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from services.payment.repository import PaymentRepository, write_ledger_pair
from services.payment.stripe_client import StripeClient, StripeError
from shared.outbox import write_outbox_event

logger = logging.getLogger(__name__)


async def handle_authorize_payment_requested(
    session: AsyncSession,
    repo: PaymentRepository,
    stripe_client: StripeClient,
    *,
    booking_id: uuid.UUID,
    renter_id: uuid.UUID,
    amount_cents: int,
) -> None:
    existing = await repo.get_by_booking_id(booking_id)
    if existing is not None:
        return  # inbox dedup already guards this, but a booking is 1:1 with a payment

    try:
        intent_id = stripe_client.authorize(
            amount_cents=amount_cents, idempotency_key=f"authorize:{booking_id}"
        )
    except StripeError:
        await repo.create(
            booking_id=booking_id,
            renter_id=renter_id,
            hold_amount_cents=amount_cents,
            status="authorization_failed",
        )
        await write_outbox_event(
            session,
            aggregate_type="payment",
            aggregate_id=str(booking_id),
            event_type="payment_authorization_failed",
            data={"booking_id": str(booking_id)},
        )
        return

    await repo.create(
        booking_id=booking_id,
        renter_id=renter_id,
        hold_amount_cents=amount_cents,
        status="authorized",
        stripe_payment_intent_id=intent_id,
    )
    await write_outbox_event(
        session,
        aggregate_type="payment",
        aggregate_id=str(booking_id),
        event_type="payment_authorized",
        data={"booking_id": str(booking_id)},
    )


async def handle_capture_payment_requested(
    session: AsyncSession,
    repo: PaymentRepository,
    stripe_client: StripeClient,
    *,
    booking_id: uuid.UUID,
    host_id: uuid.UUID,
    hold_amount_cents: int,
    overage_cents: int,
) -> None:
    payment = await repo.get_by_booking_id(booking_id)
    if payment is None or payment.status != "authorized":
        return  # nothing was ever held (authorization failed earlier) — nothing to capture

    try:
        stripe_client.capture(
            payment_intent_id=payment.stripe_payment_intent_id,
            amount_cents=hold_amount_cents,
            idempotency_key=f"capture:{booking_id}",
        )
    except StripeError:
        payment.status = "capture_failed"
        await repo.save(payment)
        await write_outbox_event(
            session,
            aggregate_type="payment",
            aggregate_id=str(booking_id),
            event_type="payment_capture_failed",
            data={"booking_id": str(booking_id)},
        )
        return

    await write_ledger_pair(
        session,
        payment_id=payment.id,
        booking_id=booking_id,
        debit_account=f"renter:{payment.renter_id}",
        credit_account=f"host:{host_id}",
        amount_cents=hold_amount_cents,
        reason="rental",
    )

    if overage_cents > 0:
        # A hold can only be captured up to its authorized amount, so the
        # overage is a second, separate immediate charge — not an extension
        # of the original capture.
        try:
            overage_intent_id = stripe_client.authorize_and_capture(
                amount_cents=overage_cents, idempotency_key=f"overage:{booking_id}"
            )
        except StripeError:
            logger.warning("overage charge failed for booking_id=%s", booking_id)
        else:
            payment.stripe_overage_intent_id = overage_intent_id
            payment.overage_cents = overage_cents
            await repo.save(payment)
            await write_ledger_pair(
                session,
                payment_id=payment.id,
                booking_id=booking_id,
                debit_account=f"renter:{payment.renter_id}",
                credit_account=f"host:{host_id}",
                amount_cents=overage_cents,
                reason="mileage_overage",
            )

    payment.status = "captured"
    await repo.save(payment)
    await write_outbox_event(
        session,
        aggregate_type="payment",
        aggregate_id=str(booking_id),
        event_type="payment_captured",
        data={"booking_id": str(booking_id)},
    )
