from prometheus_client import Counter

# Deliberately labeled by service only — never by vehicle_id (high
# cardinality is banned from Prometheus labels; per-vehicle detail belongs
# in traces/logs, not metrics).
TELEMETRY_PACKETS_INGESTED = Counter(
    "telemetry_packets_ingested_total",
    "Total telemetry packets accepted and published to Kafka",
    ("service",),
)
