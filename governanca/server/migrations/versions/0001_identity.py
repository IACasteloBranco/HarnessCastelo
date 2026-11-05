"""Initial standalone Governança identity and investigation tables."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "governanca_0001_identity"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "organizations",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("code", sa.String(64), nullable=False, unique=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "departments",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("organization_id", sa.Uuid(as_uuid=True), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("code", sa.String(64), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("organization_id", "code"),
        sa.UniqueConstraint("organization_id", "id"),
    )
    op.create_table(
        "employees",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("organization_id", sa.Uuid(as_uuid=True), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("department_id", sa.Uuid(as_uuid=True)),
        sa.Column("code", sa.String(128), nullable=False, unique=True),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("must_change_password", sa.Boolean(), nullable=False),
        sa.Column("disabled", sa.Boolean(), nullable=False),
        sa.Column("failed_logins", sa.Integer(), nullable=False),
        sa.Column("locked_until", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id", "department_id"], ["departments.organization_id", "departments.id"]),
        sa.CheckConstraint("role IN ('collaborator', 'auditor', 'governance')", name="ck_employees_role"),
        sa.CheckConstraint("role = 'governance' OR department_id IS NOT NULL", name="ck_employees_department"),
    )
    op.create_table(
        "internal_sessions",
        sa.Column("token_hash", sa.String(64), primary_key=True),
        sa.Column("employee_id", sa.Uuid(as_uuid=True), sa.ForeignKey("employees.id", ondelete="CASCADE"), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_internal_sessions_employee_id", "internal_sessions", ["employee_id"])
    op.create_index("ix_internal_sessions_expires_at", "internal_sessions", ["expires_at"])
    op.create_table(
        "governance_investigations",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("organization_id", sa.Uuid(as_uuid=True), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("requested_by", sa.Uuid(as_uuid=True), sa.ForeignKey("employees.id"), nullable=False),
        sa.Column("purpose", sa.String(2000), nullable=False),
        sa.Column("viewer_ids", postgresql.JSONB(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("target_employee_id", sa.Uuid(as_uuid=True), sa.ForeignKey("employees.id")),
        sa.Column("approved_by", sa.Uuid(as_uuid=True), sa.ForeignKey("employees.id")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True)),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("status IN ('pending', 'approved', 'rejected')", name="ck_investigations_status"),
    )


def downgrade():
    op.drop_table("governance_investigations")
    op.drop_table("internal_sessions")
    op.drop_table("employees")
    op.drop_table("departments")
    op.drop_table("organizations")
