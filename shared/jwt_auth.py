from collections.abc import Callable

import jwt
from fastapi import Header, HTTPException




def decode_token(token: str, *, secret: str, issuer: str) -> dict:
    return jwt.decode(token, secret, algorithms=["HS256"], issuer=issuer)


def bearer_token(authorization: str | None) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="missing bearer token")
    return authorization.split(" ", 1)[1]


def claims_dependency(*, secret: str, issuer: str, token_type: str = "access") -> Callable:
    async def _dependency(authorization: str | None = Header(default=None)) -> dict:
        token = bearer_token(authorization)
        try:
            claims = decode_token(token, secret=secret, issuer=issuer)
        except jwt.InvalidTokenError as exc:
            raise HTTPException(status_code=401, detail="invalid or expired token") from exc
        if claims.get("type") != token_type:
            raise HTTPException(status_code=401, detail=f"expected a {token_type} token")
        return claims

    return _dependency


def require_role(claims: dict, *allowed_roles: str) -> None:
    if claims.get("role") not in allowed_roles:
        raise HTTPException(status_code=403, detail="insufficient role")
