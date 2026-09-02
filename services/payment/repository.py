import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from services.payment.models import LedgerEntry, Payment


class PaymentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_booking_id(self, booking_id: uuid.UUID) -> Payment | None:
        result = await self._session.execute(
            select(Payment).where(Payment.booking_id == booking_id)
        )
        return result.scalar_one_or_none()

    async def create(
        self,
        *,
        booking_id: uuid.UUID,
        renter_id: uuid.UUID,
        hold_amount_cents: int,
        status: str,
        stripe_payment_intent_id: str | None = None,
    ) -> Payment:
        payment = Payment(
            booking_id=booking_id,
            renter_id=renter_id,
            hold_amount_cents=hold_amount_cents,
            status=status,
            stripe_payment_intent_id=stripe_payment_intent_id,
        )
        self._session.add(payment)
        await self._session.flush()
        return payment

    async def save(self, payment: Payment) -> None:
        await self._session.flush()


async def write_ledger_pair(
    session: AsyncSession,
    *,
    payment_id: uuid.UUID,
    booking_id: uuid.UUID,
    debit_account: str,
    credit_account: str,
    amount_cents: int,
    reason: str,
) -> None:
    session.add_all(
        [
            LedgerEntry(
                payment_id=payment_id,
                booking_id=booking_id,
                account=debit_account,
                direction="debit",
                amount_cents=amount_cents,
                reason=reason,
            ),
            LedgerEntry(
                payment_id=payment_id,
                booking_id=booking_id,
                account=credit_account,
                direction="credit",
                amount_cents=amount_cents,
                reason=reason,
            ),
        ]
    )
    await session.flush()
