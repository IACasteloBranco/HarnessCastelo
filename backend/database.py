import asyncio
import os
import sys
from functools import lru_cache
from datetime import datetime
from uuid import UUID

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, ForeignKeyConstraint, Index, Integer, LargeBinary, String, Text, UniqueConstraint, Uuid, text
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
        UniqueConstraint("employee_id", "client_message_id", name="uq_runs_employee_client_message"),
        ForeignKeyConstraint(["conversation_id", "employee_id"],
                             ["conversations.id", "conversations.employee_id"],
                             name="fk_runs_conversation_employee"),
        CheckConstraint(
            "(conversation_id IS NULL AND client_message_id IS NULL AND chat_prompt IS NULL) OR "
            "(conversation_id IS NOT NULL AND client_message_id IS NOT NULL "
            "AND chat_prompt IS NOT NULL AND employee_id IS NOT NULL)",
            name="ck_runs_chat_fields",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    credential_id: Mapped[str] = mapped_column(ForeignKey("credentials.credential_id"), nullable=False)
    employee_id: Mapped[UUID | None] = mapped_column(ForeignKey("employees.id"), nullable=True, index=True)
    conversation_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True, index=True)
    client_message_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    chat_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
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


class Organization(Base):
    __tablename__ = "organizations"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class Department(Base):
    __tablename__ = "departments"
    __table_args__ = (UniqueConstraint("organization_id", "code"), UniqueConstraint("organization_id", "id"))

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id"), nullable=False)
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class Employee(Base):
    __tablename__ = "employees"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "department_id"], ["departments.organization_id", "departments.id"]
        ),
        CheckConstraint("role IN ('collaborator', 'governance')", name="ck_employees_role"),
        CheckConstraint("role = 'governance' OR department_id IS NOT NULL", name="ck_employees_department"),
        Index(
            "uq_employees_active_governance", "organization_id", unique=True,
            postgresql_where=text("role = 'governance' AND disabled = false"),
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id"), nullable=False)
    department_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    code: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    must_change_password: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    disabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    failed_logins: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class Conversation(Base):
    __tablename__ = "conversations"
    __table_args__ = (UniqueConstraint("id", "employee_id"),)

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    employee_id: Mapped[UUID] = mapped_column(ForeignKey("employees.id"), unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class GovernanceAccess(Base):
    __tablename__ = "governance_access"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    actor_employee_id: Mapped[UUID] = mapped_column(ForeignKey("employees.id"), nullable=False, index=True)
    run_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, index=True)
    action: Mapped[str] = mapped_column(String(16), nullable=False)
    accessed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class InternalSession(Base):
    __tablename__ = "internal_sessions"
    __table_args__ = (Index("ix_internal_sessions_expires_at", "expires_at"),)

    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    employee_id: Mapped[UUID] = mapped_column(ForeignKey("employees.id", ondelete="CASCADE"), nullable=False, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class EmployeeCredential(Base):
    __tablename__ = "employee_credentials"
    __table_args__ = (
        Index("uq_employee_credentials_connector", "credential_id", unique=True,
              postgresql_where=text("can_connect = true")),
    )

    employee_id: Mapped[UUID] = mapped_column(ForeignKey("employees.id", ondelete="CASCADE"), primary_key=True)
    credential_id: Mapped[str] = mapped_column(ForeignKey("credentials.credential_id"), primary_key=True)
    can_connect: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    assigned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class OAuthConnectionIntent(Base):
    __tablename__ = "oauth_connection_intents"
    __table_args__ = (Index("ix_oauth_connection_intents_expires_at", "expires_at"),)

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    employee_id: Mapped[UUID] = mapped_column(ForeignKey("employees.id", ondelete="CASCADE"), nullable=False)
    credential_id: Mapped[str] = mapped_column(ForeignKey("credentials.credential_id"), nullable=False)
    session_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    state_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    verifier_ciphertext: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    redirect_uri: Mapped[str] = mapped_column(Text, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)


@lru_cache(maxsize=1)
def _session_factory() -> async_sessionmaker[AsyncSession]:
    database_url = os.environ.get("DATABASE_URL", "")
    if not database_url.startswith("postgresql+psycopg://"):
        raise RuntimeError("DATABASE_URL must use postgresql+psycopg://")
    engine = create_async_engine(database_url, pool_pre_ping=True)
    return async_sessionmaker(engine, expire_on_commit=False)


def session_factory() -> async_sessionmaker[AsyncSession]:
    return _session_factory()
