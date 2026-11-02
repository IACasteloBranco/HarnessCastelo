import unittest

from tools.serve_privacy import api_allowed


class ExtensionApiRoutesTests(unittest.TestCase):
    def test_only_extension_routes_are_public(self):
        for method, path in [
            ("POST", "/api/auth/extension/login"),
            ("POST", "/api/auth/extension/renew"),
            ("GET", "/api/capture/v1/machines/00000000-0000-4000-8000-000000000001"),
            ("POST", "/api/capture/v1/interactions/00000000-0000-4000-8000-000000000001/response"),
            ("OPTIONS", "/api/capture/v1/interactions"),
        ]:
            self.assertTrue(api_allowed(method, path), path)
        for method, path in [
            ("GET", "/"),
            ("GET", "/api/auth/me"),
            ("GET", "/api/capture/v1/admin/analytics/interactions"),
            ("POST", "/api/capture/v1/admin/machines/00000000-0000-4000-8000-000000000001/assignment-request/approve"),
            ("POST", "/api/auth/extension/me"),
        ]:
            self.assertFalse(api_allowed(method, path), path)
