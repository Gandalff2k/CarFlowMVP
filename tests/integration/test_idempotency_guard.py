import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy import text

from shared.db import create_engine, create_session_factory
from shared.idempotency import IdempotencyGuard, hash_request_body, purge_expired_idempotency_keys


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
        winner = IdempotencyGuard(
            session=winner_session, consumer_id="", key=key, request_hash=request_hash
        )
        await winner.store('{"winner": true}', 201)

    async with session_factory() as loser_session:
        loser = IdempotencyGuard(
            session=loser_session, consumer_id="", key=key, request_hash=request_hash
        )
        await loser.store('{"winner": false}', 201)

        assert loser.is_replay
        assert loser.replay_body == '{"winner": true}'
        assert loser.replay_status == 201


async def test_store_rejects_conflicting_hash_lost_in_the_race(session_factory) -> None:
    key = str(uuid.uuid4())

    async with session_factory() as winner_session:
        winner = IdempotencyGuard(
            session=winner_session,
            consumer_id="",
            key=key,
            request_hash=hash_request_body(b'{"a":1}'),
        )
        await winner.store('{"winner": true}', 201)

    async with session_factory() as loser_session:
        loser = IdempotencyGuard(
            session=loser_session,
            consumer_id="",
            key=key,
            request_hash=hash_request_body(b'{"a":2}'),
        )
        with pytest.raises(HTTPException) as exc_info:
            await loser.store('{"winner": false}', 201)

    assert exc_info.value.status_code == 409


async def test_different_consumers_can_reuse_the_same_key(session_factory) -> None:
    key = str(uuid.uuid4())
    request_hash = hash_request_body(b'{"a":1}')

    async with session_factory() as session_a:
        guard_a = IdempotencyGuard(
            session=session_a, consumer_id="user-a", key=key, request_hash=request_hash
        )
        await guard_a.store('{"owner": "a"}', 201)
        assert not guard_a.is_replay

    async with session_factory() as session_b:
        guard_b = IdempotencyGuard(
            session=session_b, consumer_id="user-b", key=key, request_hash=request_hash
        )
        await guard_b.store('{"owner": "b"}', 201)

        # Same client-chosen key, different consumer: no collision, no replay.
        assert not guard_b.is_replay


async def test_purge_expired_idempotency_keys_removes_only_old_rows(session_factory) -> None:
    old_key, fresh_key = str(uuid.uuid4()), str(uuid.uuid4())

    async with session_factory() as session:
        await session.execute(
            text(
                "INSERT INTO idempotency_keys "
                "(consumer_id, key, request_hash, response_body, status_code, created_at) "
                "VALUES ('', :key, 'h', 'b', 200, :created_at)"
            ),
            {"key": old_key, "created_at": datetime.now(UTC) - timedelta(days=2)},
        )
        await session.execute(
            text(
                "INSERT INTO idempotency_keys "
                "(consumer_id, key, request_hash, response_body, status_code) "
                "VALUES ('', :key, 'h', 'b', 200)"
            ),
            {"key": fresh_key},
        )
        await session.commit()

        deleted = await purge_expired_idempotency_keys(session, older_than=timedelta(hours=24))
        assert deleted == 1

        remaining = (
            (
                await session.execute(
                    text("SELECT key FROM idempotency_keys WHERE key IN (:old, :fresh)"),
                    {"old": old_key, "fresh": fresh_key},
                )
            )
            .scalars()
            .all()
        )
        assert remaining == [fresh_key]
