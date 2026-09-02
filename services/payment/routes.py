import logging
import uuid
from collections.abc import Callable

import stripe
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from services.payment.config import PaymentSettings
from services.payment.models import Payment
from services.payment.repository import PaymentRepository
from services.payment.schemas import PaymentResponse
from shared.inbox import claim_event
from shared.jwt_auth import claims_dependency, require_role

logger = logging.getLogger(__name__)


def _payment_response(payment: Payment) -> PaymentResponse:
    return PaymentResponse(
        booking_id=str(payment.booking_id),
        renter_id=str(payment.renter_id),
        status=payment.status,
        hold_amount_cents=payment.hold_amount_cents,
        overage_cents=payment.overage_cents,
        stripe_payment_intent_id=payment.stripe_payment_intent_id,
    )


def create_router(settings: PaymentSettings, get_session: Callable) -> APIRouter:
    router = APIRouter()
    get_access_claims = claims_dependency(
        secret=settings.jwt_secret, issuer=settings.jwt_issuer, token_type="access"
    )

    @router.get("/payments/{booking_id}", response_model=PaymentResponse)
    async def get_payment(
        booking_id: uuid.UUID,
        session: AsyncSession = Depends(get_session),
        claims: dict = Depends(get_access_claims),
    ) -> PaymentResponse:
        require_role(claims, "admin")
        payment = await PaymentRepository(session).get_by_booking_id(booking_id)
        if payment is None:
            raise HTTPException(status_code=404, detail="payment not found")
        return _payment_response(payment)

    @router.post("/payments/webhooks/stripe", status_code=200, include_in_schema=False)
    async def stripe_webhook(
        request: Request,
        session: AsyncSession = Depends(get_session),
        stripe_signature: str = Header(alias="Stripe-Signature"),
    ) -> dict[str, str]:
        # Real Stripe async events (e.g. a delayed decline) land here. The
        # saga itself is driven by the synchronous authorize()/capture()
        # call result (services/payment/service.py); this endpoint exists
        # for the general "verify HMAC, dedup" reliability requirement and
        # as a hook for future async event types — not on the MVP happy path.
        payload = await request.body()
        try:
            event = stripe.Webhook.construct_event(
                payload, stripe_signature, settings.stripe_webhook_secret
            )
        except (ValueError, stripe.SignatureVerificationError) as exc:
            raise HTTPException(status_code=400, detail="invalid webhook signature") from exc

        claimed = await claim_event(session, event_id=event["id"])
        if claimed:
            logger.info("stripe webhook event_type=%s event_id=%s", event["type"], event["id"])
        await session.commit()
        return {"status": "ok"}

    return router
