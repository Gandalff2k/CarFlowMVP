import dataclasses
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from services.notification.models import NotificationPreference

DEFAULT_PREFERENCE_EMAIL_ENABLED = True
DEFAULT_PREFERENCE_SMS_ENABLED = True


@dataclasses.dataclass
class ResolvedPreference:
    email_enabled: bool
    sms_enabled: bool


async def resolve_preference(session: AsyncSession, *, user_id: uuid.UUID) -> ResolvedPreference:
    """A user with no row yet gets the default (opted in to both channels) —
    "resolve" means look it up and fall back, not require it to exist."""
    result = await session.execute(
        select(NotificationPreference).where(NotificationPreference.user_id == user_id)
    )
    row = result.scalar_one_or_none()
    if row is None:
        return ResolvedPreference(
            email_enabled=DEFAULT_PREFERENCE_EMAIL_ENABLED,
            sms_enabled=DEFAULT_PREFERENCE_SMS_ENABLED,
        )
    return ResolvedPreference(email_enabled=row.email_enabled, sms_enabled=row.sms_enabled)
