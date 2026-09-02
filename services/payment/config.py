from shared.settings import ServiceSettings


class PaymentSettings(ServiceSettings):
    service_name: str = "payment"
    database_url: str = "postgresql+asyncpg://carflow:carflow@localhost:5432/payment"
    jwt_secret: str = "dev-secret-change-me"
    jwt_issuer: str = "carflow-auth"
    kafka_bootstrap_servers: str = "localhost:9092"
    booking_commands_topic: str = "booking.payment.commands"
    booking_events_topic: str = "payment.booking.events"
    enable_kafka_consumer: bool = True
    stripe_api_key: str = ""
    stripe_webhook_secret: str = ""
    # Stripe's documented test PaymentMethod id: authorizes/captures in test
    # mode with no real card and no checkout UI, which is all MVP scope needs.
    stripe_test_payment_method: str = "pm_card_visa"
