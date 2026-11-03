"""Maintain one evolving collaborator profile."""

from alembic import op
import sqlalchemy as sa

revision = "0014_user_profile"
down_revision = "0013_chat_context"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("employees", sa.Column("profile_text", sa.Text(), nullable=False, server_default=""))
    op.add_column("employees", sa.Column("profile_version", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("employees", sa.Column("profile_updated_at", sa.DateTime(timezone=True)))


def downgrade() -> None:
    op.drop_column("employees", "profile_updated_at")
    op.drop_column("employees", "profile_version")
    op.drop_column("employees", "profile_text")
