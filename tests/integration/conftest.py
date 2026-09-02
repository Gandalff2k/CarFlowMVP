import asyncio
import os
import pathlib

import asyncpg
import pytest
from alembic import command
from alembic.config import Config
from testcontainers.community.postgres import PostgresContainer
from testcontainers.kafka import KafkaContainer

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
AUTH_DIR = REPO_ROOT / "services" / "auth"
LISTING_DIR = REPO_ROOT / "services" / "listing"
BOOKING_DIR = REPO_ROOT / "services" / "booking"
PAYMENT_DIR = REPO_ROOT / "services" / "payment"


def _run_migrations(service_dir: pathlib.Path, database_url: str) -> None:
    os.environ["DATABASE_URL"] = database_url
    try:
        alembic_cfg = Config(str(service_dir / "alembic.ini"))
        alembic_cfg.set_main_option("script_location", str(service_dir / "migrations"))
        command.upgrade(alembic_cfg, "head")
    finally:
        del os.environ["DATABASE_URL"]


async def _create_database(base_url: str, dbname: str) -> None:
    dsn = base_url.replace("postgresql+asyncpg://", "postgresql://")
    conn = await asyncpg.connect(dsn)
    try:
        await conn.execute(f'CREATE DATABASE "{dbname}"')
    finally:
        await conn.close()


@pytest.fixture(scope="session")
def postgres_container():
    with PostgresContainer("postgres:16-alpine") as postgres:
        yield postgres


@pytest.fixture(scope="session")
def kafka_bootstrap_servers():
    with KafkaContainer("confluentinc/cp-kafka:7.7.1") as kafka:
        yield kafka.get_bootstrap_server()


@pytest.fixture(scope="session")
def database_url(postgres_container: PostgresContainer) -> str:
    url = postgres_container.get_connection_url().replace(
        "postgresql+psycopg2", "postgresql+asyncpg"
    )
    _run_migrations(AUTH_DIR, url)
    return url


@pytest.fixture(scope="session")
def listing_database_url(postgres_container: PostgresContainer) -> str:
    base_url = postgres_container.get_connection_url().replace(
        "postgresql+psycopg2", "postgresql+asyncpg"
    )
    asyncio.run(_create_database(base_url, "listing_test"))
    listing_url = base_url.rsplit("/", 1)[0] + "/listing_test"
    _run_migrations(LISTING_DIR, listing_url)
    return listing_url


@pytest.fixture(scope="session")
def booking_database_url(postgres_container: PostgresContainer) -> str:
    base_url = postgres_container.get_connection_url().replace(
        "postgresql+psycopg2", "postgresql+asyncpg"
    )
    asyncio.run(_create_database(base_url, "booking_test"))
    booking_url = base_url.rsplit("/", 1)[0] + "/booking_test"
    _run_migrations(BOOKING_DIR, booking_url)
    return booking_url


@pytest.fixture(scope="session")
def payment_database_url(postgres_container: PostgresContainer) -> str:
    base_url = postgres_container.get_connection_url().replace(
        "postgresql+psycopg2", "postgresql+asyncpg"
    )
    asyncio.run(_create_database(base_url, "payment_test"))
    payment_url = base_url.rsplit("/", 1)[0] + "/payment_test"
    _run_migrations(PAYMENT_DIR, payment_url)
    return payment_url
