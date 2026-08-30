from services.auth.config import AuthSettings
from services.auth.models import User
from services.auth.repository import DuplicateEmailError, UserRepository
from services.auth.security import create_token, hash_password, verify_password


class EmailAlreadyRegisteredError(Exception):
    pass


class InvalidCredentialsError(Exception):
    pass


async def register_user(repo: UserRepository, *, email: str, password: str, role: str) -> User:
    existing = await repo.get_by_email(email)
    if existing is not None:
        raise EmailAlreadyRegisteredError(email)
    try:
        return await repo.create(email=email, password_hash=hash_password(password), role=role)
    except DuplicateEmailError as exc:
        raise EmailAlreadyRegisteredError(email) from exc


async def authenticate_user(repo: UserRepository, *, email: str, password: str) -> User:
    user = await repo.get_by_email(email)
    if user is None or not verify_password(password, user.password_hash):
        raise InvalidCredentialsError
    return user


def issue_token_pair(user: User, settings: AuthSettings) -> tuple[str, str]:
    access = create_token(
        user_id=user.id,
        role=user.role,
        token_type="access",
        secret=settings.jwt_secret,
        issuer=settings.jwt_issuer,
        ttl_seconds=settings.access_token_ttl_seconds,
    )
    refresh = create_token(
        user_id=user.id,
        role=user.role,
        token_type="refresh",
        secret=settings.jwt_secret,
        issuer=settings.jwt_issuer,
        ttl_seconds=settings.refresh_token_ttl_seconds,
    )
    return access, refresh
