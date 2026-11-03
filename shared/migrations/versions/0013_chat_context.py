"""Private context notes for a collaborator, project, or conversation."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0013_chat_context"
down_revision = "0012_chat_projects"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("runs", sa.Column("context_checked_at", sa.DateTime(timezone=True)))
    op.create_table(
        "context_notes",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("employee_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("employees.id"), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True)),
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True)),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("content", sa.String(1000), nullable=False),
        sa.Column("source_run_id", postgresql.UUID(as_uuid=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id", "employee_id"], ["projects.id", "projects.employee_id"]),
        sa.ForeignKeyConstraint(["conversation_id", "employee_id"], ["conversations.id", "conversations.employee_id"]),
        sa.CheckConstraint("project_id IS NULL OR conversation_id IS NULL", name="ck_context_notes_one_scope"),
        sa.CheckConstraint("kind IN ('instruction', 'memory')", name="ck_context_notes_kind"),
        sa.UniqueConstraint("source_run_id"),
    )
    op.create_index("ix_context_notes_employee_id", "context_notes", ["employee_id"])
    op.create_index("ix_context_notes_project_id", "context_notes", ["project_id"])
    op.create_index("ix_context_notes_conversation_id", "context_notes", ["conversation_id"])


def downgrade() -> None:
    op.drop_index("ix_context_notes_conversation_id", table_name="context_notes")
    op.drop_index("ix_context_notes_project_id", table_name="context_notes")
    op.drop_index("ix_context_notes_employee_id", table_name="context_notes")
    op.drop_table("context_notes")
    op.drop_column("runs", "context_checked_at")
