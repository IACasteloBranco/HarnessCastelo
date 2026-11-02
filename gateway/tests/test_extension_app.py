import unittest

import httpx

from gateway.extension_app import app
from gateway.internal_auth import EXTENSION_ORIGIN


class ExtensionAppTests(unittest.IsolatedAsyncioTestCase):
    async def test_only_extension_surface_is_mounted(self):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://app.test") as client:
            self.assertEqual((await client.get("/")).status_code, 404)
            self.assertEqual((await client.get("/api/chat/conversations")).status_code, 404)
            self.assertEqual((await client.post("/api/auth/extension/renew")).status_code, 403)
            preflight = await client.options("/api/auth/extension/login", headers={
                "Origin": EXTENSION_ORIGIN, "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type",
            })
            self.assertEqual(preflight.status_code, 200)
            self.assertEqual(preflight.headers["access-control-allow-origin"], EXTENSION_ORIGIN)
