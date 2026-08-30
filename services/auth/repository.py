import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from services.auth.models import User


class DuplicateEmailError(Exception):
    pass


class UserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_email(self, email: str) -> User | None:
        result = await self._session.execute(select(User).where(User.email == email))
        return result.scalar_one_or_none()

    async def get_by_id(self, user_id: uuid.UUID) -> User | None:
        result = await self._session.execute(select(User).where(User.id == user_id))
        return result.scalar_one_or_none()

    async def create(self, *, email: str, name: str, password_hash: str, role: str) -> User:
        user = User(email=email, name=name, password_hash=password_hash, role=role)
        self._session.add(user)
        try:
            await self._session.flush()
        except IntegrityError as exc:

            raise DuplicateEmailError(email) from exc
        return user
