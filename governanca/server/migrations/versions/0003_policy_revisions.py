"""Persist versioned, auditable extension policy actions."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "governanca_0003_policy_revisions"
down_revision = "governanca_0002_roster_names"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "governance_policy_revisions",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("organization_id", sa.Uuid(as_uuid=True), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("actions", postgresql.JSONB(), nullable=False),
        sa.Column("changed_by", sa.Uuid(as_uuid=True), sa.ForeignKey("employees.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("organization_id", "version"),
    )


def downgrade():
    op.drop_table("governance_policy_revisions")
