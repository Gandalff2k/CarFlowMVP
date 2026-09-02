import json

from aiokafka import AIOKafkaProducer
from pydantic import ValidationError

from services.telemetry.schemas import TelemetryPacket


class InvalidPacketError(Exception):
    pass


def parse_packet(raw: str) -> TelemetryPacket:
    try:
        return TelemetryPacket.model_validate_json(raw)
    except ValidationError as exc:
        raise InvalidPacketError(str(exc)) from exc


def apply_kill_switch(packet: TelemetryPacket, *, active: bool) -> TelemetryPacket:
    # The guard lives here, not just as an admin_actions log entry: a real
    # device cannot be trusted to actually stop on request, so the ingest
    # path itself overrides the reported speed to zero regardless of what
    # the device claims — "enforced server-side", not merely recorded.
    if not active:
        return packet
    return packet.model_copy(update={"speed_kph": 0.0})


async def publish_packet(
    producer: AIOKafkaProducer, *, topic: str, vehicle_id: str, packet: TelemetryPacket
) -> None:
    # No outbox here: there is no database write for this to be atomic
    # with — telemetry is a raw stream, not a saga side effect. Losing an
    # occasional packet on producer failure is acceptable (no analytics,
    # no smart-lock decisions ride on any single reading); throughput
    # matters more than delivery guarantees for this path (it's the
    # eventual load-test target).
    message = {
        "vehicle_id": vehicle_id,
        "lat": packet.lat,
        "lng": packet.lng,
        "speed_kph": packet.speed_kph,
        "recorded_at": packet.recorded_at.isoformat(),
    }
    await producer.send_and_wait(topic, key=vehicle_id.encode(), value=json.dumps(message).encode())
