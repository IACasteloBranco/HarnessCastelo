import asyncio
import os
import sys
from functools import lru_cache
from datetime import datetime
from uuid import UUID

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, LargeBinary, String, Text, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


# Psycopg async connections do not support Windows' default ProactorEventLoop.
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


class Base(DeclarativeBase):
    pass


class Account(Base):
    __tablename__ = "accounts"

    user_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    disabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class CredentialRecord(Base):
    __tablename__ = "credentials"
    __table_args__ = (
        CheckConstraint("rpm > 0", name="ck_credentials_rpm_positive"),
        CheckConstraint("daily > 0", name="ck_credentials_daily_positive"),
    )

    credential_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("accounts.user_id"), nullable=False, index=True)
    credential_type: Mapped[str] = mapped_column(String(64), nullable=False)
    rpm: Mapped[int] = mapped_column(Integer, nullable=False)
    daily: Mapped[int] = mapped_column(Integer, nullable=False)
    token_ciphertext: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class ClientKey(Base):
    __tablename__ = "client_keys"

    key_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    key_prefix: Mapped[str] = mapped_column(String(12), nullable=False)
    credential_id: Mapped[str] = mapped_column(ForeignKey("credentials.credential_id"), nullable=False, index=True)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class Run(Base):
    __tablename__ = "runs"
    __table_args__ = (
        CheckConstraint(
            "outcome IN ('open', 'completed', 'failed', 'incomplete', 'interrupted')",
            name="ck_runs_outcome",
        ),
        Index("ix_runs_credential_started", "credential_id", "started_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    credential_id: Mapped[str] = mapped_column(ForeignKey("credentials.credential_id"), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    method: Mapped[str] = mapped_column(String(16), nullable=False)
    path: Mapped[str] = mapped_column(Text, nullable=False)
    model: Mapped[str | None] = mapped_column(String(255), nullable=True)
    request_body: Mapped[str] = mapped_column(Text, nullable=False)
    request_json: Mapped[dict | list | None] = mapped_column(JSONB, nullable=True)
    response_json: Mapped[dict | list | None] = mapped_column(JSONB, nullable=True)
    usage_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    http_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    outcome: Mapped[str] = mapped_column(String(16), default="open", nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)


class RunEvent(Base):
    __tablename__ = "run_events"

    run_id: Mapped[UUID] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), primary_key=True)
    ordinal: Mapped[int] = mapped_column(Integer, primary_key=True)
    event_type: Mapped[str] = mapped_column(String(128), nullable=False)
    data: Mapped[str] = mapped_column(Text, nullable=False)


@lru_cache(maxsize=1)
def _session_factory() -> async_sessionmaker[AsyncSession]:
    database_url = os.environ.get("DATABASE_URL", "")
    if not database_url.startswith("postgresql+psycopg://"):
        raise RuntimeError("DATABASE_URL must use postgresql+psycopg://")
    engine = create_async_engine(database_url, pool_pre_ping=True)
    return async_sessionmaker(engine, expire_on_commit=False)


def session_factory() -> async_sessionmaker[AsyncSession]:
    return _session_factory()
