import unittest
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import httpx

from backend.internal_auth import EmployeeInfo
from governanca.server import inspection
from governanca.server.app import app
from governanca.server.auth_api import EXTENSION_ORIGIN, extension_employee


class GovernanceAppTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        app.dependency_overrides[extension_employee] = lambda: EmployeeInfo(
            uuid4(), "synthetic", "org", "dept", "collaborator", False
        )
        self.inspection = patch.object(inspection, "inspect_sensitive_data", new_callable=AsyncMock,
                                       return_value=())
        self.inspection.start()
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://app.test")

    async def asyncTearDown(self):
        await self.client.aclose()
        self.inspection.stop()
        app.dependency_overrides.clear()

    async def test_standalone_app_serves_governance_api_without_codex_proxy(self):
        health = await self.client.get("/healthz")
        inspection = await self.client.post("/api/auth/extension/inspect",
            headers={"Origin": EXTENSION_ORIGIN}, json={"text": "texto sintético"})
        codex_proxy = await self.client.get("/v1/models")
        self.assertEqual(health.status_code, 200)
        self.assertEqual(inspection.status_code, 200)
        self.assertEqual(inspection.json()["action"], "allow")
        self.assertEqual(codex_proxy.status_code, 404)


if __name__ == "__main__":
    unittest.main()
