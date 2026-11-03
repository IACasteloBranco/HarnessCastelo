"""Store generated chat artifacts alongside their source runs."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0011_chat_artifacts"
down_revision = "0010_chat_attachment_downloads"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "chat_artifacts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("format", sa.String(8), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("mime_type", sa.String(255), nullable=False),
        sa.Column("size", sa.BigInteger, nullable=False),
        sa.Column("ciphertext", sa.LargeBinary, nullable=False),
        sa.UniqueConstraint("run_id", "format"),
    )
    op.create_index("ix_chat_artifacts_run_id", "chat_artifacts", ["run_id"])


def downgrade() -> None:
    op.drop_index("ix_chat_artifacts_run_id", table_name="chat_artifacts")
    op.drop_table("chat_artifacts")
