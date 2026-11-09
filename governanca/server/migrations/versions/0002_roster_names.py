"""Store roster display names in Governança's own identity database.

Revision ID: governanca_0002_roster_names
Revises: governanca_0001_identity
"""
from alembic import op
import sqlalchemy as sa

revision = "governanca_0002_roster_names"
down_revision = "governanca_0001_identity"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("employees", sa.Column("display_name", sa.String(255), nullable=True))


def downgrade():
    op.drop_column("employees", "display_name")
