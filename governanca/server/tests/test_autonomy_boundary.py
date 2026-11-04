"""Governance must boot without importing Maximus or shared runtime packages."""

import ast
import unittest
from pathlib import Path
from unittest.mock import patch

from governanca.server.capture_app.settings import Settings


SERVER = Path(__file__).resolve().parents[1]


class AutonomyBoundaryTests(unittest.TestCase):
    def test_database_url_does_not_fall_back_to_maximus_env_file(self):
        with patch.dict("os.environ", {}, clear=True):
            self.assertIsNone(Settings().database_url)
        with patch.dict("os.environ", {"DATABASE_URL": "postgresql+psycopg://fake@localhost/maximus"}, clear=True):
            self.assertIsNone(Settings().database_url)

    def test_capture_and_identity_use_same_governance_database_variable(self):
        with patch.dict("os.environ", {"GOVERNANCA_DATABASE_URL": "postgresql+psycopg://fake@localhost/governanca"}, clear=True):
            settings = Settings()
            url = settings.database_url
            self.assertIsNotNone(url)
            assert url is not None
            self.assertEqual(url.get_secret_value(),
                             "postgresql+psycopg://fake@localhost/governanca")

    def test_server_has_no_maximus_or_shared_imports(self):
        imports = set()
        for path in SERVER.rglob("*.py"):
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                if isinstance(node, ast.Import):
                    imports.update(alias.name for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    imports.add(node.module)
        self.assertEqual(
            sorted(name for name in imports if name.split(".", 1)[0] in {"maximus", "shared"}),
            [],
        )


if __name__ == "__main__":
    unittest.main()
