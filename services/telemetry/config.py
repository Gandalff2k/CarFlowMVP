from shared.settings import ServiceSettings


class TelemetrySettings(ServiceSettings):
    service_name: str = "telemetry"
    kafka_bootstrap_servers: str = "localhost:9092"
    raw_topic: str = "telemetry.raw"
    mongo_url: str = "mongodb://localhost:27017"
    mongo_db: str = "telemetry"
    redis_url: str = "redis://localhost:6379/0"
    redis_position_ttl_seconds: int = 300
    jwt_secret: str = "dev-secret-change-me"
    jwt_issuer: str = "carflow-auth"
    batch_size: int = 100
    batch_interval_seconds: float = 2.0
    enable_consumer: bool = True
