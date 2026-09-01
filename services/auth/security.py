import datetime as dt
import uuid
from typing import Literal

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

_hasher = PasswordHasher()

TokenType = Literal["access", "refresh"]


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except VerifyMismatchError:
        return False


def create_token(
    *,
    user_id: uuid.UUID,
    role: str,
    token_type: TokenType,
    secret: str,
    issuer: str,
    ttl_seconds: int,
) -> str:
    now = dt.datetime.now(dt.UTC)
    payload = {
        "sub": str(user_id),
        "role": role,
        "type": token_type,
        "iss": issuer,
        "iat": now,
        "exp": now + dt.timedelta(seconds=ttl_seconds),
    }
    return jwt.encode(payload, secret, algorithm="HS256")
