"""Track live run ownership for safe abandoned-run recovery."""

from alembic import op
import sqlalchemy as sa

revision = "0018_run_lease"
down_revision = "0017_department_knowledge"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("runs", sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("runs", "lease_expires_at")
