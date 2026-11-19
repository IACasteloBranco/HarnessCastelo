import unittest
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import httpx
from fastapi import FastAPI

from governanca.server.identity import api
from governanca.server.identity.auth import EmployeeInfo


class GovernancePasswordResetApiTests(unittest.IsolatedAsyncioTestCase):
    def _app(self, actor):
        app = FastAPI()
        app.include_router(api.router)

        async def current_employee():
            return actor

        app.dependency_overrides[api.current_employee] = current_employee
        return app

    async def test_governance_reset_returns_nocache_temporary_password(self):
        actor = EmployeeInfo(uuid4(), "GOV1", "ORG1", None, "governance", False)
        app = self._app(actor)
        with patch.object(api, "reset_password", new_callable=AsyncMock) as reset:
            reset.return_value = "temporary-secret"
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="https://governanca.test"
            ) as client:
                response = await client.post(
                    "/api/auth/governance/accounts/reset-password",
                    headers={"Origin": "https://governanca.test"},
                    json={"employee_code": "EMP1"},
                )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["cache-control"], "no-store")
        self.assertEqual(response.json(), {
            "employee_code": "EMP1",
            "temporary_password": "temporary-secret",
            "must_change_password": True,
        })
        reset.assert_awaited_once_with("EMP1", organization_code="ORG1", role="collaborator")

    async def test_non_governance_cannot_reset_a_collaborators_password(self):
        actor = EmployeeInfo(uuid4(), "EMP2", "ORG1", "FIN", "collaborator", False)
        app = self._app(actor)
        with patch.object(api, "reset_password", new_callable=AsyncMock) as reset:
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="https://governanca.test"
            ) as client:
                response = await client.post(
                    "/api/auth/governance/accounts/reset-password",
                    headers={"Origin": "https://governanca.test"},
                    json={"employee_code": "EMP1"},
                )

        self.assertEqual(response.status_code, 403)
        reset.assert_not_awaited()
