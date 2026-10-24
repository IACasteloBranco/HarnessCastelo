"""Assign OAuth credentials to employees and preserve legacy run attribution."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0003_shared_oauth"
down_revision = "0002_internal_identity"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("runs", sa.Column("employee_id", postgresql.UUID(as_uuid=True),
                                    sa.ForeignKey("employees.id"), nullable=True))
    op.create_index("ix_runs_employee_id", "runs", ["employee_id"])
    op.create_table(
        "employee_credentials",
        sa.Column("employee_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("employees.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("credential_id", sa.String(255), sa.ForeignKey("credentials.credential_id"), primary_key=True),
        sa.Column("can_connect", sa.Boolean(), nullable=False),
        sa.Column("assigned_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("uq_employee_credentials_connector", "employee_credentials", ["credential_id"],
                    unique=True, postgresql_where=sa.text("can_connect = true"))
    op.create_table(
        "oauth_connection_intents",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("employee_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("employees.id", ondelete="CASCADE"), nullable=False),
        sa.Column("credential_id", sa.String(255), sa.ForeignKey("credentials.credential_id"), nullable=False),
        sa.Column("session_hash", sa.String(64), nullable=False),
        sa.Column("state_hash", sa.String(64), nullable=False),
        sa.Column("verifier_ciphertext", sa.LargeBinary(), nullable=True),
        sa.Column("redirect_uri", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
    )
    op.create_index("ix_oauth_connection_intents_expires_at", "oauth_connection_intents", ["expires_at"])


def downgrade() -> None:
    op.drop_table("oauth_connection_intents")
    op.drop_table("employee_credentials")
    op.drop_index("ix_runs_employee_id", table_name="runs")
    op.drop_column("runs", "employee_id")
