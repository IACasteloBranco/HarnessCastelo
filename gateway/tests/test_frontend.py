import unittest

import httpx

from gateway.main import app


class FrontendTests(unittest.IsolatedAsyncioTestCase):
    async def test_frontend_is_served_without_capturing_api_routes(self):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="https://app.test"
        ) as client:
            page = await client.get("/")
            self.assertEqual(page.status_code, 200)
            self.assertIn("Maximus AI", page.text)
            self.assertEqual((await client.get("/styles.css")).status_code, 200)
            self.assertEqual((await client.get("/app.js")).status_code, 200)
            self.assertEqual((await client.get("/castelo-branco.png")).status_code, 200)
            self.assertEqual((await client.get("/api/unknown")).status_code, 404)


if __name__ == "__main__":
    unittest.main()
