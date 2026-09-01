import uuid

from services.auth.security import create_token, hash_password, verify_password
from shared.jwt_auth import decode_token


def test_hash_and_verify_password_roundtrip() -> None:
    password_hash = hash_password("correct horse battery staple")

    assert verify_password("correct horse battery staple", password_hash)


def test_verify_password_rejects_wrong_password() -> None:
    password_hash = hash_password("correct horse battery staple")

    assert not verify_password("wrong password", password_hash)


def test_create_token_produces_claims_decodable_by_shared_jwt_auth() -> None:
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
