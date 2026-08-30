from shared.settings import ServiceSettings


class AuthSettings(ServiceSettings):
    service_name: str = "auth"
    database_url: str = "postgresql+asyncpg://carflow:carflow@localhost:5432/auth"
    jwt_secret: str = "dev-secret-change-me"
    jwt_issuer: str = "carflow-auth"
    access_token_ttl_seconds: int = 900
    refresh_token_ttl_seconds: int = 604_800
