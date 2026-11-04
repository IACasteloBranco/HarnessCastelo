import unittest
import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from governanca.server.identity import operator


class OperatorFileTests(unittest.TestCase):
    def test_windows_password_file_acl_is_restricted_before_secret_is_written(self):
        with patch.object(operator.sys, "platform", "win32"), patch.object(
            subprocess, "run", side_effect=[SimpleNamespace(stdout="DOMAIN\\operator\n"), SimpleNamespace()]
        ) as run:
            operator._restrict_file(Path("C:/private/temporary-password"))
        self.assertEqual(run.call_count, 2)
        args = run.call_args.args[0]
        self.assertEqual(args[0], "icacls")
        self.assertIn("/inheritance:r", args)
        self.assertIn("/grant:r", args)
        self.assertIn("DOMAIN\\operator:(F)", args)
        self.assertTrue(run.call_args.kwargs["check"])


if __name__ == "__main__":
    unittest.main()
