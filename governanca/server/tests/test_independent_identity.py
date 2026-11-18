"""Independent Governança identity contract; run with a disposable database URL."""
import asyncio
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from urllib.parse import urlencode, urlsplit, urlunsplit
from uuid import uuid4

import httpx
import psycopg
from psycopg import sql
from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from sqlalchemy import select


@unittest.skipUnless(os.environ.get("HARNESS_TEST_DATABASE_URL"), "requires disposable PostgreSQL")
class IndependentIdentityTests(unittest.IsolatedAsyncioTestCase):
    loop_factory = asyncio.SelectorEventLoop

    async def asyncTearDown(self):
        from governanca.server.identity.database import _session_factory
        if _session_factory.cache_info().currsize:
            await _session_factory().kw["bind"].dispose()
            _session_factory.cache_clear()

    def tearDown(self):
        url = os.environ["HARNESS_TEST_DATABASE_URL"].replace("postgresql+psycopg://", "postgresql://", 1)
        with psycopg.connect(url) as connection:
            for table in ("governance_investigations", "internal_sessions", "employees", "departments", "organizations"):
                connection.execute("DELETE FROM " + table)
    def test_operator_cli_delivers_secret_to_exclusive_file_only(self):
        url = os.environ["HARNESS_TEST_DATABASE_URL"]
        os.environ["GOVERNANCA_DATABASE_URL"] = url
        config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
        command.upgrade(config, "head")
        env = {**os.environ, "GOVERNANCA_DATABASE_URL": url}
        with tempfile.TemporaryDirectory() as directory:
            secret_file = Path(directory) / "temporary-password"
            def cli(*args):
                return subprocess.run([sys.executable, "-m", "governanca.server.identity.operator", *args],
                                      env=env, capture_output=True, text=True, check=True)
            suffix = uuid4().hex
            org, dept, employee = "org-" + suffix, "dept-" + suffix, "employee-" + suffix
            cli("organization", org, "Governança test")
            cli("department", org, dept, "Test department")
            created = cli("employee", org, employee, "auditor", "--department", dept,
                          "--password-file", str(secret_file))
            temporary = secret_file.read_text().strip()
            self.assertGreater(len(temporary), 20)
            self.assertNotIn(temporary, created.stdout + created.stderr)
            with self.assertRaises(subprocess.CalledProcessError):
                cli("reset", employee, "--password-file", str(secret_file))
            reset_file = Path(directory) / "reset-password"
            reset = cli("reset", employee, "--password-file", str(reset_file))
            self.assertNotEqual(reset_file.read_text().strip(), temporary)
            self.assertNotIn(reset_file.read_text().strip(), reset.stdout + reset.stderr)

    def test_migrations_round_trip_and_match_owned_metadata(self):
        base_url = os.environ["HARNESS_TEST_DATABASE_URL"]
        schema = "migration_probe_" + uuid4().hex
        with psycopg.connect(base_url.replace("postgresql+psycopg://", "postgresql://", 1)) as connection:
            connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
        parsed = urlsplit(base_url)
        query = "&".join(filter(None, (parsed.query, urlencode({"options": "-csearch_path=" + schema}))))
        os.environ["GOVERNANCA_DATABASE_URL"] = urlunsplit(parsed._replace(query=query))
        config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
        try:
            command.upgrade(config, "head")
            command.check(config)
            command.downgrade(config, "base")
            command.upgrade(config, "head")
            command.check(config)
        finally:
            os.environ["GOVERNANCA_DATABASE_URL"] = base_url
            with psycopg.connect(base_url.replace("postgresql+psycopg://", "postgresql://", 1)) as connection:
                connection.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))

    async def test_auth_api_rejects_cross_origin_and_uses_distinct_secure_cookie(self):
        from governanca.server.identity import api, auth

        os.environ["GOVERNANCA_DATABASE_URL"] = os.environ["HARNESS_TEST_DATABASE_URL"]
        command.upgrade(Config(str(Path(__file__).resolve().parents[2] / "alembic.ini")), "head")
        suffix = uuid4().hex
        await auth.provision_organization("org-" + suffix, "Test organization")
        secret = await auth.provision_employee("org-" + suffix, "employee-" + suffix, "governance")
        app = FastAPI()
        app.include_router(api.router)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://governanca.test") as client:
            payload = {"employee_code": "employee-" + suffix, "password": secret}
            forbidden = await client.post("/api/auth/login", json=payload, headers={"Origin": "https://foreign.test"})
            self.assertEqual(forbidden.status_code, 403)
            success = await client.post("/api/auth/login", json=payload, headers={"Origin": "https://governanca.test"})
            self.assertEqual(success.status_code, 200)
            self.assertTrue(success.json()["must_change_password"])
            self.assertIn("governanca_session=", success.headers["set-cookie"])
            self.assertIn("Secure", success.headers["set-cookie"])
            self.assertIn("HttpOnly", success.headers["set-cookie"])
            self.assertNotIn(secret, success.text)

    async def test_governance_can_create_collaborator_with_temporary_password(self):
        from governanca.server.identity import api, auth
        from governanca.server.identity.database import _session_factory

        os.environ["GOVERNANCA_DATABASE_URL"] = os.environ["HARNESS_TEST_DATABASE_URL"]
        command.upgrade(Config(str(Path(__file__).resolve().parents[2] / "alembic.ini")), "head")
        _session_factory.cache_clear()
        suffix = uuid4().hex
        organization = "org-" + suffix
        department = "dept-" + suffix
        governance_code = "governance-" + suffix
        await auth.provision_organization(organization, "Test organization")
        await auth.provision_department(organization, department, "Test department")
        temporary = await auth.provision_employee(organization, governance_code, "governance")
        app = FastAPI()
        app.include_router(api.router)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://governanca.test") as client:
            headers = {"Origin": "https://governanca.test"}
            login = await client.post("/api/auth/login", headers=headers,
                                      json={"employee_code": governance_code, "password": temporary})
            self.assertTrue(login.json()["must_change_password"])
            changed = await client.post("/api/auth/change-password", headers=headers, json={
                "current_password": temporary, "new_password": "changed-governance-password-123"})
            self.assertEqual(changed.status_code, 200)
            departments = await client.get("/api/auth/governance/departments")
            self.assertEqual(departments.json()["departments"], [{"code": department, "name": "Test department"}])
            created = await client.post("/api/auth/governance/accounts", headers=headers, json={
                "employee_code": "collaborator-" + suffix,
                "display_name": "Pessoa de teste",
                "department_code": department,
            })
            self.assertEqual(created.status_code, 201, created.text)
            self.assertEqual(created.headers["cache-control"], "no-store")
            self.assertTrue(created.json()["must_change_password"])
            password = created.json()["temporary_password"]
            self.assertGreater(len(password), 20)
            self.assertTrue((await auth.login("collaborator-" + suffix, password))[1])

    async def test_governance_can_reset_collaborator_password_and_revoke_sessions(self):
        from governanca.server.identity import api, auth, database

        os.environ["GOVERNANCA_DATABASE_URL"] = os.environ["HARNESS_TEST_DATABASE_URL"]
        command.upgrade(Config(str(Path(__file__).resolve().parents[2] / "alembic.ini")), "head")
        database._session_factory.cache_clear()
        suffix = uuid4().hex
        organization = "org-" + suffix
        department = "dept-" + suffix
        governance_code = "governance-" + suffix
        collaborator_code = "collaborator-" + suffix
        await auth.provision_organization(organization, "Test organization")
        await auth.provision_department(organization, department, "Test department")
        governance_password = await auth.provision_employee(organization, governance_code, "governance")
        old_password = await auth.provision_employee(
            organization, collaborator_code, "collaborator", department
        )
        old_login = await auth.login(collaborator_code, old_password)
        self.assertIsNotNone(old_login)
        assert old_login is not None
        old_session, _ = old_login
        app = FastAPI()
        app.include_router(api.router)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="https://governanca.test"
        ) as client:
            headers = {"Origin": "https://governanca.test"}
            await client.post("/api/auth/login", headers=headers, json={
                "employee_code": governance_code, "password": governance_password,
            })
            changed = await client.post("/api/auth/change-password", headers=headers, json={
                "current_password": governance_password,
                "new_password": "changed-governance-password-123",
            })
            self.assertEqual(changed.status_code, 200)
            reset = await client.post("/api/auth/governance/accounts/reset-password", headers=headers, json={
                "employee_code": collaborator_code,
            })

        self.assertEqual(reset.status_code, 200, reset.text)
        self.assertEqual(reset.headers["cache-control"], "no-store")
        self.assertTrue(reset.json()["must_change_password"])
        new_password = reset.json()["temporary_password"]
        self.assertGreater(len(new_password), 20)
        self.assertNotEqual(new_password, old_password)
        self.assertIsNone(await auth.resolve_session(old_session))
        self.assertIsNone(await auth.login(collaborator_code, old_password))
        new_login = await auth.login(collaborator_code, new_password)
        self.assertIsNotNone(new_login)
        assert new_login is not None
        new_session, must_change_password = new_login
        self.assertTrue(must_change_password)
        self.assertIsNotNone(await auth.resolve_session(new_session))

    async def test_collaborator_cannot_reset_another_collaborators_password(self):
        from governanca.server.identity import api, auth, database

        os.environ["GOVERNANCA_DATABASE_URL"] = os.environ["HARNESS_TEST_DATABASE_URL"]
        command.upgrade(Config(str(Path(__file__).resolve().parents[2] / "alembic.ini")), "head")
        database._session_factory.cache_clear()
        suffix = uuid4().hex
        organization = "org-" + suffix
        department = "dept-" + suffix
        await auth.provision_organization(organization, "Test organization")
        await auth.provision_department(organization, department, "Test department")
        first_code = "collaborator-a-" + suffix
        second_code = "collaborator-b-" + suffix
        first_password = await auth.provision_employee(organization, first_code, "collaborator", department)
        await auth.provision_employee(organization, second_code, "collaborator", department)
        app = FastAPI()
        app.include_router(api.router)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="https://governanca.test"
        ) as client:
            headers = {"Origin": "https://governanca.test"}
            await client.post("/api/auth/login", headers=headers, json={
                "employee_code": first_code, "password": first_password,
            })
            response = await client.post("/api/auth/governance/accounts/reset-password", headers=headers, json={
                "employee_code": second_code,
            })
        self.assertEqual(response.status_code, 403)

    async def test_access_request_is_immediately_granted_and_scoped_to_requester(self):
        from governanca.server.identity import auth, database, investigations
        from governanca.server.identity.models import Employee

        os.environ["GOVERNANCA_DATABASE_URL"] = os.environ["HARNESS_TEST_DATABASE_URL"]
        command.upgrade(Config(str(Path(__file__).resolve().parents[2] / "alembic.ini")), "head")
        database._session_factory.cache_clear()
        suffix = uuid4().hex
        org = "org-" + suffix
        await auth.provision_organization(org, "Test organization")
        await auth.provision_department(org, "dept-" + suffix, "Test department")
        passwords = {}
        for code, role, dept in (("viewer", "governance", None), ("approver", "governance", None),
                                 ("other", "governance", None), ("subject", "collaborator", "dept-" + suffix)):
            passwords[code] = await auth.provision_employee(org, code + suffix, role, dept)
        identities = {}
        for code in ("viewer", "approver", "other"):
            token, _ = await auth.login(code + suffix, passwords[code])
            await auth.change_password(token, passwords[code], "changed-password-123")
            identities[code] = (await auth.resolve_session(token)).employee_id
        requested = await investigations.request_investigation(identities["viewer"], "subject" + suffix)
        listed = await investigations.list_investigations(identities["viewer"])
        self.assertEqual(listed[0]["target_employee_code"], "subject" + suffix)
        self.assertTrue(listed[0]["can_use"])
        self.assertFalse(listed[0]["can_approve"])
        self.assertFalse(listed[0]["can_reject"])
        async with database.session_factory()() as session:
            subject = await session.scalar(select(Employee).where(Employee.code == "subject" + suffix))
            other = await session.scalar(select(Employee).where(Employee.code == "other" + suffix))
        await investigations.require_investigation(identities["viewer"], requested["id"], subject.id)
        with self.assertRaises(investigations.InvestigationDenied):
            await investigations.require_investigation(identities["viewer"], requested["id"], other.id)
        with self.assertRaises(investigations.InvestigationDenied):
            await investigations.require_investigation(identities["other"], requested["id"], subject.id)

    async def test_temporary_password_requires_change_before_governance_access(self):
        from governanca.server.identity import auth, database, investigations
        from governanca.server.identity.models import Employee

        os.environ["GOVERNANCA_DATABASE_URL"] = os.environ["HARNESS_TEST_DATABASE_URL"]
        database._session_factory.cache_clear()
        suffix = uuid4().hex
        await auth.provision_organization("org-" + suffix, "Test organization")
        requester = "requester-" + suffix
        temporary = await auth.provision_employee("org-" + suffix, requester, "governance")
        token, change_required = await auth.login(requester, temporary)
        self.assertTrue(change_required)
        employee = await auth.resolve_session(token)
        self.assertTrue(employee.must_change_password)
        with self.assertRaises(investigations.InvestigationDenied):
            await investigations.request_investigation(employee.employee_id, requester)
        self.assertTrue(await auth.change_password(token, temporary, "replaced-password-123"))
        self.assertFalse((await auth.resolve_session(token)).must_change_password)
        self.assertIsNone(await auth.login(requester, temporary))
        async with database.session_factory()() as session:
            row = await session.scalar(select(Employee).where(Employee.code == requester))
            self.assertNotEqual(row.password_hash, temporary)
