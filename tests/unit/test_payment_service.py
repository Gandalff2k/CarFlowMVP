import uuid
from types import SimpleNamespace

from services.payment.service import (
    handle_authorize_payment_requested,
    handle_capture_payment_requested,
)
from services.payment.stripe_client import StripeError


class FakePaymentRepository:
    def __init__(self) -> None:
        self._by_booking_id: dict[uuid.UUID, SimpleNamespace] = {}

    async def get_by_booking_id(self, booking_id):
        return self._by_booking_id.get(booking_id)

    async def create(
        self, *, booking_id, renter_id, hold_amount_cents, status, stripe_payment_intent_id=None
    ):
        payment = SimpleNamespace(
            id=uuid.uuid4(),
            booking_id=booking_id,
            renter_id=renter_id,
            hold_amount_cents=hold_amount_cents,
            overage_cents=0,
            status=status,
            stripe_payment_intent_id=stripe_payment_intent_id,
            stripe_overage_intent_id=None,
        )
        self._by_booking_id[booking_id] = payment
        return payment

    async def save(self, payment):
        self._by_booking_id[payment.booking_id] = payment


class FakeSession:
    def __init__(self) -> None:
        self.ledger_entries: list[SimpleNamespace] = []
        self.outbox_events: list[str] = []

    def add_all(self, entries) -> None:
        self.ledger_entries.extend(entries)

    async def flush(self) -> None:
        return None

    async def execute(self, statement, params=None):
        # write_outbox_event's raw INSERT: record the event_type it wrote.
        if params is not None and "type" in params:
            self.outbox_events.append(params["type"])
        return None


class FakeStripeClient:
    def __init__(self, *, fail_authorize=False, fail_capture=False, fail_overage=False) -> None:
        self.fail_authorize = fail_authorize
        self.fail_capture = fail_capture
        self.fail_overage = fail_overage
        self.captured_amounts: list[int] = []

    def authorize(self, *, amount_cents, idempotency_key):
        if self.fail_authorize:
            raise StripeError("card declined")
        return "pi_authorized_123"

    def capture(self, *, payment_intent_id, amount_cents, idempotency_key):
        if self.fail_capture:
            raise StripeError("capture failed")
        self.captured_amounts.append(amount_cents)

    def authorize_and_capture(self, *, amount_cents, idempotency_key):
        if self.fail_overage:
            raise StripeError("overage charge declined")
        self.captured_amounts.append(amount_cents)
        return "pi_overage_123"


def _ledger_balance(session: FakeSession) -> int:
    return sum(
        e.amount_cents if e.direction == "credit" else -e.amount_cents
        for e in session.ledger_entries
    )


async def test_authorize_success_records_an_authorized_payment() -> None:
    repo = FakePaymentRepository()
    session = FakeSession()
    booking_id = uuid.uuid4()

    await handle_authorize_payment_requested(
        session,
        repo,
        FakeStripeClient(),
        booking_id=booking_id,
        renter_id=uuid.uuid4(),
        amount_cents=15000,
    )

    payment = await repo.get_by_booking_id(booking_id)
    assert payment.status == "authorized"
    assert "payment_authorized" in session.outbox_events


async def test_authorize_failure_records_an_authorization_failed_payment() -> None:
    repo = FakePaymentRepository()
    session = FakeSession()
    booking_id = uuid.uuid4()

    await handle_authorize_payment_requested(
        session,
        repo,
        FakeStripeClient(fail_authorize=True),
        booking_id=booking_id,
        renter_id=uuid.uuid4(),
        amount_cents=15000,
    )

    payment = await repo.get_by_booking_id(booking_id)
    assert payment.status == "authorization_failed"
    assert "payment_authorization_failed" in session.outbox_events


async def test_authorize_is_idempotent_under_duplicate_delivery() -> None:
    repo = FakePaymentRepository()
    session = FakeSession()
    stripe_client = FakeStripeClient()
    booking_id = uuid.uuid4()
    kwargs = dict(booking_id=booking_id, renter_id=uuid.uuid4(), amount_cents=15000)

    await handle_authorize_payment_requested(session, repo, stripe_client, **kwargs)
    await handle_authorize_payment_requested(session, repo, stripe_client, **kwargs)

    assert session.outbox_events.count("payment_authorized") == 1


async def test_capture_with_no_overage_balances_the_ledger() -> None:
    repo = FakePaymentRepository()
    session = FakeSession()
    booking_id = uuid.uuid4()
    await handle_authorize_payment_requested(
        session,
        repo,
        FakeStripeClient(),
        booking_id=booking_id,
        renter_id=uuid.uuid4(),
        amount_cents=15000,
    )

    await handle_capture_payment_requested(
        session,
        repo,
        FakeStripeClient(),
        booking_id=booking_id,
        host_id=uuid.uuid4(),
        hold_amount_cents=15000,
        overage_cents=0,
    )

    payment = await repo.get_by_booking_id(booking_id)
    assert payment.status == "captured"
    assert _ledger_balance(session) == 0
    assert len(session.ledger_entries) == 2


async def test_capture_with_overage_charges_it_separately_and_still_balances() -> None:
    repo = FakePaymentRepository()
    session = FakeSession()
    booking_id = uuid.uuid4()
    await handle_authorize_payment_requested(
        session,
        repo,
        FakeStripeClient(),
        booking_id=booking_id,
        renter_id=uuid.uuid4(),
        amount_cents=15000,
    )
    stripe_client = FakeStripeClient()

    await handle_capture_payment_requested(
        session,
        repo,
        stripe_client,
        booking_id=booking_id,
        host_id=uuid.uuid4(),
        hold_amount_cents=15000,
        overage_cents=5000,
    )

    assert stripe_client.captured_amounts == [15000, 5000]
    assert _ledger_balance(session) == 0
    assert len(session.ledger_entries) == 4
    assert {e.reason for e in session.ledger_entries} == {"rental", "mileage_overage"}


async def test_capture_failure_marks_the_payment_capture_failed_and_writes_no_ledger() -> None:
    repo = FakePaymentRepository()
    session = FakeSession()
    booking_id = uuid.uuid4()
    await handle_authorize_payment_requested(
        session,
        repo,
        FakeStripeClient(),
        booking_id=booking_id,
        renter_id=uuid.uuid4(),
        amount_cents=15000,
    )

    await handle_capture_payment_requested(
        session,
        repo,
        FakeStripeClient(fail_capture=True),
        booking_id=booking_id,
        host_id=uuid.uuid4(),
        hold_amount_cents=15000,
        overage_cents=0,
    )

    payment = await repo.get_by_booking_id(booking_id)
    assert payment.status == "capture_failed"
    assert session.ledger_entries == []
    assert "payment_capture_failed" in session.outbox_events


async def test_capture_is_a_no_op_when_authorization_never_succeeded() -> None:
    repo = FakePaymentRepository()
    session = FakeSession()
    booking_id = uuid.uuid4()
    await handle_authorize_payment_requested(
        session,
        repo,
        FakeStripeClient(fail_authorize=True),
        booking_id=booking_id,
        renter_id=uuid.uuid4(),
        amount_cents=15000,
    )

    await handle_capture_payment_requested(
        session,
        repo,
        FakeStripeClient(),
        booking_id=booking_id,
        host_id=uuid.uuid4(),
        hold_amount_cents=15000,
        overage_cents=0,
    )

    payment = await repo.get_by_booking_id(booking_id)
    assert payment.status == "authorization_failed"
    assert session.ledger_entries == []
