"""Group each employee's conversations into optional private projects."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0012_chat_projects"
down_revision = "0011_chat_artifacts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "projects",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("employee_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("employees.id"), nullable=False),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("id", "employee_id"),
    )
    op.create_index("ix_projects_employee_id", "projects", ["employee_id"])
    op.add_column("conversations", sa.Column("project_id", postgresql.UUID(as_uuid=True)))
    op.create_index("ix_conversations_project_id", "conversations", ["project_id"])
    op.create_foreign_key("fk_conversations_project_employee", "conversations", "projects",
                          ["project_id", "employee_id"], ["id", "employee_id"])


def downgrade() -> None:
    op.drop_constraint("fk_conversations_project_employee", "conversations", type_="foreignkey")
    op.drop_index("ix_conversations_project_id", table_name="conversations")
    op.drop_column("conversations", "project_id")
    op.drop_index("ix_projects_employee_id", table_name="projects")
    op.drop_table("projects")
