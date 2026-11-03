"""Identify human and internal model requests in governance."""

from alembic import op
import sqlalchemy as sa


revision = "0019_run_origin"
down_revision = "0018_run_lease"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("runs", sa.Column("origin", sa.String(24), nullable=False,
                                    server_default="legacy_unknown"))
    op.execute("UPDATE runs SET origin = 'chat' WHERE conversation_id IS NOT NULL")
    op.execute("UPDATE runs SET origin = 'api' WHERE employee_id IS NULL")
    op.create_check_constraint(
        "ck_runs_origin", "runs",
        "origin IN ('chat', 'api', 'title_generation', 'profile_learning', 'artifact_generation', 'legacy_unknown')",
    )
    op.alter_column("runs", "origin", server_default=None)


def downgrade() -> None:
    op.drop_constraint("ck_runs_origin", "runs", type_="check")
    op.drop_column("runs", "origin")
