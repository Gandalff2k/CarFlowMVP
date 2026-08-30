import os
import pathlib

import pytest
from alembic import command
from alembic.config import Config
from testcontainers.community.postgres import PostgresContainer

AUTH_DIR = pathlib.Path(__file__).resolve().parents[2] / "services" / "auth"


@pytest.fixture(scope="session")
def database_url() -> str:
    with PostgresContainer("postgres:16-alpine") as postgres:
        url = postgres.get_connection_url().replace("postgresql+psycopg2", "postgresql+asyncpg")
        os.environ["DATABASE_URL"] = url
        alembic_cfg = Config(str(AUTH_DIR / "alembic.ini"))
        alembic_cfg.set_main_option("script_location", str(AUTH_DIR / "migrations"))
        command.upgrade(alembic_cfg, "head")
        yield url
        del os.environ["DATABASE_URL"]
