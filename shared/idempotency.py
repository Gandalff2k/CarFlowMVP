import hashlib
from dataclasses import dataclass
from typing import Any

from fastapi import Depends, HTTPException, Request
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

# Each service that uses this module owns its own `idempotency_keys` table,
# created by that service's migrations:
#
#   CREATE TABLE idempotency_keys (
#       key TEXT PRIMARY KEY,
#       request_hash TEXT NOT NULL,
#       response_body TEXT NOT NULL,
#       status_code INTEGER NOT NULL,
#       created_at TIMESTAMPTZ NOT NULL DEFAULT now()
#   );


def hash_request_body(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


@dataclass
class IdempotencyGuard:
    session: AsyncSession
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
                "INSERT INTO idempotency_keys (key, request_hash, response_body, status_code) "
                "VALUES (:key, :request_hash, :response_body, :status_code) "
                "ON CONFLICT (key) DO NOTHING"
            ),
            {
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
                        "FROM idempotency_keys WHERE key = :key"
                    ),
                    {"key": self.key},
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
) -> Any:
    async def _guard(
        request: Request, session: AsyncSession = Depends(get_session)
    ) -> IdempotencyGuard:
        key = request.headers.get("Idempotency-Key")
        if not key:
            raise HTTPException(status_code=400, detail="Idempotency-Key header is required")

        body = await request.body()
        request_hash = hash_request_body(body)

        row = (
            await session.execute(
                text(
                    "SELECT request_hash, response_body, status_code "
                    "FROM idempotency_keys WHERE key = :key"
                ),
                {"key": key},
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
                key=key,
                request_hash=request_hash,
                replay_body=row.response_body,
                replay_status=row.status_code,
            )

        return IdempotencyGuard(session=session, key=key, request_hash=request_hash)

    return _guard
