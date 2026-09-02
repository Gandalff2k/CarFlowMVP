import json

from shared.kafka_consumer import decode_envelope


def _envelope() -> dict:
    return {
        "event_id": "e1",
        "event_type": "vehicle_approved",
        "data": {"vehicle_id": "v1"},
        "trace_context": {},
    }


def test_decode_envelope_reads_a_single_encoded_message() -> None:
    raw = json.dumps(_envelope()).encode()

    assert decode_envelope(raw) == _envelope()


def test_decode_envelope_reads_a_debezium_double_encoded_jsonb_payload() -> None:
    # What a real Debezium worker actually puts on the wire for an outbox
    # `payload` column: Postgres jsonb is always carried as a Connect STRING
    # (io.debezium.data.Json), so JsonConverter re-encodes that string as a
    # JSON string literal — the envelope is JSON inside JSON.
    inner = json.dumps(_envelope())
    raw = json.dumps(inner).encode()

    assert decode_envelope(raw) == _envelope()
