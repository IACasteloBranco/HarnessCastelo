"""Persist one chat conversation per employee and audit governance reads."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0004_chat_history"
down_revision = "0003_shared_oauth"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "conversations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("employee_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("employees.id"), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("id", "employee_id"),
    )
    op.add_column("runs", sa.Column("conversation_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("runs", sa.Column("client_message_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("runs", sa.Column("chat_prompt", sa.Text(), nullable=True))
    op.create_index("ix_runs_conversation_id", "runs", ["conversation_id"])
    op.create_unique_constraint("uq_runs_employee_client_message", "runs", ["employee_id", "client_message_id"])
    op.create_foreign_key("fk_runs_conversation_employee", "runs", "conversations",
                          ["conversation_id", "employee_id"], ["id", "employee_id"])
    op.create_check_constraint("ck_runs_chat_fields", "runs",
        "(conversation_id IS NULL AND client_message_id IS NULL AND chat_prompt IS NULL) OR "
        "(conversation_id IS NOT NULL AND client_message_id IS NOT NULL "
        "AND chat_prompt IS NOT NULL AND employee_id IS NOT NULL)")
    op.create_table(
        "governance_access",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("actor_employee_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("employees.id"), nullable=False),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("action", sa.String(16), nullable=False),
        sa.Column("accessed_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_governance_access_actor_employee_id", "governance_access", ["actor_employee_id"])
    op.create_index("ix_governance_access_run_id", "governance_access", ["run_id"])


def downgrade() -> None:
    op.drop_table("governance_access")
    op.drop_constraint("ck_runs_chat_fields", "runs", type_="check")
    op.drop_constraint("uq_runs_employee_client_message", "runs", type_="unique")
    op.drop_constraint("fk_runs_conversation_employee", "runs", type_="foreignkey")
    op.drop_index("ix_runs_conversation_id", table_name="runs")
    op.drop_column("runs", "chat_prompt")
    op.drop_column("runs", "client_message_id")
    op.drop_column("runs", "conversation_id")
    op.drop_table("conversations")
