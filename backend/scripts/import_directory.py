"""Import the Castelo Branco department and employee workbook into an empty database."""

import argparse
import asyncio
import csv
import os
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4
from xml.etree import ElementTree
from zipfile import BadZipFile, ZipFile

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from backend.database import Department, Employee, Organization, session_factory
from backend.internal_auth import _code, _name, _password_hash, _temporary_password

NAMESPACE = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
PASSWORDS_FILE = Path(__file__).resolve().parents[2] / ".tmp" / "senhas-colaboradores.csv"


def load_directory(path: Path) -> tuple[list[tuple[str, str]], list[tuple[str, str, str]]]:
    with ZipFile(path) as workbook:
        names = []
        if "xl/sharedStrings.xml" in workbook.namelist():
            shared = ElementTree.fromstring(workbook.read("xl/sharedStrings.xml"))
            names = ["".join(text.text or "" for text in item.findall(".//x:t", NAMESPACE))
                     for item in shared.findall("x:si", NAMESPACE)]
        sheet = ElementTree.fromstring(workbook.read("xl/worksheets/sheet1.xml"))
        rows = []
        for row in sheet.findall(".//x:sheetData/x:row", NAMESPACE):
            cells = {}
            for cell in row.findall("x:c", NAMESPACE):
                if cell.find("x:f", NAMESPACE) is not None:
                    raise ValueError("formulas are not allowed in the directory workbook")
                value = cell.find("x:v", NAMESPACE)
                inline = cell.find("x:is", NAMESPACE)
                text = value.text if value is not None else (
                    "".join(part.text or "" for part in inline.findall(".//x:t", NAMESPACE))
                    if inline is not None else ""
                )
                if cell.get("t") == "s" and text:
                    text = names[int(text)]
                cells["".join(char for char in cell.get("r", "") if char.isalpha())] = (text or "").strip()
            rows.append(cells)
    return _validate_rows(rows)


def _validate_rows(rows: list[dict[str, str]]) -> tuple[list[tuple[str, str]], list[tuple[str, str, str]]]:
    expected = {"A": "Departamentos", "B": "Código", "D": "Funcionário", "E": "Código", "F": "Departamento"}
    if not rows or any(rows[0].get(column) != title for column, title in expected.items()):
        raise ValueError("unexpected directory workbook headers")

    departments = []
    employees = []
    department_names = set()
    department_codes = set()
    employee_codes = set()
    for number, row in enumerate(rows[1:], start=2):
        if row.get("A") or row.get("B"):
            name, code = _name(row.get("A", "")), _code(row.get("B", ""), 64)
            if name in department_names or code in department_codes:
                raise ValueError(f"duplicate department on row {number}")
            department_names.add(name)
            department_codes.add(code)
            departments.append((name, code))
        if row.get("D") or row.get("E") or row.get("F"):
            name = _name(row.get("D", ""))
            code = _code(row.get("E", ""), 128)
            department = _name(row.get("F", ""))
            if code in employee_codes:
                raise ValueError(f"duplicate employee code on row {number}")
            employee_codes.add(code)
            employees.append((name, code, department))
    if not departments or not employees:
        raise ValueError("the workbook must contain departments and employees")
    unknown = {department for _, _, department in employees} - department_names
    if unknown:
        raise ValueError(f"employees reference unknown departments: {', '.join(sorted(unknown))}")
    return departments, employees


async def import_directory(departments: list[tuple[str, str]], employees: list[tuple[str, str, str]]) -> None:
    passwords = {code: _temporary_password() for _, code, _ in employees}
    hashes = {code: await asyncio.to_thread(_password_hash, password)
              for code, password in passwords.items()}
    PASSWORDS_FILE.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(PASSWORDS_FILE, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as output:
            writer = csv.writer(output)
            writer.writerow(("employee_code", "employee_name", "department", "temporary_password"))
            for name, code, department in employees:
                writer.writerow((code, name, department, passwords[code]))
            output.flush()
            os.fsync(output.fileno())

        async with session_factory()() as session, session.begin():
            if await session.scalar(select(func.count()).select_from(Organization)):
                raise ValueError("initial import requires an empty organization database")
            now = datetime.now(timezone.utc)
            organization_id = uuid4()
            session.add(Organization(id=organization_id, code="CASTELO", name="Castelo Branco", created_at=now))
            await session.flush()
            department_ids = {name: uuid4() for name, _ in departments}
            for name, code in departments:
                session.add(Department(id=department_ids[name], organization_id=organization_id,
                                       code=code, name=name, created_at=now))
            await session.flush()
            for _, code, department in employees:
                session.add(Employee(id=uuid4(), organization_id=organization_id,
                                     department_id=department_ids[department], code=code,
                                     role="collaborator", password_hash=hashes[code],
                                     must_change_password=True, disabled=False,
                                     failed_logins=0, created_at=now))
    except BaseException:
        PASSWORDS_FILE.unlink(missing_ok=True)
        raise


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("workbook", type=Path)
    args = parser.parse_args()
    try:
        departments, employees = load_directory(args.workbook)
        await import_directory(departments, employees)
    except (ValueError, OSError, KeyError, IndexError, BadZipFile,
            ElementTree.ParseError, IntegrityError) as exc:
        parser.exit(1, f"directory import failed: {exc}\n")
    print(f"Imported {len(departments)} departments and {len(employees)} employees.")
    print(f"Temporary passwords: {PASSWORDS_FILE}")


if __name__ == "__main__":
    asyncio.run(main())
