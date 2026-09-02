from shared.settings import ServiceSettings


class NotificationSettings(ServiceSettings):
    service_name: str = "notification"
    database_url: str = "postgresql+asyncpg://carflow:carflow@localhost:5432/notification"
    kafka_bootstrap_servers: str = "localhost:9092"
    # Booking ships both its payment commands and its domain events onto this
    # one topic (see PLAN.md's Phase 6 notes) — notification only has
    # handlers for the booking_* event types, everything else is ignored.
    booking_events_topic: str = "booking.payment.commands"
    enable_kafka_consumer: bool = True
