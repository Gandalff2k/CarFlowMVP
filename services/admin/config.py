from shared.settings import ServiceSettings


class AdminSettings(ServiceSettings):
    service_name: str = "admin"
    database_url: str = "postgresql+asyncpg://carflow:carflow@localhost:5432/admin"
    jwt_secret: str = "dev-secret-change-me"
    jwt_issuer: str = "carflow-auth"
    listing_base_url: str = "http://listing:8000"
    booking_base_url: str = "http://booking:8000"
    redis_url: str = "redis://localhost:6379/0"
