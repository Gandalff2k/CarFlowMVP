"""Separate from locustfile.py on purpose: telemetry ingest is a WebSocket
path (see PLAN.md/CLAUDE.md's "why WebSockets" rationale — many small,
frequent packets, not request/response), and Locust's HttpUser model has no
native WS support worth fighting for a single-endpoint load profile. This
opens N concurrent connections (one per "vehicle") streaming packets at a
target rate for a fixed duration, and reports throughput/latency directly —
no framework needed for something this shaped.

Needs a host token (the /telemetry/ingest route isn't behind the jwt
plugin — see infra/kong.yml's comment on why — but services/telemetry/app.py
still checks the token itself), so this reuses whichever host was seeded
first by seed_vehicles.py; any authenticated user works for the ingest path
itself, ownership isn't checked at that layer.

Usage:
    python telemetry_load.py --kong-url http://<agent-public-ip>:30080 \\
        --vehicles 100 --rate-hz 1 --duration-seconds 120
"""

import argparse
import asyncio
import datetime as dt
import json
import random
import time
import uuid
from pathlib import Path

import httpx
import websockets

SEED_FILE = Path(__file__).parent / "seed_data.json"


async def get_any_token(kong_url: str) -> str:
    async with httpx.AsyncClient(timeout=15) as client:
        email = f"loadtest-telemetry-{uuid.uuid4().hex[:10]}@example.com"
        await client.post(
            f"{kong_url}/auth/register",
            json={"name": "Telemetry Loadgen", "email": email, "password": "supersecret123", "role": "host"},
            headers={"Idempotency-Key": str(uuid.uuid4())},
        )
        response = await client.post(
            f"{kong_url}/auth/login", json={"email": email, "password": "supersecret123"}
        )
        response.raise_for_status()
        return response.json()["access_token"]


async def stream_vehicle(
    *, ws_url: str, token: str, vehicle_id: str, rate_hz: float, duration_seconds: int, results: dict
) -> None:
    uri = f"{ws_url}/telemetry/ingest/{vehicle_id}?token={token}"
    lat, lng = 40.7128 + random.uniform(-1, 1), -74.0060 + random.uniform(-1, 1)
    sent = 0
    errors = 0
    deadline = time.monotonic() + duration_seconds
    try:
        async with websockets.connect(uri) as ws:
            while time.monotonic() < deadline:
                lat += random.uniform(-0.001, 0.001)
                lng += random.uniform(-0.001, 0.001)
                packet = {
                    "lat": lat,
                    "lng": lng,
                    "speed_kph": random.uniform(10, 110),
                    "recorded_at": dt.datetime.now(dt.UTC).isoformat(),
                }
                try:
                    await ws.send(json.dumps(packet))
                    await ws.recv()
                    sent += 1
                except Exception:
                    errors += 1
                await asyncio.sleep(1 / rate_hz)
    except Exception as exc:
        results[vehicle_id] = {"sent": sent, "errors": errors, "fatal": str(exc)}
        return
    results[vehicle_id] = {"sent": sent, "errors": errors, "fatal": None}


async def main(args: argparse.Namespace) -> None:
    token = await get_any_token(args.kong_url)
    ws_url = args.kong_url.replace("http://", "ws://").replace("https://", "wss://")
    vehicle_ids = [str(uuid.uuid4()) for _ in range(args.vehicles)]

    print(f"Streaming {args.vehicles} vehicles at {args.rate_hz} Hz for {args.duration_seconds}s...")
    results: dict[str, dict] = {}
    start = time.monotonic()
    await asyncio.gather(
        *(
            stream_vehicle(
                ws_url=ws_url,
                token=token,
                vehicle_id=vid,
                rate_hz=args.rate_hz,
                duration_seconds=args.duration_seconds,
                results=results,
            )
            for vid in vehicle_ids
        )
    )
    elapsed = time.monotonic() - start

    total_sent = sum(r["sent"] for r in results.values())
    total_errors = sum(r["errors"] for r in results.values())
    fatal = [vid for vid, r in results.items() if r["fatal"]]
    print(f"Done in {elapsed:.1f}s: {total_sent} packets sent, {total_errors} send/recv errors, "
          f"{len(fatal)} connections died early.")
    if fatal:
        print(f"  first fatal error: {results[fatal[0]]['fatal']}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kong-url", required=True)
    parser.add_argument("--vehicles", type=int, default=50)
    parser.add_argument("--rate-hz", type=float, default=1.0)
    parser.add_argument("--duration-seconds", type=int, default=120)
    asyncio.run(main(parser.parse_args()))
