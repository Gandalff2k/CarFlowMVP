import uuid
from collections.abc import AsyncIterator

import pytest
from fastapi import HTTPException

from shared.db import create_engine, create_session_factory
from shared.idempotency import IdempotencyGuard, hash_request_body


@pytest.fixture()
async def session_factory(database_url: str) -> AsyncIterator:
    engine = create_engine(database_url)
    factory = create_session_factory(engine)
    yield factory
    await engine.dispose()


async def test_store_recovers_when_another_request_wins_the_insert_race(session_factory) -> None:
    # Simulates two requests that both pass the pre-check SELECT (neither sees
    # a row yet) and then race on INSERT. Before the ON CONFLICT DO NOTHING
    # fix, the loser's store() raised an unhandled unique-violation IntegrityError.
    key = str(uuid.uuid4())
    request_hash = hash_request_body(b'{"a":1}')

    async with session_factory() as winner_session:
        winner = IdempotencyGuard(session=winner_session, key=key, request_hash=request_hash)
        await winner.store('{"winner": true}', 201)

    async with session_factory() as loser_session:
        loser = IdempotencyGuard(session=loser_session, key=key, request_hash=request_hash)
        await loser.store('{"winner": false}', 201)

        assert loser.is_replay
        assert loser.replay_body == '{"winner": true}'
        assert loser.replay_status == 201


async def test_store_rejects_conflicting_hash_lost_in_the_race(session_factory) -> None:
    key = str(uuid.uuid4())

    async with session_factory() as winner_session:
        winner = IdempotencyGuard(
            session=winner_session, key=key, request_hash=hash_request_body(b'{"a":1}')
        )
        await winner.store('{"winner": true}', 201)

    async with session_factory() as loser_session:
        loser = IdempotencyGuard(
            session=loser_session, key=key, request_hash=hash_request_body(b'{"a":2}')
        )
        with pytest.raises(HTTPException) as exc_info:
            await loser.store('{"winner": false}', 201)

    assert exc_info.value.status_code == 409
