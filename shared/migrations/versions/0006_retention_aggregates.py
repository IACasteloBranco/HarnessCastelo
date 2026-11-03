"""Store deidentified daily metrics after raw run retention."""

from alembic import op
import sqlalchemy as sa

revision = "0006_retention_aggregates"
down_revision = "0005_prompt_governance"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("runs", sa.Column("organization_id", sa.Uuid(), nullable=True))
    op.add_column("runs", sa.Column("department_id", sa.Uuid(), nullable=True))
    op.execute(sa.text("""
        UPDATE runs SET organization_id = employees.organization_id,
                        department_id = employees.department_id
        FROM employees WHERE runs.employee_id = employees.id
    """))
    # Older chat requests copied every prior turn, so keep only the current message.
    op.execute(sa.text("""
        UPDATE runs SET
            request_json = jsonb_build_object('model', model, 'input',
                jsonb_build_array(jsonb_build_object('role', 'user', 'content', chat_prompt))),
            request_body = jsonb_build_object('model', model, 'input',
                jsonb_build_array(jsonb_build_object('role', 'user', 'content', chat_prompt)))::text
        WHERE conversation_id IS NOT NULL
    """))
    op.create_table(
        "daily_usage",
        sa.Column("organization_code", sa.String(64), primary_key=True),
        sa.Column("department_code", sa.String(64), primary_key=True),
        sa.Column("day", sa.Date(), primary_key=True),
        sa.Column("runs", sa.BigInteger(), nullable=False),
        sa.Column("errors", sa.BigInteger(), nullable=False),
        sa.Column("latency_ms", sa.BigInteger(), nullable=False),
        sa.Column("latency_samples", sa.BigInteger(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_daily_usage_expires_at", "daily_usage", ["expires_at"])
    op.create_table(
        "daily_findings",
        sa.Column("organization_code", sa.String(64), primary_key=True),
        sa.Column("department_code", sa.String(64), primary_key=True),
        sa.Column("day", sa.Date(), primary_key=True),
        sa.Column("category", sa.String(64), primary_key=True),
        sa.Column("findings", sa.BigInteger(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_daily_findings_expires_at", "daily_findings", ["expires_at"])
    op.create_index("ix_runs_started_outcome", "runs", ["started_at", "outcome"])


def downgrade() -> None:
    op.drop_index("ix_runs_started_outcome", table_name="runs")
    op.drop_table("daily_findings")
    op.drop_table("daily_usage")
    op.drop_column("runs", "department_id")
    op.drop_column("runs", "organization_id")
