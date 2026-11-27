import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from governanca.server.backup_status import get_backup_status


class BackupStatusTests(unittest.TestCase):
    def test_missing_or_invalid_marker_is_unknown(self):
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory) / "last-success"
            self.assertEqual(get_backup_status(marker)["state"], "unknown")
            marker.write_text("not a timestamp")
            self.assertEqual(get_backup_status(marker)["state"], "unknown")
            marker.write_text("2026-11-26T02:55:00")
            self.assertEqual(get_backup_status(marker)["state"], "unknown")

    def test_status_uses_the_backup_jobs_97_hour_window(self):
        now = datetime(2026, 11, 26, 12, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory) / "last-success"
            marker.write_text((now - timedelta(hours=96)).isoformat())
            self.assertEqual(get_backup_status(marker, now=now)["state"], "fresh")
            marker.write_text((now - timedelta(hours=98)).isoformat())
            self.assertEqual(get_backup_status(marker, now=now)["state"], "stale")
            marker.write_text((now + timedelta(hours=1)).isoformat())
            self.assertEqual(get_backup_status(marker, now=now)["state"], "unknown")


if __name__ == "__main__":
    unittest.main()
