"""Keep independent conversations and hide deleted ones without removing audit runs."""

from alembic import op
import sqlalchemy as sa

revision = "0009_multiple_conversations"
down_revision = "0008_employee_governance_access"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("conversations_employee_id_key", "conversations", type_="unique")
    op.create_index("ix_conversations_employee_id", "conversations", ["employee_id"])
    op.add_column("conversations", sa.Column("last_activity_at", sa.DateTime(timezone=True)))
    op.add_column("conversations", sa.Column("deleted_at", sa.DateTime(timezone=True)))
    op.add_column("conversations", sa.Column("title_requested_at", sa.DateTime(timezone=True)))
    op.execute(sa.text("""
        UPDATE conversations SET last_activity_at = COALESCE(
            (SELECT MAX(started_at) FROM runs WHERE runs.conversation_id = conversations.id),
            created_at)
    """))
    op.alter_column("conversations", "last_activity_at", nullable=False)
    op.create_index("ix_conversations_employee_activity", "conversations",
                    ["employee_id", "last_activity_at", "id"])


def downgrade() -> None:
    op.drop_index("ix_conversations_employee_activity", table_name="conversations")
    op.drop_column("conversations", "title_requested_at")
    op.drop_column("conversations", "deleted_at")
    op.drop_column("conversations", "last_activity_at")
    op.drop_index("ix_conversations_employee_id", table_name="conversations")
    op.create_unique_constraint("conversations_employee_id_key", "conversations", ["employee_id"])
