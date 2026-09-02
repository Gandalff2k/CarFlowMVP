from typing import Protocol

import stripe


class StripeError(Exception):
    pass


class StripeClient(Protocol):
    def authorize(self, *, amount_cents: int, idempotency_key: str) -> str:
        """Hold funds; returns a payment intent id."""

    def capture(self, *, payment_intent_id: str, amount_cents: int, idempotency_key: str) -> None:
        """Capture a previously authorized hold."""

    def authorize_and_capture(self, *, amount_cents: int, idempotency_key: str) -> str:
        """Create a fresh, immediately-captured charge (used for overage,
        which has no prior hold to draw from). Returns a payment intent id."""


class StripeTestModeClient:
    """Thin wrapper over Stripe's test-mode API. Uses Stripe's documented
    test PaymentMethod id, so it needs no real card and no checkout UI —
    matching PLAN.md's "Stripe test mode" scope for the hold/capture flow."""

    def __init__(self, *, api_key: str, test_payment_method: str) -> None:
        self._client = stripe.StripeClient(api_key)
        self._test_payment_method = test_payment_method

    def authorize(self, *, amount_cents: int, idempotency_key: str) -> str:
        try:
            intent = self._client.payment_intents.create(
                {
                    "amount": amount_cents,
                    "currency": "usd",
                    "payment_method": self._test_payment_method,
                    "capture_method": "manual",
                    "confirm": True,
                },
                options={"idempotency_key": idempotency_key},
            )
        except stripe.StripeError as exc:
            raise StripeError(str(exc)) from exc
        return intent.id

    def capture(self, *, payment_intent_id: str, amount_cents: int, idempotency_key: str) -> None:
        try:
            self._client.payment_intents.capture(
                payment_intent_id,
                {"amount_to_capture": amount_cents},
                options={"idempotency_key": idempotency_key},
            )
        except stripe.StripeError as exc:
            raise StripeError(str(exc)) from exc

    def authorize_and_capture(self, *, amount_cents: int, idempotency_key: str) -> str:
        try:
            intent = self._client.payment_intents.create(
                {
                    "amount": amount_cents,
                    "currency": "usd",
                    "payment_method": self._test_payment_method,
                    "capture_method": "automatic",
                    "confirm": True,
                },
                options={"idempotency_key": idempotency_key},
            )
        except stripe.StripeError as exc:
            raise StripeError(str(exc)) from exc
        return intent.id
