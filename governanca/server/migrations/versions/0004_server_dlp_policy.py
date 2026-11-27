"""Persist organization-scoped server inspection actions."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "governanca_0004_dlp_policy"
down_revision = "governanca_0003_policy_revisions"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("governance_policy_revisions", sa.Column("server_actions", postgresql.JSONB(), nullable=True))
    op.add_column("governance_policy_revisions", sa.Column("extension_engine_version", sa.Integer(), nullable=True))
    op.execute("UPDATE governance_policy_revisions SET extension_engine_version = version")
    op.alter_column("governance_policy_revisions", "extension_engine_version", nullable=False)


def downgrade():
    op.drop_column("governance_policy_revisions", "extension_engine_version")
    op.drop_column("governance_policy_revisions", "server_actions")
