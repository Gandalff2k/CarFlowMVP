import uuid

import jwt
import pytest
from fastapi import HTTPException

from services.auth.security import create_token
from shared.jwt_auth import bearer_token, decode_token, require_role


def _token(**overrides: object) -> str:
    defaults: dict = {
        "user_id": uuid.uuid4(),
        "role": "renter",
        "token_type": "access",
        "secret": "secret",
        "issuer": "carflow-auth",
        "ttl_seconds": 60,
    }
    defaults.update(overrides)
    return create_token(**defaults)


def test_decode_token_rejects_expired_token() -> None:
    token = _token(ttl_seconds=-1)

    with pytest.raises(jwt.ExpiredSignatureError):
        decode_token(token, secret="secret", issuer="carflow-auth")


def test_decode_token_rejects_wrong_issuer() -> None:
    token = _token()

    with pytest.raises(jwt.InvalidIssuerError):
        decode_token(token, secret="secret", issuer="someone-else")


def test_decode_token_rejects_tampered_signature() -> None:
    token = _token()

    with pytest.raises(jwt.InvalidSignatureError):
        decode_token(token, secret="a-different-secret", issuer="carflow-auth")


def test_bearer_token_extracts_token_from_header() -> None:
    assert bearer_token("Bearer abc.def.ghi") == "abc.def.ghi"


@pytest.mark.parametrize("header", [None, "", "Basic abc", "Bearer"])
def test_bearer_token_rejects_missing_or_malformed_header(header: str | None) -> None:
    with pytest.raises(HTTPException) as exc_info:
        bearer_token(header)

    assert exc_info.value.status_code == 401


def test_require_role_allows_listed_role() -> None:
    require_role({"role": "admin"}, "host", "admin")


def test_require_role_rejects_role_not_listed() -> None:
    with pytest.raises(HTTPException) as exc_info:
        require_role({"role": "renter"}, "host", "admin")

    assert exc_info.value.status_code == 403
