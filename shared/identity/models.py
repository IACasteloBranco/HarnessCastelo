"""Canonical SQLAlchemy models for shared employee identity."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


class Organization(Base):
    __tablename__ = "organizations"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class Department(Base):
    __tablename__ = "departments"
    __table_args__ = (
        UniqueConstraint("organization_id", "code"),
        UniqueConstraint("organization_id", "id"),
    )

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
        CheckConstraint("role IN ('collaborator', 'auditor', 'governance')", name="ck_employees_role"),
        CheckConstraint("role = 'governance' OR department_id IS NOT NULL", name="ck_employees_department"),
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
    profile_text: Mapped[str] = mapped_column(String, nullable=False, default="")
    profile_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    profile_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    profile_source: Mapped[str] = mapped_column(String(16), nullable=False, default="manual")
    profile_source_run_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)


class InternalSession(Base):
    __tablename__ = "internal_sessions"
    __table_args__ = (Index("ix_internal_sessions_expires_at", "expires_at"),)

    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    employee_id: Mapped[UUID] = mapped_column(ForeignKey("employees.id", ondelete="CASCADE"), nullable=False, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class GovernanceInvestigation(Base):
    __tablename__ = "governance_investigations"
    __table_args__ = (
        CheckConstraint("status IN ('pending', 'approved', 'rejected')", name="ck_investigations_status"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id"), nullable=False)
    requested_by: Mapped[UUID] = mapped_column(ForeignKey("employees.id"), nullable=False)
    purpose: Mapped[str] = mapped_column(String(2000), nullable=False)
    viewer_ids: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    target_employee_id: Mapped[UUID | None] = mapped_column(ForeignKey("employees.id"), nullable=True)
    approved_by: Mapped[UUID | None] = mapped_column(ForeignKey("employees.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
