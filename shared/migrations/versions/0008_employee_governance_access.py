"""Allow a collaborator to hold governance access without losing chat."""

from alembic import op
import sqlalchemy as sa

revision = "0008_employee_governance_access"
down_revision = "0007_conversation_title"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("employees", sa.Column("can_govern", sa.Boolean(), nullable=False,
                                         server_default=sa.false()))


def downgrade() -> None:
    op.drop_column("employees", "can_govern")
