"""Import the existing JSON registry and auth files into PostgreSQL without deleting them."""

import argparse
import asyncio
import json
import math
from pathlib import Path

from backend.store import LegacyCredential, TokenBundle, import_legacy
from gateway.config import AUTH_DIR, REGISTRY_FILE


def load_legacy_entries() -> list[LegacyCredential]:
    if not REGISTRY_FILE.is_file():
        raise FileNotFoundError(f"legacy registry not found: {REGISTRY_FILE}")
    raw = json.loads(REGISTRY_FILE.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("legacy registry must be a JSON object")

    entries = []
    for client_key, value in raw.items():
        if not isinstance(value, dict):
            raise ValueError("registry entries must be JSON objects")
        credential_id = value.get("credentialId")
        user_id = value.get("userId")
        credential_type = value.get("type")
        if not all(isinstance(item, str) and item for item in (credential_id, user_id, credential_type)):
            raise ValueError("credentialId, userId, and type must be non-empty strings")
        auth_file = value.get("authFile")
        if not isinstance(auth_file, str) or Path(auth_file).name != auth_file:
            raise ValueError("authFile must be a filename inside PROXY_AUTH_DIR")
        auth_path = (AUTH_DIR / auth_file).resolve()
        if auth_path.parent != AUTH_DIR.resolve():
            raise ValueError("authFile must stay inside PROXY_AUTH_DIR")
        auth = json.loads(auth_path.read_text(encoding="utf-8"))
        if not isinstance(auth, dict):
            raise ValueError(f"auth file must contain a JSON object: {auth_file}")

        limits = value.get("limits", {})
        if not isinstance(limits, dict):
            raise ValueError("limits must be a JSON object")
        rpm = limits.get("rpm", 60)
        daily = limits.get("daily", 500)
        if not isinstance(rpm, int) or isinstance(rpm, bool) or rpm <= 0:
            raise ValueError("credential rpm limit must be a positive integer")
        if not isinstance(daily, int) or isinstance(daily, bool) or daily <= 0:
            raise ValueError("credential daily limit must be a positive integer")

        access = auth.get("access")
        refresh = auth.get("refresh")
        expires = auth.get("expires", 0)
        if not isinstance(client_key, str) or not client_key or not isinstance(access, str) or not access:
            raise ValueError("registry client keys and auth access tokens must be non-empty strings")
        if refresh is not None and not isinstance(refresh, str):
            raise ValueError("auth refresh token must be a string or null")
        if isinstance(expires, bool) or not isinstance(expires, (int, float)) or not math.isfinite(expires):
            raise ValueError("auth expires must be a finite Unix timestamp")

        entries.append(
            LegacyCredential(
                client_key=client_key,
                credential_id=credential_id,
                user_id=user_id,
                credential_type=credential_type,
                rpm=rpm,
                daily=daily,
                tokens=TokenBundle(
                    access=access,
                    refresh=refresh,
                    expires=float(expires),
                    account_id=auth.get("accountId"),
                ),
            )
        )
    return entries


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    imported = await import_legacy(load_legacy_entries())
    print(f"Imported {imported} client key(s); source JSON files were left unchanged.")


if __name__ == "__main__":
    asyncio.run(main())
