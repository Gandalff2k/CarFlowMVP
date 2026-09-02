import json

import pytest

from services.telemetry.consumer import build_batch
from services.telemetry.ingest import (
    InvalidPacketError,
    apply_kill_switch,
    parse_packet,
    publish_packet,
)


class FakeProducer:
    def __init__(self) -> None:
        self.sent: list[tuple[str, bytes, bytes]] = []

    async def send_and_wait(self, topic: str, key: bytes, value: bytes) -> None:
        self.sent.append((topic, key, value))


def _raw_packet(**overrides) -> str:
    data = {
        "lat": 40.7128,
        "lng": -74.0060,
        "speed_kph": 55.0,
        "recorded_at": "2026-06-01T12:00:00Z",
    }
    data.update(overrides)
    return json.dumps(data)


def test_parse_packet_accepts_a_valid_payload() -> None:
    packet = parse_packet(_raw_packet())

    assert packet.lat == 40.7128
    assert packet.speed_kph == 55.0


@pytest.mark.parametrize(
    "overrides",
    [
        {"lat": 999},
        {"lng": -999},
        {"speed_kph": -1},
        {"speed_kph": "fast"},
    ],
)
def test_parse_packet_rejects_out_of_range_or_malformed_values(overrides) -> None:
    with pytest.raises(InvalidPacketError):
        parse_packet(_raw_packet(**overrides))


def test_parse_packet_rejects_non_json() -> None:
    with pytest.raises(InvalidPacketError):
        parse_packet("not json")


async def test_publish_packet_keys_by_vehicle_id_and_carries_the_fields() -> None:
    producer = FakeProducer()
    packet = parse_packet(_raw_packet())

    await publish_packet(producer, topic="telemetry.raw", vehicle_id="v1", packet=packet)

    topic, key, value = producer.sent[0]
    assert topic == "telemetry.raw"
    assert key == b"v1"
    body = json.loads(value)
    assert body["vehicle_id"] == "v1"
    assert body["lat"] == 40.7128
    assert body["recorded_at"] == packet.recorded_at.isoformat()


def test_build_batch_keeps_the_last_reading_per_vehicle() -> None:
    raw_records = [
        json.dumps({"vehicle_id": "v1", "lat": 1.0, "lng": 1.0, "recorded_at": "t1"}).encode(),
        json.dumps({"vehicle_id": "v2", "lat": 2.0, "lng": 2.0, "recorded_at": "t1"}).encode(),
        json.dumps({"vehicle_id": "v1", "lat": 1.5, "lng": 1.5, "recorded_at": "t2"}).encode(),
    ]

    documents, latest_by_vehicle = build_batch(raw_records)

    assert len(documents) == 3
    assert latest_by_vehicle["v1"]["recorded_at"] == "t2"
    assert latest_by_vehicle["v2"]["recorded_at"] == "t1"


def test_build_batch_handles_an_empty_batch() -> None:
    documents, latest_by_vehicle = build_batch([])

    assert documents == []
    assert latest_by_vehicle == {}


def test_apply_kill_switch_passes_through_when_inactive() -> None:
    packet = parse_packet(_raw_packet(speed_kph=80))

    result = apply_kill_switch(packet, active=False)

    assert result.speed_kph == 80


def test_apply_kill_switch_forces_zero_speed_when_active() -> None:
    packet = parse_packet(_raw_packet(speed_kph=80))

    result = apply_kill_switch(packet, active=True)

    assert result.speed_kph == 0.0
    assert result.lat == packet.lat  # only speed is overridden
