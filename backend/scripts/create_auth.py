"""Authenticate with oauth-codex and store the account in PostgreSQL."""

import argparse
import asyncio
import re
import tempfile
from pathlib import Path

from oauth_codex import Client
from oauth_codex.auth.store import FileTokenStore

from backend.store import TokenBundle, create_credential, credential_exists


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("user_id", help="local owner ID for this OAuth account")
    parser.add_argument("credential_id", nargs="?", help="optional ID when one user has multiple accounts")
    args = parser.parse_args()
    credential_id = args.credential_id or args.user_id
    for label, value in (("user_id", args.user_id), ("credential_id", credential_id)):
        if not re.fullmatch(r"[A-Za-z0-9_-]+", value):
            parser.error(f"{label} must contain only letters, numbers, '-' or '_'")
    if await credential_exists(credential_id):
        parser.error(f"credential already exists in PostgreSQL: {credential_id}")

    with tempfile.TemporaryDirectory() as temp_dir:
        token_store = FileTokenStore(Path(temp_dir) / "oauth-codex.json")
        client = Client(token_store=token_store)
        client.authenticate()
        tokens = token_store.load()

    if not tokens or not tokens.access_token:
        raise RuntimeError("oauth-codex completed without an access token")

    await create_credential(
        user_id=args.user_id,
        credential_id=credential_id,
        credential_type="personal_oauth",
        tokens=TokenBundle(
            access=tokens.access_token,
            refresh=tokens.refresh_token,
            expires=tokens.expires_at or 0,
            account_id=tokens.account_id,
        ),
    )
    print(f"OAuth credential {credential_id} stored for {args.user_id}")


if __name__ == "__main__":
    asyncio.run(main())
