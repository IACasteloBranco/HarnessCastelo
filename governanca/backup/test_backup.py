import base64
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

from governanca.backup.backup import main, tier_for, upload


class BackupTests(unittest.TestCase):
    def test_first_backup_of_month_and_week_controls_retention_tier(self):
        now = datetime(2026, 11, 10, 5, tzinfo=timezone.utc)
        self.assertEqual(tier_for(now, "2026-10", "2026-W45"), ("monthly", "COLDLINE"))
        self.assertEqual(tier_for(now, "2026-11", "2026-W45"), ("weekly", "NEARLINE"))
        self.assertEqual(tier_for(now, "2026-11", "2026-W46"), ("recent", "STANDARD"))

    def test_upload_uses_create_only_precondition_and_checks_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / "backup.dump"
            archive.write_bytes(b"synthetic archive")
            metadata = MagicMock()
            metadata.__enter__.return_value = metadata
            metadata.read.return_value = b'{"access_token":"synthetic-token"}'
            connection = MagicMock()
            connection.getresponse.return_value.status = 200
            with patch("governanca.backup.backup.urlopen", return_value=metadata), patch(
                "governanca.backup.backup.http.client.HTTPSConnection", return_value=connection
            ):
                upload(archive, "backup-bucket", "monthly/backup.dump", "COLDLINE")
            args, kwargs = connection.request.call_args
            self.assertEqual(args[:2], ("PUT", "/backup-bucket/monthly/backup.dump"))
            self.assertEqual(kwargs["headers"]["x-goog-if-generation-match"], "0")
            self.assertEqual(kwargs["headers"]["x-goog-storage-class"], "COLDLINE")
            self.assertIn("GMT", kwargs["headers"]["Date"])
            self.assertEqual(kwargs["headers"]["Content-Length"], str(archive.stat().st_size))
            self.assertEqual(len(base64.b64decode(kwargs["headers"]["Content-MD5"])), 16)

    def test_missing_backup_check_fails_after_four_days(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict("os.environ", {
            "STATE_DIRECTORY": directory,
            "GOVERNANCA_BACKUP_BUCKET": "backup-bucket",
            "GOVERNANCA_BACKUP_DATABASE": "governanca_staging",
        }), patch("sys.argv", ["backup.py", "check"]):
            marker = Path(directory) / "last-success"
            marker.write_text((datetime.now(timezone.utc) - timedelta(days=5)).isoformat())
            with self.assertRaisesRegex(RuntimeError, "BACKUP_STALE"):
                main()
            marker.write_text(datetime.now(timezone.utc).isoformat())
            main()


if __name__ == "__main__":
    unittest.main()
