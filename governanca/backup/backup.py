"""Create one Governança PostgreSQL dump and upload it to Cloud Storage."""

import base64
import hashlib
import http.client
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from urllib.parse import quote
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo


def tier_for(now: datetime, last_month: str, last_week: str) -> tuple[str, str]:
    local = now.astimezone(ZoneInfo("America/Bahia"))
    month = local.strftime("%Y-%m")
    week = local.strftime("%G-W%V")
    if month != last_month:
        return "monthly", "COLDLINE"
    if week != last_week:
        return "weekly", "NEARLINE"
    return "recent", "STANDARD"


def upload(path: Path, bucket: str, name: str, storage_class: str) -> None:
    request = Request(
        "http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/token",
        headers={"Metadata-Flavor": "Google"},
    )
    with urlopen(request, timeout=5) as response:
        token = json.load(response)["access_token"]
    digest = hashlib.md5()  # Cloud Storage checks Content-MD5 against the uploaded bytes.
    with path.open("rb") as archive:
        for chunk in iter(lambda: archive.read(1024 * 1024), b""):
            digest.update(chunk)
    connection = http.client.HTTPSConnection("storage.googleapis.com", timeout=120)
    try:
        # shortcut: a failed upload retries the whole dump; use resumable uploads when dumps grow.
        with path.open("rb") as archive:
            connection.request("PUT", f"/{bucket}/{quote(name, safe='/')}", body=archive, headers={
                "Authorization": f"Bearer {token}",
                "Date": format_datetime(datetime.now(timezone.utc), usegmt=True),
                "Content-Type": "application/octet-stream",
                "Content-Length": str(path.stat().st_size),
                "Content-MD5": base64.b64encode(digest.digest()).decode("ascii"),
                "x-goog-storage-class": storage_class,
                "x-goog-if-generation-match": "0",
            })
            response = connection.getresponse()
            if response.status != 200:
                raise RuntimeError(f"Cloud Storage upload failed: HTTP {response.status}: {response.read(512)!r}")
            response.read()
    finally:
        connection.close()


def main() -> None:
    state = Path(os.environ.get("STATE_DIRECTORY", "/var/lib/governanca-backup"))
    now = datetime.now(timezone.utc)
    if sys.argv[1:] == ["check"]:
        marker = state / "last-success"
        if not marker.exists() or now - datetime.fromisoformat(marker.read_text()) >= timedelta(hours=97):
            raise RuntimeError("BACKUP_STALE: no successful backup in the expected interval")
        print("BACKUP_FRESH", flush=True)
        return
    if len(sys.argv) != 1:
        raise ValueError("usage: backup.py [check]")
    bucket = os.environ["GOVERNANCA_BACKUP_BUCKET"]
    database = os.environ["GOVERNANCA_BACKUP_DATABASE"]
    if not re.fullmatch(r"[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]", bucket):
        raise ValueError("invalid backup bucket name")
    month = now.astimezone(ZoneInfo("America/Bahia")).strftime("%Y-%m")
    week = now.astimezone(ZoneInfo("America/Bahia")).strftime("%G-W%V")
    last_month = (state / "last-monthly").read_text().strip() if (state / "last-monthly").exists() else ""
    last_week = (state / "last-weekly").read_text().strip() if (state / "last-weekly").exists() else ""
    tier, storage_class = tier_for(now, last_month, last_week)
    name = f"{tier}/{now:%Y/%m/%Y%m%dT%H%M%SZ}-{os.getpid()}.dump"
    with tempfile.NamedTemporaryFile(prefix="dump-", dir=state, delete=False) as temporary:
        archive = Path(temporary.name)
    try:
        subprocess.run(["pg_dump", "--no-password", "--format=custom", "--compress=6",
                        f"--dbname={database}", f"--file={archive}"], check=True)
        if archive.stat().st_size == 0:
            raise RuntimeError("pg_dump produced an empty archive")
        subprocess.run(["pg_restore", "--list", str(archive)], check=True, stdout=subprocess.DEVNULL)
        upload(archive, bucket, name, storage_class)
        if tier == "monthly":
            (state / "last-monthly").write_text(month)
        if tier in ("monthly", "weekly"):
            (state / "last-weekly").write_text(week)
        (state / "last-success").write_text(now.isoformat())
        print(f"BACKUP_OK gs://{bucket}/{name} ({archive.stat().st_size} bytes, {storage_class})", flush=True)
    finally:
        archive.unlink(missing_ok=True)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        print("BACKUP_FAILED", file=sys.stderr, flush=True)
        raise
