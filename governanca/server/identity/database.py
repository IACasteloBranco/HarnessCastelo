"""Governança-owned SQLAlchemy base and PostgreSQL session factory."""

import asyncio
from functools import lru_cache
import os
import sys

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase


if sys.platform == "win32" and sys.version_info < (3, 14):
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


class Base(DeclarativeBase):
    pass


@lru_cache(maxsize=1)
def _session_factory() -> async_sessionmaker[AsyncSession]:
    database_url = os.environ.get("GOVERNANCA_DATABASE_URL", "")
    if not database_url.startswith("postgresql+psycopg://"):
        raise RuntimeError("GOVERNANCA_DATABASE_URL must use postgresql+psycopg://")
    engine = create_async_engine(database_url, pool_pre_ping=True)
    return async_sessionmaker(engine, expire_on_commit=False)


def session_factory() -> async_sessionmaker[AsyncSession]:
    return _session_factory()
