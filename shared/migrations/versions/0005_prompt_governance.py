"""Persist prompt findings and durable email alerts."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0005_prompt_governance"
down_revision = "0004_chat_history"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "prompt_findings",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("run_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("category", sa.String(64), nullable=False),
        sa.Column("rule_id", sa.String(64), nullable=False),
        sa.Column("confidence", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("run_id", "rule_id"),
    )
    op.create_index("ix_prompt_findings_run_id", "prompt_findings", ["run_id"])
    op.create_table(
        "alert_outbox",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("finding_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("prompt_findings.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("lease_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_code", sa.String(32), nullable=True),
        sa.CheckConstraint("status IN ('pending', 'leased', 'sent')", name="ck_alert_outbox_status"),
    )
    op.create_index("ix_alert_outbox_due", "alert_outbox", ["status", "next_attempt_at"])


def downgrade() -> None:
    op.drop_table("alert_outbox")
    op.drop_table("prompt_findings")
