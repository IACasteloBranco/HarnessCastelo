"""Store a short collaborator-owned conversation title."""

from alembic import op
import sqlalchemy as sa

revision = "0007_conversation_title"
down_revision = "0006_retention_aggregates"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("conversations", sa.Column("title", sa.String(60), nullable=True))


def downgrade() -> None:
    op.drop_column("conversations", "title")
