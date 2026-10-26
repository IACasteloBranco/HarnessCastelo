"""Create account, credential, quota-ledger, and harness tables."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0001_persistent_harness"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "accounts",
        sa.Column("user_id", sa.String(length=255), primary_key=True),
        sa.Column("disabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "credentials",
        sa.Column("credential_id", sa.String(length=255), primary_key=True),
        sa.Column("user_id", sa.String(length=255), sa.ForeignKey("accounts.user_id"), nullable=False),
        sa.Column("credential_type", sa.String(length=64), nullable=False),
        sa.Column("rpm", sa.Integer(), nullable=False),
        sa.Column("daily", sa.Integer(), nullable=False),
        sa.Column("token_ciphertext", sa.LargeBinary(), nullable=True),
        sa.Column("revoked", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.CheckConstraint("rpm > 0", name="ck_credentials_rpm_positive"),
        sa.CheckConstraint("daily > 0", name="ck_credentials_daily_positive"),
    )
    op.create_index("ix_credentials_user_id", "credentials", ["user_id"])
    op.create_table(
        "client_keys",
        sa.Column("key_hash", sa.String(length=64), primary_key=True),
        sa.Column("key_prefix", sa.String(length=12), nullable=False),
        sa.Column("credential_id", sa.String(length=255), sa.ForeignKey("credentials.credential_id"), nullable=False),
        sa.Column("revoked", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_index("ix_client_keys_credential_id", "client_keys", ["credential_id"])
    op.create_table(
        "runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("credential_id", sa.String(length=255), sa.ForeignKey("credentials.credential_id"), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("method", sa.String(length=16), nullable=False),
        sa.Column("path", sa.Text(), nullable=False),
        sa.Column("model", sa.String(length=255), nullable=True),
        sa.Column("request_body", sa.Text(), nullable=False),
        sa.Column("request_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("response_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("usage_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("http_status", sa.Integer(), nullable=True),
        sa.Column("outcome", sa.String(length=16), server_default="open", nullable=False),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.CheckConstraint(
            "outcome IN ('open', 'completed', 'failed', 'incomplete', 'interrupted')",
            name="ck_runs_outcome",
        ),
    )
    op.create_index("ix_runs_credential_started", "runs", ["credential_id", "started_at"])
    op.create_table(
        "run_events",
        sa.Column("run_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("runs.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("ordinal", sa.Integer(), primary_key=True),
        sa.Column("event_type", sa.String(length=128), nullable=False),
        sa.Column("data", sa.Text(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("run_events")
    op.drop_index("ix_runs_credential_started", table_name="runs")
    op.drop_table("runs")
    op.drop_index("ix_client_keys_credential_id", table_name="client_keys")
    op.drop_table("client_keys")
    op.drop_index("ix_credentials_user_id", table_name="credentials")
    op.drop_table("credentials")
    op.drop_table("accounts")
