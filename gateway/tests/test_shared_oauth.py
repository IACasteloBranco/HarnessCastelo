import os
import unittest
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit
from unittest.mock import patch
from uuid import uuid4

import httpx
from cryptography.fernet import Fernet
from sqlalchemy import delete, select, update

from backend.database import (Account, CredentialRecord, Department, Employee,
                              EmployeeCredential, InternalSession, OAuthConnectionIntent,
                              Organization, Run, _session_factory, session_factory)
from backend.internal_auth import provision_department, provision_employee, provision_organization
from backend.shared_oauth import assign_credential, create_shared_credential, unassign_credential
from backend.store import (QuotaExceeded, RequestRecord, TokenBundle, UnavailableAssignment,
                           _encode_tokens, admit_employee)
from gateway.main import app

AsyncClient = httpx.AsyncClient


@unittest.skipUnless(os.environ.get("HARNESS_TEST_DATABASE_URL"), "requires a disposable PostgreSQL database")
class SharedOAuthTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        os.environ["DATABASE_URL"] = os.environ["HARNESS_TEST_DATABASE_URL"]
        os.environ["TOKEN_ENCRYPTION_KEY"] = Fernet.generate_key().decode()
        _session_factory.cache_clear()

    async def asyncSetUp(self):
        self.org = f"org-{uuid4().hex}"
        self.dept = f"dept-{uuid4().hex}"
        self.first = f"employee-{uuid4().hex}"
        self.second = f"employee-{uuid4().hex}"
        self.third = f"employee-{uuid4().hex}"
        self.owner = f"owner-{uuid4().hex}"
        self.credential = f"cred-{uuid4().hex}"
        await provision_organization(self.org, "Example")
        await provision_department(self.org, self.dept, "Accounting")
        self.password = await provision_employee(self.org, self.first, "collaborator", self.dept)
        await provision_employee(self.org, self.second, "collaborator", self.dept)
        await provision_employee(self.org, self.third, "collaborator", self.dept)
        await create_shared_credential(self.owner, self.credential, self.first, rpm=2, daily=2)
        await assign_credential(self.credential, self.second)
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://app.test")

    async def asyncTearDown(self):
        await self.client.aclose()
        async with session_factory()() as session, session.begin():
            org_id = await session.scalar(select(Organization.id).where(Organization.code == self.org))
            employee_ids = select(Employee.id).where(Employee.organization_id == org_id)
            await session.execute(delete(Run).where(Run.credential_id == self.credential))
            await session.execute(delete(OAuthConnectionIntent).where(OAuthConnectionIntent.credential_id == self.credential))
            await session.execute(delete(EmployeeCredential).where(EmployeeCredential.credential_id == self.credential))
            await session.execute(delete(InternalSession).where(InternalSession.employee_id.in_(employee_ids)))
            await session.execute(delete(Employee).where(Employee.organization_id == org_id))
            await session.execute(delete(CredentialRecord).where(CredentialRecord.credential_id == self.credential))
            await session.execute(delete(Account).where(Account.user_id == self.owner))
            await session.execute(delete(Department).where(Department.organization_id == org_id))
            await session.execute(delete(Organization).where(Organization.id == org_id))

    async def _login_ready(self):
        headers = {"Origin": "https://app.test"}
        response = await self.client.post("/api/auth/login", json={
            "employee_code": self.first, "password": self.password}, headers=headers)
        self.assertEqual(response.status_code, 200)
        response = await self.client.post("/api/auth/change-password", json={
            "current_password": self.password, "new_password": "long new password 123"}, headers=headers)
        self.assertEqual(response.status_code, 200)

    async def test_connection_is_single_use_and_shared_quota_tracks_employee(self):
        await self._login_ready()
        headers = {"Origin": "https://app.test"}
        self.assertEqual((await self.client.post(
            f"/api/oauth/credentials/{self.credential}/start", headers=headers)).status_code, 200)
        started = (await self.client.post(
            f"/api/oauth/credentials/{self.credential}/start", headers=headers)).json()
        state = parse_qs(urlsplit(started["authorize_url"]).query)["state"][0]
        callback = f"http://localhost:1455/auth/callback?code=test-code&state={state}"
        path = f"/api/oauth/connections/{started['connection_id']}/complete"
        with patch("backend.oauth_connection._exchange", return_value=SimpleNamespace(
            access_token="access", refresh_token="refresh", expires_at=4102444800,
            account_id="upstream-account",
        )):
            self.assertEqual((await self.client.post(path, json={"callback_url": callback},
                                                     headers=headers)).status_code, 200)
        self.assertEqual((await self.client.post(path, json={"callback_url": callback}, headers=headers)).status_code, 403)

        ids = {}
        async with session_factory()() as session, session.begin():
            for employee in (self.first, self.second, self.third):
                ids[employee] = await session.scalar(select(Employee.id).where(Employee.code == employee))
            credential = await session.get(CredentialRecord, self.credential)
            self.assertIsNotNone(credential.token_ciphertext)

        with self.assertRaises(UnavailableAssignment):
            await admit_employee(ids[self.third], self.credential, RequestRecord("GET", "models", b""))
        with self.assertRaises(UnavailableAssignment):
            await admit_employee(ids[self.second], self.credential, RequestRecord("GET", "models", b""))
        async with session_factory()() as session, session.begin():
            await session.execute(update(Employee).where(Employee.id == ids[self.second]).values(
                must_change_password=False))
        one = await admit_employee(ids[self.first], self.credential, RequestRecord("GET", "models", b""))
        two = await admit_employee(ids[self.second], self.credential, RequestRecord("GET", "models", b""))
        with self.assertRaises(QuotaExceeded):
            await admit_employee(ids[self.first], self.credential, RequestRecord("GET", "models", b""))
        async with session_factory()() as session:
            self.assertEqual(await session.scalar(select(Run.employee_id).where(Run.id == one.run_id)), ids[self.first])
            self.assertEqual(await session.scalar(select(Run.employee_id).where(Run.id == two.run_id)), ids[self.second])
        await unassign_credential(self.credential, self.second)
        with self.assertRaises(UnavailableAssignment):
            await admit_employee(ids[self.second], self.credential, RequestRecord("GET", "models", b""))

    async def test_callback_requires_same_session_and_valid_state(self):
        await self._login_ready()
        headers = {"Origin": "https://app.test"}
        started = (await self.client.post(
            f"/api/oauth/credentials/{self.credential}/start", headers=headers)).json()
        state = parse_qs(urlsplit(started["authorize_url"]).query)["state"][0]
        path = f"/api/oauth/connections/{started['connection_id']}/complete"
        callback = f"http://localhost:1455/auth/callback?code=code&state={state}"
        self.assertEqual((await self.client.post(path, json={"callback_url": callback.replace(state, "bad")},
                                                 headers=headers)).status_code, 403)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://app.test") as other:
            self.assertEqual((await other.post("/api/auth/login", json={
                "employee_code": self.first, "password": "long new password 123"}, headers=headers)).status_code, 200)
            self.assertEqual((await other.post(path, json={"callback_url": callback}, headers=headers)).status_code, 403)

    async def test_browser_proxy_uses_employee_session_and_records_owner(self):
        await self._login_ready()
        async with session_factory()() as session, session.begin():
            employee_id = await session.scalar(select(Employee.id).where(Employee.code == self.first))
            credential = await session.get(CredentialRecord, self.credential)
            credential.token_ciphertext = _encode_tokens(TokenBundle(
                "access", "refresh", 4102444800, "upstream-account"))
        path = f"/api/credentials/{self.credential}/v1/responses"
        self.assertEqual((await self.client.post(path, json={})).status_code, 403)
        with patch("gateway.forwarder.get_valid_token", return_value="access"), patch(
            "gateway.forwarder.httpx.AsyncClient",
            side_effect=lambda **kwargs: AsyncClient(transport=httpx.MockTransport(
                lambda request: httpx.Response(200, json={"data": []}))),
        ):
            response = await self.client.post(path, json={}, headers={"Origin": "https://app.test"})
        self.assertEqual(response.status_code, 200)
        async with session_factory()() as session:
            run = await session.scalar(select(Run).where(Run.credential_id == self.credential))
            self.assertEqual(run.employee_id, employee_id)


if __name__ == "__main__":
    unittest.main()
