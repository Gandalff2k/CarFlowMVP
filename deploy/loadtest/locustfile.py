"""Locust load profile for the two paths that actually exercise the
saga/Kafka plumbing: search (read-heavy, no writes) and booking creation
(write-heavy — triggers the outbox -> Debezium -> Kafka -> payment saga,
which is exactly the path the Kafka partition-count fix in
deploy/hetzner/bootstrap-infra.sh targets).


Run seed_vehicles.py first — this file reads its output (seed_data.json).

Usage:
    locust -f locustfile.py --host http://<any-agent-public-ip>:30080
    # or headless, see run_loadtest.sh
"""

import datetime as dt
import json
import random
import uuid
from pathlib import Path

from locust import HttpUser, between, task

SEED_FILE = Path(__file__).parent / "seed_data.json"
_seed = json.loads(SEED_FILE.read_text())
VEHICLE_IDS: list[str] = _seed["vehicle_ids"]
RENTERS: list[dict[str, str]] = _seed["renters"]


class SearchUser(HttpUser):
    """Anonymous browsing — no login, matches the real /search route (no
    jwt plugin on it in infra/kong.yml)."""

    weight = 5
    wait_time = between(1, 3)

    @task
    def search_vehicles(self) -> None:
        self.client.get(
            "/search/vehicles",
            params={"sort": random.choice(["price_asc", "price_desc"])},
            name="/search/vehicles",
        )


class BookingUser(HttpUser):
    weight = 1
    wait_time = between(3, 8)

    def on_start(self) -> None:
        renter = random.choice(RENTERS)
        response = self.client.post(
            "/auth/login",
            json={"email": renter["email"], "password": renter["password"]},
            name="/auth/login",
        )
        self.token = response.json()["access_token"]

    def _auth_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}", "Idempotency-Key": str(uuid.uuid4())}

    @task(3)
    def create_booking(self) -> None:
        start = dt.date.today() + dt.timedelta(days=random.randint(10, 90))
        end = start + dt.timedelta(days=random.randint(2, 5))
        self.client.post(
            "/booking/bookings",
            json={
                "vehicle_id": random.choice(VEHICLE_IDS),
                "start_date": str(start),
                "end_date": str(end),
            },
            headers=self._auth_headers(),
            name="/booking/bookings [POST]",
        )

    @task(1)
    def list_own_bookings(self) -> None:
        self.client.get(
            "/booking/bookings",
            headers=self._auth_headers(),
            name="/booking/bookings [GET]",
        )
