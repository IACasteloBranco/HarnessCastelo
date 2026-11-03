"""Keep encrypted chat attachments until their run expires."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0010_chat_attachment_downloads"
down_revision = "0009_multiple_conversations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "chat_attachments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("run_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("mime_type", sa.String(255), nullable=False),
        sa.Column("size", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("ciphertext", sa.LargeBinary(), nullable=False),
    )
    op.create_index("ix_chat_attachments_run_id", "chat_attachments", ["run_id"])


def downgrade() -> None:
    op.drop_index("ix_chat_attachments_run_id", table_name="chat_attachments")
    op.drop_table("chat_attachments")
