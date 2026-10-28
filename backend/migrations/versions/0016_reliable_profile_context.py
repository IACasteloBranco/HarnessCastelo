"""Queue profile learning and retain profile provenance."""

from alembic import op
import sqlalchemy as sa

revision = "0016_reliable_profile_context"
down_revision = "0015_seed_user_profile"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("runs", sa.Column("context_attempts", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("runs", sa.Column("context_learning_status", sa.String(16), nullable=False, server_default="done"))
    op.add_column("employees", sa.Column("profile_source", sa.String(16), nullable=False, server_default="manual"))
    op.add_column("employees", sa.Column("profile_source_run_id", sa.Uuid(), nullable=True))
    op.add_column("context_notes", sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True))
    op.execute(sa.text("UPDATE context_notes SET updated_at = created_at"))
    op.alter_column("context_notes", "updated_at", nullable=False)
    op.execute(sa.text("UPDATE employees SET profile_source = 'legacy' WHERE profile_text <> ''"))
    op.execute(sa.text("""
        UPDATE runs SET context_checked_at = now()
        WHERE outcome = 'completed' AND conversation_id IS NOT NULL
          AND context_checked_at IS NULL
    """))
def downgrade() -> None:
    op.drop_column("context_notes", "updated_at")
    op.drop_column("employees", "profile_source_run_id")
    op.drop_column("employees", "profile_source")
    op.drop_column("runs", "context_learning_status")
    op.drop_column("runs", "context_attempts")
