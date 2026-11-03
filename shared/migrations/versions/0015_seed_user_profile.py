"""Seed the evolving profile from previously saved automatic memories."""

from alembic import op
import sqlalchemy as sa

revision = "0015_seed_user_profile"
down_revision = "0014_user_profile"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(sa.text("""
        WITH remembered AS (
            SELECT employee_id, string_agg(content, E'\n' ORDER BY created_at, id) AS summary
            FROM context_notes
            WHERE kind = 'memory' AND source_run_id IS NOT NULL
              AND project_id IS NULL AND conversation_id IS NULL
            GROUP BY employee_id
        )
        UPDATE employees AS employee
        SET profile_text = remembered.summary,
            profile_version = 1,
            profile_updated_at = now()
        FROM remembered
        WHERE employee.id = remembered.employee_id
          AND employee.profile_text = ''
          AND length(remembered.summary) <= 3000
    """))


def downgrade() -> None:
    pass
