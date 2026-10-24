import hashlib
import os
import unittest
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import httpx
from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError

from backend.database import Department, Employee, InternalSession, Organization, _session_factory, session_factory
from backend.internal_auth import (
    disable_employee, provision_department, provision_employee, provision_organization, reset_password,
)
from gateway.main import app


@unittest.skipUnless(os.environ.get("HARNESS_TEST_DATABASE_URL"), "requires a disposable PostgreSQL database")
class InternalAuthTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        os.environ["DATABASE_URL"] = os.environ["HARNESS_TEST_DATABASE_URL"]
        _session_factory.cache_clear()

    async def asyncSetUp(self):
        self.org_code = f"org-{uuid4().hex}"
        self.dept_code = f"dept-{uuid4().hex}"
        await provision_organization(self.org_code, "Example Company")
        await provision_department(self.org_code, self.dept_code, "Accounting")
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://app.test")

    async def asyncTearDown(self):
        await self.client.aclose()
        async with session_factory()() as session, session.begin():
            organization_id = await session.scalar(select(Organization.id).where(Organization.code == self.org_code))
            if organization_id:
                employee_ids = select(Employee.id).where(Employee.organization_id == organization_id)
                await session.execute(delete(InternalSession).where(InternalSession.employee_id.in_(employee_ids)))
                await session.execute(delete(Employee).where(Employee.organization_id == organization_id))
                await session.execute(delete(Department).where(Department.organization_id == organization_id))
                await session.execute(delete(Organization).where(Organization.id == organization_id))

    async def _login(self, code, password, client=None, origin="https://app.test"):
        return await (client or self.client).post(
            "/api/auth/login", json={"employee_code": code, "password": password},
            headers={"Origin": origin} if origin else {},
        )

    async def test_login_first_password_change_and_logout(self):
        code = f"employee-{uuid4().hex}"
        temporary = await provision_employee(self.org_code, code, "collaborator", self.dept_code)
        self.assertEqual((await self.client.get("/api/auth/me")).status_code, 401)
        self.assertEqual((await self._login(code, temporary, origin=None)).status_code, 403)
        self.assertEqual((await self._login(code, "wrong-password")).status_code, 401)

        response = await self._login(code, temporary)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["must_change_password"])
        cookie = response.headers["set-cookie"]
        self.assertIn("httponly", cookie.lower())
        self.assertIn("secure", cookie.lower())
        self.assertIn("samesite=lax", cookie.lower())

        mine = (await self.client.get("/api/auth/me")).json()
        self.assertEqual(mine["employee_code"], code)
        self.assertEqual(mine["department_code"], self.dept_code)
        self.assertTrue(mine["must_change_password"])

        new_password = "minha senha com acentuação"
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="https://app.test"
        ) as other:
            self.assertEqual((await self._login(code, temporary, other)).status_code, 200)
            changed = await self.client.post(
                "/api/auth/change-password",
                json={"current_password": temporary, "new_password": new_password},
                headers={"Origin": "https://app.test"},
            )
            self.assertEqual(changed.status_code, 200)
            self.assertEqual((await other.get("/api/auth/me")).status_code, 401)
        self.assertFalse((await self.client.get("/api/auth/me")).json()["must_change_password"])
        self.assertEqual((await self._login(code, temporary)).status_code, 401)

        logged_out = await self.client.post("/api/auth/logout", headers={"Origin": "https://app.test"})
        self.assertEqual(logged_out.status_code, 204)
        self.assertEqual((await self.client.get("/api/auth/me")).status_code, 401)
        self.assertEqual((await self._login(code, new_password)).status_code, 200)

    async def test_reset_disable_and_expiry_revoke_access(self):
        code = f"employee-{uuid4().hex}"
        temporary = await provision_employee(self.org_code, code, "collaborator", self.dept_code)
        await self._login(code, temporary)
        old_token = self.client.cookies["harness_session"]

        replacement = await reset_password(code)
        self.assertNotEqual(replacement, temporary)
        self.assertEqual((await self.client.get("/api/auth/me")).status_code, 401)
        self.assertEqual((await self._login(code, temporary)).status_code, 401)
        self.assertEqual((await self._login(code, replacement)).status_code, 200)
        self.assertNotEqual(self.client.cookies["harness_session"], old_token)

        async with session_factory()() as session, session.begin():
            await session.execute(update(InternalSession).where(
                InternalSession.token_hash == hashlib.sha256(
                    self.client.cookies["harness_session"].encode()
                ).hexdigest()
            ).values(expires_at=datetime.now(timezone.utc) - timedelta(seconds=1)))
        self.assertEqual((await self.client.get("/api/auth/me")).status_code, 401)
        await self._login(code, replacement)
        await disable_employee(code)
        self.assertEqual((await self.client.get("/api/auth/me")).status_code, 401)
        self.assertEqual((await self._login(code, replacement)).status_code, 401)

    async def test_employee_sessions_are_separate_and_governance_is_unique(self):
        first = f"employee-{uuid4().hex}"
        second = f"employee-{uuid4().hex}"
        first_password = await provision_employee(self.org_code, first, "collaborator", self.dept_code)
        second_password = await provision_employee(self.org_code, second, "collaborator", self.dept_code)
        await provision_employee(self.org_code, f"gov-{uuid4().hex}", "governance")
        with self.assertRaises(IntegrityError):
            await provision_employee(self.org_code, f"gov-{uuid4().hex}", "governance")

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="https://app.test"
        ) as other:
            self.assertEqual((await self._login(first, first_password)).status_code, 200)
            self.assertEqual((await self._login(second, second_password, other)).status_code, 200)
            self.assertEqual((await self.client.get("/api/auth/me")).json()["employee_code"], first)
            self.assertEqual((await other.get("/api/auth/me")).json()["employee_code"], second)

    async def test_five_failed_logins_temporarily_lock_account(self):
        code = f"employee-{uuid4().hex}"
        temporary = await provision_employee(self.org_code, code, "collaborator", self.dept_code)
        for _ in range(5):
            self.assertEqual((await self._login(code, "incorrect-password")).status_code, 401)
        self.assertEqual((await self._login(code, temporary)).status_code, 401)
        async with session_factory()() as session, session.begin():
            await session.execute(update(Employee).where(Employee.code == code).values(
                locked_until=datetime.now(timezone.utc) - timedelta(seconds=1)
            ))
        self.assertEqual((await self._login(code, temporary)).status_code, 200)
