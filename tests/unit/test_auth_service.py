import uuid
from types import SimpleNamespace

import pytest

from services.auth.security import verify_password
from services.auth.service import (
    EmailAlreadyRegisteredError,
    InvalidCredentialsError,
    authenticate_user,
    register_user,
)


class FakeUserRepository:
    def __init__(self) -> None:
        self._by_email: dict[str, SimpleNamespace] = {}

    async def get_by_email(self, email: str) -> SimpleNamespace | None:
        return self._by_email.get(email)

    async def get_by_id(self, user_id: uuid.UUID) -> SimpleNamespace | None:
        return next((u for u in self._by_email.values() if u.id == user_id), None)

    async def create(self, *, email: str, password_hash: str, role: str) -> SimpleNamespace:
        user = SimpleNamespace(id=uuid.uuid4(), email=email, password_hash=password_hash, role=role)
        self._by_email[email] = user
        return user


async def test_register_user_creates_account_with_hashed_password() -> None:
    repo = FakeUserRepository()

    user = await register_user(repo, email="a@example.com", password="s3cret!!", role="renter")

    assert user.email == "a@example.com"
    assert user.password_hash != "s3cret!!"
    assert verify_password("s3cret!!", user.password_hash)


async def test_register_user_rejects_duplicate_email() -> None:
    repo = FakeUserRepository()
    await register_user(repo, email="a@example.com", password="s3cret!!", role="renter")

    with pytest.raises(EmailAlreadyRegisteredError):
        await register_user(repo, email="a@example.com", password="different", role="host")


async def test_authenticate_user_succeeds_with_correct_password() -> None:
    repo = FakeUserRepository()
    await register_user(repo, email="a@example.com", password="s3cret!!", role="renter")

    user = await authenticate_user(repo, email="a@example.com", password="s3cret!!")

    assert user.email == "a@example.com"


async def test_authenticate_user_rejects_wrong_password() -> None:
    repo = FakeUserRepository()
    await register_user(repo, email="a@example.com", password="s3cret!!", role="renter")

    with pytest.raises(InvalidCredentialsError):
        await authenticate_user(repo, email="a@example.com", password="wrong")


async def test_authenticate_user_rejects_unknown_email() -> None:
    repo = FakeUserRepository()

    with pytest.raises(InvalidCredentialsError):
        await authenticate_user(repo, email="nobody@example.com", password="whatever")
