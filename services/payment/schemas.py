from pydantic import BaseModel


class PaymentResponse(BaseModel):
    booking_id: str
    renter_id: str
    status: str
    hold_amount_cents: int
    overage_cents: int
    stripe_payment_intent_id: str | None
