from shared.settings import ServiceSettings


class SearchSettings(ServiceSettings):
    service_name: str = "search"
    elasticsearch_url: str = "http://localhost:9200"
    index_name: str = "vehicles"
    redis_url: str = "redis://localhost:6379/0"
    kafka_bootstrap_servers: str = "localhost:9092"
    listing_events_topic: str = "listing.vehicle.events"
    listing_base_url: str = "http://listing:8000"
    jwt_secret: str = "dev-secret-change-me"
    jwt_issuer: str = "carflow-auth"
    enable_kafka_consumer: bool = True
    query_cache_ttl_seconds: int = 30
