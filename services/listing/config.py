from shared.settings import ServiceSettings


class ListingSettings(ServiceSettings):
    service_name: str = "listing"
    database_url: str = "postgresql+asyncpg://carflow:carflow@localhost:5432/listing"
    jwt_secret: str = "dev-secret-change-me"
    jwt_issuer: str = "carflow-auth"
