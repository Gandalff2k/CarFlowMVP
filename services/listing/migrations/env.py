import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from services.listing.config import ListingSettings
from services.listing.models import Base

config = context.config

if config.config_file_name is not None:
    # disable_existing_loggers=False: fileConfig's default (True) disables
    # every logger that exists at call time. Migrations run in-process during
    # test setup, so the default would silently kill application logging
    # (Logger.disabled short-circuits regardless of level) for the rest of
    # the test session — found via a real test that asserted on logged output.
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata

settings = ListingSettings()
config.set_main_option("sqlalchemy.url", settings.database_url)


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
