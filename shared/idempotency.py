import asyncio
import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import Depends, HTTPException, Request
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

# Each service that uses this module owns its own `idempotency_keys` table,
# created by that service's migrations:
#
#   CREATE TABLE idempotency_keys (
#       consumer_id TEXT NOT NULL DEFAULT '',
#       key TEXT NOT NULL,
#       request_hash TEXT NOT NULL,
#       response_body TEXT NOT NULL,
#       status_code INTEGER NOT NULL,
#       created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
#       PRIMARY KEY (consumer_id, key)
#   );
#
# consumer_id scopes the key namespace to whoever is calling (typically an
# authenticated caller id) so two different callers can never collide on the
# same client-chosen key. Endpoints with no authenticated caller yet (e.g.
# registration) use the default anonymous "" consumer.


def hash_request_body(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


@dataclass
class IdempotencyGuard:
    session: AsyncSession
    consumer_id: str
    key: str
    request_hash: str
    replay_body: str | None = None
    replay_status: int | None = None

    @property
    def is_replay(self) -> bool:
        return self.replay_body is not None

    async def store(self, response_body: str, status_code: int) -> None:
        result = await self.session.execute(
            text(
                "INSERT INTO idempotency_keys "
                "(consumer_id, key, request_hash, response_body, status_code) "
                "VALUES (:consumer_id, :key, :request_hash, :response_body, :status_code) "
                "ON CONFLICT (consumer_id, key) DO NOTHING"
            ),
            {
                "consumer_id": self.consumer_id,
                "key": self.key,
                "request_hash": self.request_hash,
                "response_body": response_body,
                "status_code": status_code,
            },
        )
        if result.rowcount == 0:
            # Lost a race: another request already claimed this key between our
            # pre-check SELECT and this INSERT. Recover by returning whatever
            # that request actually persisted, instead of crashing on the
            # primary-key violation.
            row = (
                await self.session.execute(
                    text(
                        "SELECT request_hash, response_body, status_code "
                        "FROM idempotency_keys WHERE consumer_id = :consumer_id AND key = :key"
                    ),
                    {"consumer_id": self.consumer_id, "key": self.key},
                )
            ).one()
            if row.request_hash != self.request_hash:
                raise HTTPException(
                    status_code=409,
                    detail="Idempotency-Key was already used with a different request",
                )
            self.replay_body = row.response_body
            self.replay_status = row.status_code
        await self.session.commit()


def idempotency_guard_dependency(
    get_session: Any,
    get_consumer_id: Callable[[Request], str] | None = None,
) -> Any:
    resolve_consumer_id = get_consumer_id or (lambda request: "")

    async def _guard(
        request: Request, session: AsyncSession = Depends(get_session)
    ) -> IdempotencyGuard:
        key = request.headers.get("Idempotency-Key")
        if not key:
            raise HTTPException(status_code=400, detail="Idempotency-Key header is required")

        consumer_id = resolve_consumer_id(request)
        body = await request.body()
        request_hash = hash_request_body(body)

        row = (
            await session.execute(
                text(
                    "SELECT request_hash, response_body, status_code "
                    "FROM idempotency_keys WHERE consumer_id = :consumer_id AND key = :key"
                ),
                {"consumer_id": consumer_id, "key": key},
            )
        ).first()

        if row is not None:
            if row.request_hash != request_hash:
                raise HTTPException(
                    status_code=409,
                    detail="Idempotency-Key was already used with a different request",
                )
            return IdempotencyGuard(
                session=session,
                consumer_id=consumer_id,
                key=key,
                request_hash=request_hash,
                replay_body=row.response_body,
                replay_status=row.status_code,
            )

        return IdempotencyGuard(
            session=session, consumer_id=consumer_id, key=key, request_hash=request_hash
        )

    return _guard


async def purge_expired_idempotency_keys(session: AsyncSession, *, older_than: timedelta) -> int:
    cutoff = datetime.now(UTC) - older_than
    result = await session.execute(
        text("DELETE FROM idempotency_keys WHERE created_at < :cutoff"),
        {"cutoff": cutoff},
    )
    await session.commit()
    return result.rowcount


async def run_idempotency_cleanup_loop(
    session_factory: Any,
    *,
    older_than: timedelta = timedelta(hours=24),
    interval: timedelta = timedelta(hours=1),
) -> None:
    while True:
        await asyncio.sleep(interval.total_seconds())
        async with session_factory() as session:
            await purge_expired_idempotency_keys(session, older_than=older_than)
