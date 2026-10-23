import time
from typing import Callable

import httpx

from config import CLIENT_ID_BY_TYPE
from store import Credential, TokenBundle, valid_access_token

TOKEN_URL = "https://auth.openai.com/oauth/token"


async def _refresh(credential: Credential, tokens: TokenBundle) -> TokenBundle:
    client_id = CLIENT_ID_BY_TYPE.get(
        credential.type,
        CLIENT_ID_BY_TYPE["personal_oauth"],
    )
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(
            TOKEN_URL,
            json={
                "grant_type": "refresh_token",
                "refresh_token": tokens.refresh,
                "client_id": client_id,
            },
        )
        response.raise_for_status()
        payload = response.json()

    return TokenBundle(
        access=payload["access_token"],
        refresh=payload.get("refresh_token", tokens.refresh),
        expires=time.time() + payload.get("expires_in", 3600),
        account_id=tokens.account_id,
    )


async def get_valid_token(credential: Credential) -> str:
    return await valid_access_token(
        credential,
        lambda tokens: _refresh(credential, tokens),
    )
