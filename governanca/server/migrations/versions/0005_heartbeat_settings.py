"""Store organization heartbeat cadence and stale threshold."""
from alembic import op
import sqlalchemy as sa

revision = "governanca_0005_heartbeat"
down_revision = "governanca_0004_dlp_policy"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("organizations", sa.Column(
        "heartbeat_interval_hours", sa.Integer(), nullable=False, server_default="12"))
    op.add_column("organizations", sa.Column(
        "heartbeat_stale_hours", sa.Integer(), nullable=False, server_default="72"))


def downgrade():
    op.drop_column("organizations", "heartbeat_stale_hours")
    op.drop_column("organizations", "heartbeat_interval_hours")
