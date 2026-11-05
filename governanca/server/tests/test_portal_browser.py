"""Browser smoke for the standalone portal's first-login security gate."""
import json
import threading
import unittest
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sync_playwright = None

PUBLIC = Path(__file__).resolve().parents[1] / "public"


class PortalFiles(SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/change-password":
            self.path = "/index.html"
        return super().do_GET()

    def log_message(self, format, *args):
        pass


@unittest.skipUnless(sync_playwright, "Playwright browser tooling not installed")
class PortalBrowserTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), partial(PortalFiles, directory=str(PUBLIC)))
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def test_temporary_password_cannot_open_analytics(self):
        logged_in = False
        forced_change = True
        requests = []

        def api(route):
            nonlocal logged_in, forced_change
            request = route.request
            pathname = request.url.split("/api/", 1)[1]
            requests.append(pathname)
            status = 200
            if pathname == "auth/me":
                if logged_in:
                    payload = {"role": "governance", "must_change_password": forced_change}
                else:
                    status, payload = 401, {"detail": "authentication required"}
            elif pathname == "auth/login":
                logged_in = True
                payload = {"must_change_password": True}
            elif pathname == "auth/change-password":
                forced_change = False
                payload = {"must_change_password": False}
            elif pathname.endswith("analytics/summary"):
                payload = {"totals": {"interactions": 1, "responses": 1}}
            elif pathname.endswith("analytics/departments"):
                payload = {"departments": []}
            elif pathname.endswith("analytics/interactions"):
                payload = {"items": [], "total": 0}
            elif pathname == "governance/investigations":
                payload = {"investigations": []}
            elif pathname.endswith("machines/assignment-requests"):
                payload = {"items": []}
            else:
                raise AssertionError(f"Unexpected API path: {pathname}")
            route.fulfill(status=status, content_type="application/json", body=json.dumps(payload))

        assert sync_playwright is not None
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                page = browser.new_page()
                page.route("**/api/**", api)
                page.goto(f"http://127.0.0.1:{self.server.server_port}/")
                page.locator("#employee-code").fill("GOV001")
                page.locator("#password").fill("temporary")
                page.locator("#login-form button").click()
                page.locator("#change-screen").wait_for(state="visible")
                self.assertTrue(page.url.endswith("/change-password"))
                self.assertTrue(page.locator("#portal-screen").is_hidden())
                self.assertFalse(any("analytics/" in path for path in requests))
                page.reload()
                page.locator("#change-screen").wait_for(state="visible")
                self.assertFalse(any("analytics/" in path for path in requests))
                page.locator("#current-password").fill("temporary")
                page.locator("#new-password").fill("long-new-password")
                page.locator("#change-form button").click()
                page.locator("#portal-screen").wait_for(state="visible")
                page.locator("#summary").get_by_text("Interações: 1", exact=False).wait_for()
                self.assertTrue(page.url.endswith("/"))
                self.assertTrue(any("analytics/summary" in path for path in requests))
            finally:
                browser.close()


if __name__ == "__main__":
    unittest.main()
