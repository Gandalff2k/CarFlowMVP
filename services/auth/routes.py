import uuid
from collections.abc import Callable

import jwt as pyjwt
from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.ext.asyncio import AsyncSession

from services.auth.config import AuthSettings
from services.auth.repository import UserRepository
from services.auth.schemas import (
    LoginRequest,
    RefreshRequest,
    RegisterRequest,
    TokenResponse,
    UserResponse,
)
from services.auth.service import (
    EmailAlreadyRegisteredError,
    InvalidCredentialsError,
    authenticate_user,
    issue_token_pair,
    register_user,
)
from shared.idempotency import IdempotencyGuard, respond_idempotently
from shared.jwt_auth import claims_dependency, decode_token


def create_router(
    settings: AuthSettings,
    get_session: Callable,
    get_guard: Callable,
) -> APIRouter:
    router = APIRouter()
    get_access_claims = claims_dependency(
        secret=settings.jwt_secret, issuer=settings.jwt_issuer, token_type="access"
    )

    @router.post("/register", status_code=201)
    async def register(
        payload: RegisterRequest,
        session: AsyncSession = Depends(get_session),
        guard: IdempotencyGuard = Depends(get_guard),
    ) -> Response:
        repo = UserRepository(session)

        async def build() -> str:
            try:
                user = await register_user(
                    repo,
                    email=payload.email,
                    name=payload.name,
                    password=payload.password,
                    role=payload.role,
                )
            except EmailAlreadyRegisteredError as exc:
                await session.rollback()
                raise HTTPException(status_code=409, detail="email already registered") from exc
            return UserResponse(
                id=str(user.id), email=user.email, name=user.name, role=user.role
            ).model_dump_json()

        return await respond_idempotently(guard, 201, build)

    @router.post("/login", response_model=TokenResponse)
    async def login(
        payload: LoginRequest, session: AsyncSession = Depends(get_session)
    ) -> TokenResponse:
        repo = UserRepository(session)
        try:
            user = await authenticate_user(repo, email=payload.email, password=payload.password)
        except InvalidCredentialsError as exc:
            raise HTTPException(status_code=401, detail="invalid email or password") from exc
        access, refresh = issue_token_pair(user, settings)
        return TokenResponse(access_token=access, refresh_token=refresh)

    @router.post("/refresh", response_model=TokenResponse)
    async def refresh(
        payload: RefreshRequest, session: AsyncSession = Depends(get_session)
    ) -> TokenResponse:
        try:
            claims = decode_token(
                payload.refresh_token, secret=settings.jwt_secret, issuer=settings.jwt_issuer
            )
        except pyjwt.InvalidTokenError as exc:
            raise HTTPException(status_code=401, detail="invalid refresh token") from exc
        if claims.get("type") != "refresh":
            raise HTTPException(status_code=401, detail="not a refresh token")

        repo = UserRepository(session)
        user = await repo.get_by_id(uuid.UUID(claims["sub"]))
        if user is None:
            raise HTTPException(status_code=401, detail="user no longer exists")

        access, new_refresh = issue_token_pair(user, settings)
        return TokenResponse(access_token=access, refresh_token=new_refresh)

    @router.get("/me", response_model=UserResponse)
    async def me(
        session: AsyncSession = Depends(get_session),
        claims: dict = Depends(get_access_claims),
    ) -> UserResponse:
        repo = UserRepository(session)
        user = await repo.get_by_id(uuid.UUID(claims["sub"]))
        if user is None:
            raise HTTPException(status_code=401, detail="user no longer exists")

        return UserResponse(id=str(user.id), email=user.email, name=user.name, role=user.role)

    return router
