"""Identify internal department analysis without counting it as employee usage."""

from alembic import op
import sqlalchemy as sa


revision = "0022_department_analysis_origin"
down_revision = "0021_governance_investigations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("ck_runs_origin", "runs", type_="check")
    op.create_check_constraint("ck_runs_origin", "runs", "origin IN ('chat', 'api', 'title_generation', 'profile_learning', 'artifact_generation', 'department_analysis', 'legacy_unknown')")


def downgrade() -> None:
    if op.get_bind().execute(sa.text("SELECT COUNT(*) FROM runs WHERE origin = 'department_analysis'")).scalar_one():
        raise RuntimeError("Retain department analysis runs before downgrading")
    op.drop_constraint("ck_runs_origin", "runs", type_="check")
    op.create_check_constraint("ck_runs_origin", "runs", "origin IN ('chat', 'api', 'title_generation', 'profile_learning', 'artifact_generation', 'legacy_unknown')")
