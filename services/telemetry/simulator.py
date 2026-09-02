"""Device simulator: opens N WebSocket connections and streams synthetic
telemetry packets. This is the same load generator that gets reused for the
Hetzner load test later (see PLAN.md) — it's a real client of the real
ingest endpoint, not a test double.

    python -m services.telemetry.simulator --vehicles 20 --rate 2 --duration 30
"""

import argparse
import asyncio
import datetime as dt
import json
import random
import uuid

import websockets

from services.auth.security import create_token


def _mint_token(secret: str, issuer: str) -> str:
    return create_token(
        user_id=uuid.uuid4(),
        role="host",
        token_type="access",
        secret=secret,
        issuer=issuer,
        ttl_seconds=3600,
    )


async def _stream_one_vehicle(
    base_url: str, vehicle_id: str, token: str, *, rate_hz: float, duration_seconds: float
) -> int:
    uri = f"{base_url}/telemetry/ingest/{vehicle_id}?token={token}"
    lat, lng = 40.7128, -74.0060
    sent = 0
    interval = 1.0 / rate_hz
    loop = asyncio.get_event_loop()
    deadline = loop.time() + duration_seconds
    async with websockets.connect(uri) as ws:
        while loop.time() < deadline:
            lat += random.uniform(-0.0005, 0.0005)
            lng += random.uniform(-0.0005, 0.0005)
            packet = {
                "lat": lat,
                "lng": lng,
                "speed_kph": random.uniform(0, 120),
                "recorded_at": dt.datetime.now(dt.UTC).isoformat(),
            }
            await ws.send(json.dumps(packet))
            await ws.recv()
            sent += 1
            await asyncio.sleep(interval)
    return sent


async def run_simulation(
    *,
    base_url: str,
    secret: str,
    issuer: str,
    vehicle_count: int,
    rate_hz: float,
    duration_seconds: float,
) -> int:
    token = _mint_token(secret, issuer)
    tasks = [
        _stream_one_vehicle(
            base_url, str(uuid.uuid4()), token, rate_hz=rate_hz, duration_seconds=duration_seconds
        )
        for _ in range(vehicle_count)
    ]
    results = await asyncio.gather(*tasks)
    return sum(results)


def main() -> None:
    parser = argparse.ArgumentParser(description="CarFlow telemetry device simulator")
    parser.add_argument("--base-url", default="ws://localhost:8080")
    parser.add_argument("--vehicles", type=int, default=10)
    parser.add_argument("--rate", type=float, default=1.0, help="packets per second per vehicle")
    parser.add_argument("--duration", type=float, default=30.0, help="seconds")
    parser.add_argument("--jwt-secret", default="dev-secret")
    parser.add_argument("--jwt-issuer", default="carflow-auth")
    args = parser.parse_args()

    total = asyncio.run(
        run_simulation(
            base_url=args.base_url,
            secret=args.jwt_secret,
            issuer=args.jwt_issuer,
            vehicle_count=args.vehicles,
            rate_hz=args.rate,
            duration_seconds=args.duration,
        )
    )
    print(f"Streamed {total} packets from {args.vehicles} simulated vehicles.")


if __name__ == "__main__":
    main()
