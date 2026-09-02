from shared.settings import ServiceSettings


class BookingSettings(ServiceSettings):
    service_name: str = "booking"
    database_url: str = "postgresql+asyncpg://carflow:carflow@localhost:5432/booking"
    jwt_secret: str = "dev-secret-change-me"
    jwt_issuer: str = "carflow-auth"
    listing_base_url: str = "http://listing:8000"
    kafka_bootstrap_servers: str = "localhost:9092"
    payment_events_topic: str = "payment.booking.events"
    payment_commands_topic: str = "booking.payment.commands"
    enable_kafka_consumer: bool = True
