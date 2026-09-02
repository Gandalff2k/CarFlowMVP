from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

# Each consuming service owns its own `inbox` table:
#
#   CREATE TABLE inbox (
#       event_id TEXT PRIMARY KEY,
#       processed_at TIMESTAMPTZ NOT NULL DEFAULT now()
#   );
#
# claim_event() must run in the same transaction as the side effect it
# guards: commit both together so a crash between them rolls back the claim
# too, leaving the event free to be retried; never claim, commit, then apply
# the effect in a separate transaction.


async def claim_event(session: AsyncSession, *, event_id: str) -> bool:
    result = await session.execute(
        text("INSERT INTO inbox (event_id) VALUES (:event_id) ON CONFLICT (event_id) DO NOTHING"),
        {"event_id": event_id},
    )
    return result.rowcount == 1
