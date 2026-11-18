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
        if self.path == "/first-login":
            self.path = "/first-login.html"
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

    def test_first_login_changes_password_without_opening_analytics(self):
        logged_in = False
        requests = []

        def api(route):
            nonlocal logged_in
            pathname = route.request.url.split("/api/", 1)[1]
            requests.append(pathname)
            if pathname == "auth/login":
                logged_in = True
                payload = {"must_change_password": True}
            elif pathname == "auth/change-password":
                self.assertTrue(logged_in)
                payload = {"must_change_password": False}
            elif pathname == "auth/logout":
                logged_in = False
                route.fulfill(status=204)
                return
            else:
                raise AssertionError(f"Unexpected API path: {pathname}")
            route.fulfill(status=200, content_type="application/json", body=json.dumps(payload))

        assert sync_playwright is not None
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                page = browser.new_page()
                page.route("**/api/**", api)
                page.goto(f"http://127.0.0.1:{self.server.server_port}/first-login")
                page.locator("#employee-code").fill("EMP001")
                page.locator("#password").fill("temporary")
                page.locator("#login-form button").click()
                page.locator("#change-form").wait_for(state="visible")
                page.locator("#current-password").fill("temporary")
                page.locator("#new-password").fill("long-new-password")
                page.locator("#confirm-password").fill("long-new-password")
                page.locator("#change-form button").click()
                page.locator("#success").wait_for(state="visible")
                page.locator("#governance-link").wait_for(state="visible")
                self.assertEqual(requests, ["auth/login", "auth/change-password", "auth/logout"])
            finally:
                browser.close()


if __name__ == "__main__":
    unittest.main()
