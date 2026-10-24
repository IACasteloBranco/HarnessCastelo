"""One-use browser OAuth handoff for an operator-designated connector."""

import asyncio
import hashlib
import hmac
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlsplit
from uuid import UUID, uuid4

import httpx
from oauth_codex.auth import (build_authorize_url, exchange_code_for_tokens,
                              generate_pkce_pair, generate_state, load_oauth_config,
                              parse_callback_url)
from sqlalchemy import delete, select

from backend.database import (Account, CredentialRecord, Employee, EmployeeCredential, InternalSession,
                              OAuthConnectionIntent, session_factory)
from backend.store import TokenBundle, _decode_tokens, _encode_tokens, _fernet


class ConnectionUnavailable(Exception):
    pass


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _exchange(config, code: str, verifier: str):
    with httpx.Client(timeout=30) as client:
        return exchange_code_for_tokens(client, config, code, verifier)


async def start_connection(employee_id: UUID, session_token: str, credential_id: str) -> tuple[UUID, str]:
    config = load_oauth_config()
    verifier, challenge = generate_pkce_pair()
    state = generate_state()
    intent_id = uuid4()
    now = datetime.now(timezone.utc)
    async with session_factory()() as session, session.begin():
        await session.execute(delete(OAuthConnectionIntent).where(
            OAuthConnectionIntent.expires_at < now - timedelta(days=1)))
        credential = await session.scalar(select(CredentialRecord).where(
            CredentialRecord.credential_id == credential_id))
        owner = await session.get(Account, credential.user_id) if credential else None
        employee = await session.get(Employee, employee_id)
        active_session = await session.get(InternalSession, _hash(session_token))
        assignment = await session.get(EmployeeCredential, (employee_id, credential_id))
        if (not credential or credential.revoked or not owner or owner.disabled or not employee
                or employee.disabled or employee.must_change_password or not assignment
                or not assignment.can_connect or not active_session
                or active_session.employee_id != employee_id or active_session.expires_at <= now):
            raise ConnectionUnavailable
        session.add(OAuthConnectionIntent(
            id=intent_id, employee_id=employee_id, credential_id=credential_id,
            session_hash=_hash(session_token), state_hash=_hash(state),
            verifier_ciphertext=_fernet().encrypt(verifier.encode("ascii")),
            redirect_uri=config.redirect_uri, expires_at=now + timedelta(minutes=10),
            status="pending",
        ))
    return intent_id, build_authorize_url(config, state, challenge)


async def complete_connection(employee_id: UUID, session_token: str, intent_id: UUID,
                              callback_url: str) -> None:
    config = load_oauth_config()
    try:
        callback = urlsplit(callback_url)
        expected = urlsplit(config.redirect_uri)
        if (callback.scheme, callback.netloc, callback.path) != (expected.scheme, expected.netloc, expected.path):
            raise ConnectionUnavailable
        state = parse_qs(callback.query).get("state", [""])[0]
        if not state:
            raise ConnectionUnavailable
    except ValueError as exc:
        raise ConnectionUnavailable from exc

    now = datetime.now(timezone.utc)
    async with session_factory()() as session, session.begin():
        intent = await session.scalar(select(OAuthConnectionIntent).where(
            OAuthConnectionIntent.id == intent_id).with_for_update())
        if (not intent or intent.status != "pending" or intent.expires_at <= now
                or intent.employee_id != employee_id or intent.redirect_uri != config.redirect_uri
                or not hmac.compare_digest(intent.session_hash, _hash(session_token))
                or not hmac.compare_digest(intent.state_hash, _hash(state))):
            raise ConnectionUnavailable
        try:
            code = parse_callback_url(callback_url, state)
        except Exception as exc:
            raise ConnectionUnavailable from exc
        verifier = _fernet().decrypt(intent.verifier_ciphertext).decode("ascii")
        credential_id = intent.credential_id
        intent.status = "processing"
        intent.verifier_ciphertext = None

    try:
        tokens = await asyncio.to_thread(_exchange, config, code, verifier)
    except Exception:
        async with session_factory()() as session, session.begin():
            intent = await session.get(OAuthConnectionIntent, intent_id)
            intent.status = "failed"
        raise ConnectionUnavailable from None

    async with session_factory()() as session, session.begin():
        credential = await session.scalar(select(CredentialRecord).where(
            CredentialRecord.credential_id == credential_id).with_for_update())
        owner = await session.get(Account, credential.user_id) if credential else None
        employee = await session.get(Employee, employee_id)
        assignment = await session.get(EmployeeCredential, (employee_id, credential_id))
        active_session = await session.get(InternalSession, _hash(session_token))
        if (not credential or credential.revoked or not owner or owner.disabled or not employee
                or employee.disabled or employee.must_change_password or not assignment
                or not assignment.can_connect or not active_session
                or active_session.employee_id != employee_id
                or active_session.expires_at <= datetime.now(timezone.utc)):
            raise ConnectionUnavailable
        if credential.token_ciphertext:
            previous = _decode_tokens(credential.token_ciphertext)
            if previous.account_id and tokens.account_id and previous.account_id != tokens.account_id:
                raise ConnectionUnavailable
        credential.token_ciphertext = _encode_tokens(TokenBundle(
            tokens.access_token, tokens.refresh_token, tokens.expires_at or 0, tokens.account_id,
        ))
        intent = await session.get(OAuthConnectionIntent, intent_id)
        intent.status = "completed"
