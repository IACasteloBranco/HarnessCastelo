"""Explicit local data migration from an untracked workbook; never embed employee PII in Alembic."""
import argparse
import csv
import os
from pathlib import Path
from datetime import datetime, timezone
from urllib.parse import urlsplit
from uuid import uuid4

from openpyxl import load_workbook
from sqlalchemy import create_engine, text

from .auth import _code, _name, _password_hash, _temporary_password
from .models import Department, Employee, Organization
from .operator import _restrict_file

TEST_DEPARTMENT_CODE = "GOVERNANCA-TESTE"
TEST_DEPARTMENT_NAME = "Governança (teste local)"


def _label(value):
    return " ".join(value.split()).casefold()


def parse_roster(path: Path) -> tuple[list[tuple[str, str]], list[tuple[str, str, str]]]:
    book = load_workbook(path, read_only=True, data_only=True)
    try:
        sheet = book.active
        if sheet is None:
            raise ValueError("empty workbook")
        rows = sheet.iter_rows(values_only=True)
        headers = next(rows)
        if tuple(str(headers[i]).strip().casefold() for i in (0, 1, 3, 4, 5)) != (
            "departamentos", "código", "funcionário", "código", "departamento"
        ):
            raise ValueError("unexpected roster headers")
        departments = []
        employees = []
        names = set()
        codes = set()
        employee_codes = set()
        employee_names = set()
        pending = []
        for row in rows:
            row = (*row, *(None for _ in range(max(0, 6 - len(row)))))
            if any(value is not None for value in row[:2]):
                if not all(isinstance(value, str) for value in row[:2]):
                    raise ValueError("incomplete department row")
                name, code = _name(row[0].strip()), _code(row[1], 64)
                if _label(name) in names or code in codes:
                    raise ValueError("duplicate department name or code")
                names.add(_label(name))
                codes.add(code)
                departments.append((code, name))
            if any(value is not None for value in row[3:6]):
                if not all(isinstance(value, str) for value in row[3:6]):
                    raise ValueError("incomplete employee row")
                name, code = _name(row[3].strip()), _code(row[4], 128)
                if code in employee_codes or _label(name) in employee_names or code == "COLAB-000":
                    raise ValueError("duplicate employee code or name")
                employee_codes.add(code)
                employee_names.add(_label(name))
                pending.append((code, name, row[5]))
        by_name = {_label(name): code for code, name in departments}
        for code, name, department_name in pending:
            department_code = by_name.get(_label(department_name))
            if not department_code:
                raise ValueError("unknown department in employee row")
            employees.append((code, name, department_code))
        if not departments or not employees:
            raise ValueError("empty roster")
        return departments, employees
    finally:
        book.close()


def migrate_roster(roster_file: Path, password_file: Path) -> tuple[int, int]:
    """Seed one empty local Governança DB atomically; reject an initialized DB."""
    departments, employees = parse_roster(roster_file)
    if any(code == TEST_DEPARTMENT_CODE or _label(name) == _label(TEST_DEPARTMENT_NAME)
           for code, name in departments):
        raise ValueError("reserved test department conflicts with roster")
    departments.append((TEST_DEPARTMENT_CODE, TEST_DEPARTMENT_NAME))
    url = os.environ.get("GOVERNANCA_DATABASE_URL", "")
    parsed = urlsplit(url)
    if (parsed.scheme != "postgresql+psycopg" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
            or not parsed.path.strip("/").startswith("governanca") or parsed.port == 55434):
        raise ValueError("roster migration requires a local Governança database")
    if password_file.resolve().is_relative_to(Path(__file__).resolve().parents[3]):
        raise ValueError("password file must be outside the repository")
    if password_file.exists():
        raise ValueError("password file already exists")
    engine = create_engine(url)
    created_file = False
    try:
        with engine.begin() as connection:
            connection.execute(text("LOCK TABLE organizations, departments, employees IN SHARE ROW EXCLUSIVE MODE"))
            if any(connection.scalar(text(f"SELECT count(*) FROM {table}")) for table in
                   ("organizations", "departments", "employees")):
                raise ValueError("roster migration requires an empty database")
            organization_id = uuid4()
            now = datetime.now(timezone.utc)
            connection.execute(Organization.__table__.insert(), {
                "id": organization_id, "code": "CASTELO-BRANCO", "name": "Castelo Branco", "created_at": now,
            })
            department_ids = {code: uuid4() for code, _ in departments}
            connection.execute(Department.__table__.insert(), [
                {"id": department_ids[code], "organization_id": organization_id, "code": code,
                 "name": name, "created_at": now} for code, name in departments
            ])
            credentials = [(code, _temporary_password()) for code, _, _ in employees]
            credentials.append(("COLAB-000", _temporary_password()))
            hashes = {code: _password_hash(password) for code, password in credentials}
            connection.execute(Employee.__table__.insert(), [
                {"id": uuid4(), "organization_id": organization_id, "department_id": department_ids[dept],
                 "code": code, "display_name": name, "role": "collaborator", "password_hash": hashes[code],
                 "must_change_password": True, "disabled": False, "failed_logins": 0, "created_at": now}
                for code, name, dept in employees
            ] + [{
                "id": uuid4(), "organization_id": organization_id,
                "department_id": department_ids[TEST_DEPARTMENT_CODE],
                "code": "COLAB-000", "display_name": None, "role": "governance",
                "password_hash": hashes["COLAB-000"], "must_change_password": True,
                "disabled": False, "failed_logins": 0, "created_at": now,
            }])
            fd = os.open(password_file, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            created_file = True
            with os.fdopen(fd, "w", newline="", encoding="utf-8") as output:
                _restrict_file(password_file)
                csv.writer(output).writerows(credentials)
                output.flush()
                os.fsync(output.fileno())
        return len(departments), len(credentials)
    except BaseException:
        if created_file:
            password_file.unlink(missing_ok=True)
        raise
    finally:
        engine.dispose()


def main(argv=None):
    parser = argparse.ArgumentParser(description="One-time local Governança roster migration")
    parser.add_argument("roster", type=Path, help="untracked XLSX roster")
    parser.add_argument("--password-file", type=Path, required=True, help="new private CSV outside repository")
    args = parser.parse_args(argv)
    departments, accounts = migrate_roster(args.roster, args.password_file)
    print(f"Migrated {departments} departments and {accounts} temporary accounts. Credentials: {args.password_file}")


if __name__ == "__main__":
    main()
