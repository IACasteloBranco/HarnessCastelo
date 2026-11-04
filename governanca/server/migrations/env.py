"""Alembic environment for Governança's isolated PostgreSQL database."""
import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from governanca.server.identity.database import Base
from governanca.server.identity import models  # noqa: F401 - register owned tables

config = context.config
url = os.environ.get("GOVERNANCA_DATABASE_URL", "")
if not url.startswith("postgresql+psycopg://"):
    raise RuntimeError("GOVERNANCA_DATABASE_URL must use postgresql+psycopg://")
config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
if config.config_file_name:
    fileConfig(config.config_file_name)


def run_migrations_offline():
    context.configure(url=url, target_metadata=Base.metadata, literal_binds=True, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    engine = engine_from_config(config.get_section(config.config_ini_section) or {}, prefix="sqlalchemy.", poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=Base.metadata, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
