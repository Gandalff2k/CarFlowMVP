import uuid

import jwt
import pytest

from services.auth.security import create_token, decode_token, hash_password, verify_password


def test_hash_and_verify_password_roundtrip() -> None:
    password_hash = hash_password("correct horse battery staple")

    assert verify_password("correct horse battery staple", password_hash)


def test_verify_password_rejects_wrong_password() -> None:
    password_hash = hash_password("correct horse battery staple")

    assert not verify_password("wrong password", password_hash)


def test_create_and_decode_token_roundtrip() -> None:
    user_id = uuid.uuid4()

    token = create_token(
        user_id=user_id,
        role="renter",
        token_type="access",
        secret="secret",
        issuer="carflow-auth",
        ttl_seconds=60,
    )
    claims = decode_token(token, secret="secret", issuer="carflow-auth")

    assert claims["sub"] == str(user_id)
    assert claims["role"] == "renter"
    assert claims["type"] == "access"


def test_decode_token_rejects_expired_token() -> None:
    token = create_token(
        user_id=uuid.uuid4(),
        role="renter",
        token_type="access",
        secret="secret",
        issuer="carflow-auth",
        ttl_seconds=-1,
    )

    with pytest.raises(jwt.ExpiredSignatureError):
        decode_token(token, secret="secret", issuer="carflow-auth")


def test_decode_token_rejects_wrong_issuer() -> None:
    token = create_token(
        user_id=uuid.uuid4(),
        role="renter",
        token_type="access",
        secret="secret",
        issuer="carflow-auth",
        ttl_seconds=60,
    )

    with pytest.raises(jwt.InvalidIssuerError):
        decode_token(token, secret="secret", issuer="someone-else")


def test_decode_token_rejects_tampered_signature() -> None:
    token = create_token(
        user_id=uuid.uuid4(),
        role="renter",
        token_type="access",
        secret="secret",
        issuer="carflow-auth",
        ttl_seconds=60,
    )

    with pytest.raises(jwt.InvalidSignatureError):
        decode_token(token, secret="a-different-secret", issuer="carflow-auth")
