"""Require an independently approved case for raw governance access."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0021_governance_investigations"
down_revision = "0020_governance_roles"
branch_labels = None
depends_on = None


def upgrade() -> None:
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
    op.add_column("governance_access", sa.Column("investigation_id", sa.Uuid(as_uuid=True), nullable=True))
    op.create_foreign_key("fk_governance_access_investigation", "governance_access",
                          "governance_investigations", ["investigation_id"], ["id"])
    op.create_index("ix_governance_access_investigation_id", "governance_access", ["investigation_id"])


def downgrade() -> None:
    op.drop_index("ix_governance_access_investigation_id", table_name="governance_access")
    op.drop_constraint("fk_governance_access_investigation", "governance_access", type_="foreignkey")
    op.drop_column("governance_access", "investigation_id")
    op.drop_table("governance_investigations")
