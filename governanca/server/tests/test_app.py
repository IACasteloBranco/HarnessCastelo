import unittest
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import httpx

from governanca.server.identity.auth import EmployeeInfo
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

    async def test_store_extension_origin_can_log_in_and_inspect(self):
        origin = "chrome-extension://cnbpiejbofngbdncgppaniclkjeigboa"
        with patch("governanca.server.identity.api.login", new_callable=AsyncMock, return_value=None) as login:
            login_response = await self.client.post("/api/auth/extension/login", headers={"Origin": origin},
                                                    json={"employee_code": "test", "password": "test"})
        inspection = await self.client.post("/api/auth/extension/inspect", headers={"Origin": origin},
                                            json={"text": "texto sintético"})
        renewal = await self.client.post("/api/auth/extension/renew", headers={"Origin": origin})
        self.assertEqual(login_response.status_code, 401)
        self.assertEqual(login_response.headers["Access-Control-Allow-Origin"], origin)
        self.assertEqual(inspection.status_code, 200)
        self.assertEqual(renewal.status_code, 401)
        login.assert_awaited_once()

    async def test_password_change_is_served_only_on_first_login_host(self):
        governance = await self.client.get("/change-password")
        first_login = await self.client.get("/", headers={"host": "primeiro-login.castelotecnologia.com.br"})
        self.assertEqual(governance.status_code, 404)
        for path in ("/first-login.html", "/first-login.js", "/first-login.css", "/change-password"):
            self.assertEqual((await self.client.get(path)).status_code, 404, path)
        self.assertEqual(first_login.status_code, 200)
        self.assertEqual(first_login.headers["cache-control"], "no-store")
        self.assertIn("Primeiro acesso", first_login.text)
        self.assertIn("first-login.js", first_login.text)
        asset = await self.client.get("/first-login.js", headers={"host": "primeiro-login.castelotecnologia.com.br"})
        self.assertEqual(asset.status_code, 200)
        self.assertIn("api/auth/change-password", asset.text)
        for path in ("/tv", "/privacidade.html", "/api/capture/v1/admin/analytics/summary"):
            response = await self.client.get(path, headers={"host": "primeiro-login.castelotecnologia.com.br"})
            self.assertEqual(response.status_code, 404, path)

    async def test_first_login_host_keeps_auth_cookie_same_origin_through_password_change(self):
        from governanca.server.identity.auth import EmployeeInfo

        employee = EmployeeInfo(uuid4(), "EMP1", "org", "dept", "collaborator", True)
        origin = "https://primeiro-login.castelotecnologia.com.br"
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url=origin
        ) as client:
            with patch("governanca.server.identity.api.login", new_callable=AsyncMock,
                       return_value=("opaque-session-token", True)), \
                 patch("governanca.server.identity.api.resolve_session", new_callable=AsyncMock,
                       return_value=employee), \
                 patch("governanca.server.identity.api.change_password", new_callable=AsyncMock,
                       return_value=True) as change, \
                 patch("governanca.server.identity.api.logout", new_callable=AsyncMock) as logout:
                headers = {"Origin": origin}
                login = await client.post("/api/auth/login", headers=headers,
                    json={"employee_code": "EMP1", "password": "temporary"})
                changed = await client.post("/api/auth/change-password", headers=headers,
                    json={"current_password": "temporary", "new_password": "a-long-new-password"})
                ended = await client.post("/api/auth/logout", headers=headers)

        self.assertEqual(login.status_code, 200)
        self.assertIn("httponly", login.headers["set-cookie"].lower())
        self.assertIn("secure", login.headers["set-cookie"].lower())
        self.assertEqual(changed.status_code, 200)
        self.assertEqual(ended.status_code, 204)
        change.assert_awaited_once_with("opaque-session-token", "temporary", "a-long-new-password")
        logout.assert_awaited_once_with("opaque-session-token")

    async def test_governance_portal_remains_available(self):
        response = await self.client.get("/")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn("Governança", response.text)

    async def test_untrusted_host_cannot_select_the_first_login_site(self):
        response = await self.client.get("/", headers={"host": "attacker.example"})
        self.assertEqual(response.status_code, 400)


if __name__ == "__main__":
    unittest.main()
