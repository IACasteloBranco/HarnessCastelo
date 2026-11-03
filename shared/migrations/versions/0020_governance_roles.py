"""Separate department auditors from governance and permit independent approval."""

from alembic import op
import sqlalchemy as sa


revision = "0020_governance_roles"
down_revision = "0019_run_origin"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_index("uq_employees_active_governance", table_name="employees")
    op.drop_constraint("ck_employees_role", "employees", type_="check")
    op.execute("UPDATE employees SET role = 'governance' WHERE can_govern = true")
    op.create_check_constraint("ck_employees_role", "employees",
                               "role IN ('collaborator', 'auditor', 'governance')")
    op.drop_column("employees", "can_govern")
    if op.get_bind().execute(sa.text("SELECT to_regclass('governance_capture.employees')")).scalar_one():
        op.execute("""CREATE OR REPLACE VIEW governance_capture.employees AS
            SELECT employee.code AS employee_id, employee.code AS person_name,
                   department.code AS department_code,
                   CASE WHEN employee.disabled THEN 0 ELSE 1 END::SMALLINT AS active,
                   employee.created_at AS created_at, employee.created_at AS updated_at,
                   employee.organization_id
            FROM public.employees AS employee
            JOIN public.departments AS department ON department.id = employee.department_id
            WHERE employee.role IN ('collaborator', 'auditor')""")


def downgrade() -> None:
    connection = op.get_bind()
    if connection.execute(sa.text("SELECT COUNT(*) FROM employees WHERE role = 'auditor'")).scalar_one():
        raise RuntimeError("Reassign auditor accounts before downgrading")
    if connection.execute(sa.text("""SELECT COUNT(*) FROM (
        SELECT organization_id FROM employees
        WHERE role = 'governance' AND disabled = false
        GROUP BY organization_id HAVING COUNT(*) > 1
    ) AS duplicates""")).scalar_one():
        raise RuntimeError("Keep one active governance account per organization before downgrading")
    if connection.execute(sa.text("SELECT to_regclass('governance_capture.employees')")).scalar_one():
        op.execute("""CREATE OR REPLACE VIEW governance_capture.employees AS
            SELECT employee.code AS employee_id, employee.code AS person_name,
                   department.code AS department_code,
                   CASE WHEN employee.disabled THEN 0 ELSE 1 END::SMALLINT AS active,
                   employee.created_at AS created_at, employee.created_at AS updated_at,
                   employee.organization_id
            FROM public.employees AS employee
            JOIN public.departments AS department ON department.id = employee.department_id
            WHERE employee.role = 'collaborator'""")
    op.add_column("employees", sa.Column("can_govern", sa.Boolean(), nullable=False,
                                          server_default=sa.false()))
    op.drop_constraint("ck_employees_role", "employees", type_="check")
    op.create_check_constraint("ck_employees_role", "employees",
                               "role IN ('collaborator', 'governance')")
    op.create_index("uq_employees_active_governance", "employees", ["organization_id"],
                    unique=True, postgresql_where=sa.text("role = 'governance' AND disabled = false"))
