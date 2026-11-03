"""Add internal employees and revocable browser sessions."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0002_internal_identity"
down_revision = "0001_persistent_harness"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "organizations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("code", sa.String(64), nullable=False, unique=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "departments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("code", sa.String(64), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("organization_id", "code"),
        sa.UniqueConstraint("organization_id", "id"),
    )
    op.create_table(
        "employees",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("department_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("code", sa.String(128), nullable=False, unique=True),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("must_change_password", sa.Boolean(), nullable=False),
        sa.Column("disabled", sa.Boolean(), nullable=False),
        sa.Column("failed_logins", sa.Integer(), nullable=False),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["organization_id", "department_id"], ["departments.organization_id", "departments.id"]
        ),
        sa.CheckConstraint("role IN ('collaborator', 'governance')", name="ck_employees_role"),
        sa.CheckConstraint("role = 'governance' OR department_id IS NOT NULL", name="ck_employees_department"),
    )
    op.create_index(
        "uq_employees_active_governance", "employees", ["organization_id"], unique=True,
        postgresql_where=sa.text("role = 'governance' AND disabled = false"),
    )
    op.create_table(
        "internal_sessions",
        sa.Column("token_hash", sa.String(64), primary_key=True),
        sa.Column("employee_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("employees.id", ondelete="CASCADE"), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_internal_sessions_employee_id", "internal_sessions", ["employee_id"])
    op.create_index("ix_internal_sessions_expires_at", "internal_sessions", ["expires_at"])


def downgrade() -> None:
    op.drop_table("internal_sessions")
    op.drop_index("uq_employees_active_governance", table_name="employees")
    op.drop_table("employees")
    op.drop_table("departments")
    op.drop_table("organizations")
