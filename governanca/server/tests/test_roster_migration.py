"""Local roster migration: synthetic data only; never embed the real workbook."""
import tempfile
import unittest
import os
import csv
from pathlib import Path
from urllib.parse import urlencode, urlsplit, urlunsplit
from uuid import uuid4

import psycopg
from psycopg import sql
from alembic import command
from alembic.config import Config

from openpyxl import Workbook


def workbook(path, *, duplicate=False, unknown=False):
    book = Workbook()
    sheet = book.active
    assert sheet is not None
    sheet.append(("Departamentos ", "Código ", None, "Funcionário", "Código", "Departamento"))
    sheet.append(("Fiscal", "DEP-1", None, "Pessoa Um", "COLAB-001", "Fiscal"))
    sheet.append(("Contábil", "DEP-2", None, "Pessoa Dois", "COLAB-002", "Ausente" if unknown else "Contábil"))
    if duplicate:
        sheet.append((None, None, None, "Pessoa Três", "COLAB-001", "Fiscal"))
    book.save(path)


class RosterParsingTests(unittest.TestCase):
    def test_resolves_department_names_without_changing_codes(self):
        from governanca.server.identity.roster_migration import parse_roster
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "roster.xlsx"
            workbook(path)
            departments, employees = parse_roster(path)
        self.assertEqual(departments, [("DEP-1", "Fiscal"), ("DEP-2", "Contábil")])
        self.assertEqual(employees, [("COLAB-001", "Pessoa Um", "DEP-1"),
                                     ("COLAB-002", "Pessoa Dois", "DEP-2")])

    def test_rejects_duplicate_code_before_writing(self):
        from governanca.server.identity.roster_migration import parse_roster
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "roster.xlsx"
            workbook(path, duplicate=True)
            with self.assertRaisesRegex(ValueError, "duplicate employee code"):
                parse_roster(path)

    def test_rejects_unknown_department_before_writing(self):
        from governanca.server.identity.roster_migration import parse_roster
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "roster.xlsx"
            workbook(path, unknown=True)
            with self.assertRaisesRegex(ValueError, "unknown department"):
                parse_roster(path)


@unittest.skipUnless(os.environ.get("HARNESS_TEST_DATABASE_URL"), "requires disposable PostgreSQL")
class RosterMigrationTests(unittest.TestCase):
    def test_atomic_import_creates_roster_and_temporary_governance_auditor(self):
        from governanca.server.identity.roster_migration import migrate_roster
        source = os.environ["HARNESS_TEST_DATABASE_URL"]
        schema = "roster_probe_" + uuid4().hex
        with psycopg.connect(source.replace("postgresql+psycopg://", "postgresql://", 1)) as db:
            db.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
        parts = urlsplit(source)
        target = urlunsplit(parts._replace(query=urlencode({"options": "-csearch_path=" + schema})))
        previous = os.environ.get("GOVERNANCA_DATABASE_URL")
        os.environ["GOVERNANCA_DATABASE_URL"] = target
        try:
            command.upgrade(Config(str(Path(__file__).resolve().parents[2] / "alembic.ini")), "head")
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "roster.xlsx"
                secrets = Path(directory) / "passwords.csv"
                workbook(path)
                self.assertEqual(migrate_roster(path, secrets), (3, 3))
                with secrets.open(newline="", encoding="utf-8") as handle:
                    credentials = dict(csv.reader(handle))
                self.assertEqual(set(credentials), {"COLAB-001", "COLAB-002", "COLAB-000"})
                with psycopg.connect(target.replace("postgresql+psycopg://", "postgresql://", 1)) as db:
                    rows = db.execute("""SELECT e.code, e.display_name, e.role, e.must_change_password,
                           d.code FROM employees e LEFT JOIN departments d ON d.id=e.department_id""").fetchall()
                    self.assertEqual(set(rows), {
                        ("COLAB-001", "Pessoa Um", "collaborator", True, "DEP-1"),
                        ("COLAB-002", "Pessoa Dois", "collaborator", True, "DEP-2"),
                        ("COLAB-000", None, "governance", True, "GOVERNANCA-TESTE"),
                    })
                    test_department = db.execute(
                        "SELECT name FROM departments WHERE code='GOVERNANCA-TESTE'"
                    ).fetchone()
                    self.assertEqual(test_department, ("Governança (teste local)",))
                with self.assertRaisesRegex(ValueError, "empty database"):
                    migrate_roster(path, Path(directory) / "second.csv")
                self.assertFalse((Path(directory) / "second.csv").exists())
        finally:
            if previous is None:
                os.environ.pop("GOVERNANCA_DATABASE_URL", None)
            else:
                os.environ["GOVERNANCA_DATABASE_URL"] = previous
            with psycopg.connect(source.replace("postgresql+psycopg://", "postgresql://", 1)) as db:
                db.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


if __name__ == "__main__":
    unittest.main()
