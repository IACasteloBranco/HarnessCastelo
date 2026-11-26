"""Read the backup job's sanitized last-upload marker."""

from datetime import datetime, timedelta, timezone
import os
from pathlib import Path

FRESHNESS_WINDOW = timedelta(hours=97)


def get_backup_status(marker: Path | None = None, *, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    marker = marker or Path(os.environ.get(
        "GOVERNANCA_BACKUP_STATUS_FILE", "/run/governanca-backup-status/last-success"
    ))
    try:
        timestamp = datetime.fromisoformat(marker.read_text(encoding="ascii").strip())
        if timestamp.tzinfo is None:
            return {"state": "unknown", "last_success_at": None}
        timestamp = timestamp.astimezone(timezone.utc)
        if timestamp > now.astimezone(timezone.utc) + timedelta(minutes=5):
            return {"state": "unknown", "last_success_at": None}
    except (OSError, ValueError, UnicodeError):
        return {"state": "unknown", "last_success_at": None}

    return {
        "state": "fresh" if now.astimezone(timezone.utc) - timestamp < FRESHNESS_WINDOW else "stale",
        "last_success_at": timestamp.isoformat(),
    }
