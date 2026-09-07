"""Pre-load-test seed script — run once from the loadgen VM before starting
Locust. Creates the admin, a pool of hosts with approved vehicles, and a
pool of renters, then writes seed_data.json for locustfile.py to read.


Usage (from the loadgen VM, which sits on the same Hetzner private network
as the infra VM):
    python seed_vehicles.py --kong-url http://<agent-public-ip>:30080 \\
        --postgres-host <infra-private-ip> --hosts 20 --vehicles-per-host 5 --renters 200
"""

import argparse
import asyncio
import json
import random
import uuid

import asyncpg
import httpx
from argon2 import PasswordHasher

PASSWORD = "supersecret123"
ADMIN_EMAIL = "loadtest-admin@example.com"
ADMIN_PASSWORD = "adminpassword123"


def _idempotency_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "Idempotency-Key": str(uuid.uuid4())}


async def register_and_login(client: httpx.AsyncClient, kong_url: str, *, role: str) -> dict:
    email = f"loadtest-{role}-{uuid.uuid4().hex[:10]}@example.com"
    await client.post(
        f"{kong_url}/auth/register",
        json={"name": role.capitalize(), "email": email, "password": PASSWORD, "role": role},
        headers={"Idempotency-Key": str(uuid.uuid4())},
    )
    response = await client.post(f"{kong_url}/auth/login", json={"email": email, "password": PASSWORD})
    response.raise_for_status()
    return {"email": email, "password": PASSWORD, "token": response.json()["access_token"]}


async def ensure_admin(client: httpx.AsyncClient, kong_url: str, *, postgres_host: str) -> str:
    conn = await asyncpg.connect(
        host=postgres_host, port=5432, user="carflow", password="carflow", database="auth"
    )
    try:
        exists = await conn.fetchval("SELECT 1 FROM users WHERE email = $1", ADMIN_EMAIL)
        if not exists:
            password_hash = PasswordHasher().hash(ADMIN_PASSWORD)
            await conn.execute(
                "INSERT INTO users (id, email, name, password_hash, role) "
                "VALUES ($1, $2, $3, $4, 'admin')",
                uuid.uuid4(),
                ADMIN_EMAIL,
                "Loadtest Admin",
                password_hash,
            )
    finally:
        await conn.close()
    response = await client.post(
        f"{kong_url}/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}
    )
    response.raise_for_status()
    return response.json()["access_token"]


async def create_and_approve_vehicle(
    client: httpx.AsyncClient, kong_url: str, *, host_token: str, admin_token: str
) -> str:
    payload = {
        "make": random.choice(["Toyota", "Honda", "Mazda", "Ford", "Tesla"]),
        "model": random.choice(["Corolla", "Civic", "3", "Focus", "Model 3"]),
        "year": random.randint(2018, 2024),
        "daily_price_cents": random.randint(3000, 9000),
        "daily_mileage_limit": random.choice([150, 200, 250]),
        "booking_mode": "instant",
        "latitude": 40.7128 + random.uniform(-0.1, 0.1),
        "longitude": -74.0060 + random.uniform(-0.1, 0.1),
    }
    created = (
        await client.post(
            f"{kong_url}/listing/vehicles", json=payload, headers=_idempotency_headers(host_token)
        )
    ).json()
    await client.post(
        f"{kong_url}/listing/vehicles/{created['id']}/approve",
        headers=_idempotency_headers(admin_token),
    )
    return created["id"]


async def main(args: argparse.Namespace) -> None:
    async with httpx.AsyncClient(timeout=30) as client:
        print("Seeding admin...")
        admin_token = await ensure_admin(client, args.kong_url, postgres_host=args.postgres_host)

        print(f"Registering {args.hosts} hosts and creating/approving vehicles...")
        vehicle_ids: list[str] = []
        for i in range(args.hosts):
            host = await register_and_login(client, args.kong_url, role="host")
            for _ in range(args.vehicles_per_host):
                vehicle_ids.append(
                    await create_and_approve_vehicle(
                        client, args.kong_url, host_token=host["token"], admin_token=admin_token
                    )
                )
            if (i + 1) % 5 == 0:
                print(f"  {i + 1}/{args.hosts} hosts done, {len(vehicle_ids)} vehicles so far")

        print(f"Registering {args.renters} renters...")
        renters = [
            {"email": r["email"], "password": r["password"]}
            for r in [
                await register_and_login(client, args.kong_url, role="renter")
                for _ in range(args.renters)
            ]
        ]

    seed = {"vehicle_ids": vehicle_ids, "renters": renters}
    with open(args.out, "w") as f:
        json.dump(seed, f)
    print(f"Wrote {args.out}: {len(vehicle_ids)} vehicles, {len(renters)} renters")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kong-url", required=True, help="e.g. http://<agent-public-ip>:30080")
    parser.add_argument("--postgres-host", required=True, help="infra VM's private IP")
    parser.add_argument("--hosts", type=int, default=20)
    parser.add_argument("--vehicles-per-host", type=int, default=5)
    parser.add_argument("--renters", type=int, default=200)
    parser.add_argument("--out", default="seed_data.json")
    asyncio.run(main(parser.parse_args()))
