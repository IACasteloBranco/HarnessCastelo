import hashlib
import json
import os
import secrets
from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from typing import Awaitable, Callable, Sequence
from uuid import UUID, uuid4

from cryptography.fernet import Fernet
from sqlalchemy import func, select

from backend.database import Account, ClientKey, CredentialRecord, Employee, EmployeeCredential, Run, RunEvent, session_factory


@dataclass(frozen=True)
class Credential:
    credential_id: str
    user_id: str
    type: str
    rpm: int
    daily: int


@dataclass(frozen=True)
class AdmittedRun:
    run_id: UUID
    credential: Credential


@dataclass(frozen=True)
class TokenBundle:
    access: str
    refresh: str | None
    expires: float
    account_id: str | None = None


@dataclass(frozen=True)
class RequestRecord:
    method: str
    path: str
    body: bytes


@dataclass(frozen=True)
class StreamEvent:
    ordinal: int
    event_type: str
    data: str
    complete: bool = True


@dataclass(frozen=True)
class LegacyCredential:
    client_key: str
    credential_id: str
    user_id: str
    credential_type: str
    rpm: int
    daily: int
    tokens: TokenBundle


class UnknownClientKey(Exception):
    pass


class UnavailableAssignment(Exception):
    pass


class QuotaExceeded(Exception):
    def __init__(self, kind: str):
        self.kind = kind


def _fernet() -> Fernet:
    key = os.environ.get("TOKEN_ENCRYPTION_KEY")
    if not key:
        raise RuntimeError("TOKEN_ENCRYPTION_KEY is required")
    try:
        return Fernet(key.encode("ascii"))
    except (ValueError, UnicodeEncodeError) as exc:
        raise RuntimeError("TOKEN_ENCRYPTION_KEY must be a Fernet key") from exc


def _encode_tokens(tokens: TokenBundle) -> bytes:
    return _fernet().encrypt(
        json.dumps(
            {
                "access": tokens.access,
                "refresh": tokens.refresh,
                "expires": tokens.expires,
                "account_id": tokens.account_id,
            }
        ).encode("utf-8")
    )


def _decode_tokens(ciphertext: bytes) -> TokenBundle:
    try:
        data = json.loads(_fernet().decrypt(ciphertext))
        return TokenBundle(
            access=data["access"],
            refresh=data.get("refresh"),
            expires=float(data.get("expires", 0)),
            account_id=data.get("account_id"),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise RuntimeError("stored OAuth token data is invalid") from exc


def _key_hash(client_key: str) -> str:
    return hashlib.sha256(client_key.encode("utf-8")).hexdigest()


def _credential(row: CredentialRecord) -> Credential:
    return Credential(row.credential_id, row.user_id, row.credential_type, row.rpm, row.daily)


async def admit(client_key: str, request: RequestRecord) -> AdmittedRun:
    key_hash = _key_hash(client_key)
    async with session_factory()() as session, session.begin():
        key_ref = await session.execute(
            select(ClientKey.credential_id, CredentialRecord.user_id)
            .join(CredentialRecord, CredentialRecord.credential_id == ClientKey.credential_id)
            .where(ClientKey.key_hash == key_hash)
        )
        ref = key_ref.first()
        if not ref:
            raise UnknownClientKey
        account = await session.scalar(select(Account).where(Account.user_id == ref.user_id).with_for_update())
        credential = await session.scalar(select(CredentialRecord).where(
            CredentialRecord.credential_id == ref.credential_id).with_for_update())
        key = await session.scalar(select(ClientKey).where(ClientKey.key_hash == key_hash).with_for_update())
        if not account or account.disabled or not credential or credential.revoked or not key or key.revoked:
            raise UnknownClientKey
        return await _record_run(session, credential, request, None)


async def admit_employee(employee_id: UUID, credential_id: str, request: RequestRecord) -> AdmittedRun:
    async with session_factory()() as session, session.begin():
        ref = await session.scalar(select(CredentialRecord.user_id).where(
            CredentialRecord.credential_id == credential_id))
        if ref is None:
            raise UnavailableAssignment
        account = await session.scalar(select(Account).where(Account.user_id == ref).with_for_update())
        credential = await session.scalar(select(CredentialRecord).where(
            CredentialRecord.credential_id == credential_id).with_for_update())
        assignment = await session.get(EmployeeCredential, (employee_id, credential_id))
        employee = await session.get(Employee, employee_id)
        if (not account or account.disabled or not credential or credential.revoked
                or not credential.token_ciphertext or not assignment or not employee
                or employee.disabled or employee.must_change_password):
            raise UnavailableAssignment
        return await _record_run(session, credential, request, employee_id)


async def _record_run(session, credential: CredentialRecord, request: RequestRecord,
                      employee_id: UUID | None) -> AdmittedRun:
    now = datetime.now(timezone.utc)
    day_start = datetime.combine(now.date(), time.min, tzinfo=timezone.utc)
    run_id = uuid4()
    body_text = request.body.decode("utf-8", errors="replace")
    try:
        payload = json.loads(body_text) if body_text else None
    except json.JSONDecodeError:
        payload = None

    rpm_count = await session.scalar(
            select(func.count(Run.id)).where(
                Run.credential_id == credential.credential_id,
                Run.started_at >= now - timedelta(seconds=60),
            )
    )
    if rpm_count >= credential.rpm:
        raise QuotaExceeded("rate")

    daily_count = await session.scalar(
            select(func.count(Run.id)).where(
                Run.credential_id == credential.credential_id,
                Run.started_at >= day_start,
            )
    )
    if daily_count >= credential.daily:
        raise QuotaExceeded("daily")

    session.add(Run(
        id=run_id, credential_id=credential.credential_id, employee_id=employee_id,
        started_at=now, method=request.method, path=request.path,
        model=payload.get("model") if isinstance(payload, dict) else None,
        request_body=body_text,
        request_json=payload if isinstance(payload, (dict, list)) else None,
    ))
    return AdmittedRun(run_id, _credential(credential))


async def valid_access_token(
    credential: Credential,
    refresh: Callable[[TokenBundle], Awaitable[TokenBundle]],
) -> str:
    async with session_factory()() as session, session.begin():
        account = await session.scalar(
            select(Account).where(Account.user_id == credential.user_id)
        )
        row = await session.scalar(
            select(CredentialRecord)
            .where(CredentialRecord.credential_id == credential.credential_id)
        )
        if not account or account.disabled or not row or row.revoked or not row.token_ciphertext:
            raise PermissionError(f"credential {credential.credential_id} is unavailable")

        tokens = _decode_tokens(row.token_ciphertext)
        now = datetime.now(timezone.utc).timestamp()
        if now < tokens.expires - 60:
            return tokens.access
        if not tokens.refresh:
            if now >= tokens.expires:
                raise PermissionError(f"credential {credential.credential_id} has an expired access token")
            return tokens.access

        await session.execute(
            select(func.pg_advisory_xact_lock(314159, func.hashtext(credential.credential_id)))
        )
        account = await session.scalar(
            select(Account).where(Account.user_id == credential.user_id).execution_options(populate_existing=True)
        )
        row = await session.scalar(
            select(CredentialRecord)
            .where(CredentialRecord.credential_id == credential.credential_id)
            .execution_options(populate_existing=True)
        )
        if not account or account.disabled or not row or row.revoked or not row.token_ciphertext:
            raise PermissionError(f"credential {credential.credential_id} is unavailable")
        tokens = _decode_tokens(row.token_ciphertext)
        now = datetime.now(timezone.utc).timestamp()
        if now < tokens.expires - 60:
            return tokens.access
        if not tokens.refresh:
            if now >= tokens.expires:
                raise PermissionError(f"credential {credential.credential_id} has an expired access token")
            return tokens.access

        refreshed = await refresh(tokens)
        account = await session.scalar(
            select(Account).where(Account.user_id == credential.user_id)
            .with_for_update().execution_options(populate_existing=True)
        )
        row = await session.scalar(
            select(CredentialRecord)
            .where(CredentialRecord.credential_id == credential.credential_id)
            .with_for_update().execution_options(populate_existing=True)
        )
        if not account or account.disabled or not row or row.revoked or not row.token_ciphertext:
            raise PermissionError(f"credential {credential.credential_id} is unavailable")
        if _decode_tokens(row.token_ciphertext) != tokens:
            raise RuntimeError(f"credential {credential.credential_id} changed during OAuth refresh")
        row.token_ciphertext = _encode_tokens(refreshed)
        return refreshed.access


async def create_credential(
    user_id: str,
    tokens: TokenBundle,
    credential_type: str = "personal_oauth",
    rpm: int = 60,
    daily: int = 500,
    credential_id: str | None = None,
) -> None:
    credential_id = credential_id or user_id
    async with session_factory()() as session, session.begin():
        account = await session.scalar(select(Account).where(Account.user_id == user_id).with_for_update())
        if account and account.disabled:
            raise ValueError(f"user {user_id} is disabled")
        if not account:
            session.add(Account(user_id=user_id, created_at=datetime.now(timezone.utc)))
            await session.flush()
        existing = await session.get(CredentialRecord, credential_id)
        if existing:
            raise ValueError(f"credential already exists: {credential_id}")
        session.add(
            CredentialRecord(
                credential_id=credential_id,
                user_id=user_id,
                credential_type=credential_type,
                rpm=rpm,
                daily=daily,
                token_ciphertext=_encode_tokens(tokens),
            )
        )


async def credential_exists(credential_id: str) -> bool:
    async with session_factory()() as session:
        return await session.scalar(
            select(CredentialRecord.credential_id).where(
                CredentialRecord.credential_id == credential_id
            )
        ) is not None


async def issue_client_key(credential_id: str) -> str:
    client_key = "sk-" + secrets.token_urlsafe(32)
    async with session_factory()() as session, session.begin():
        user_id = await session.scalar(
            select(CredentialRecord.user_id).where(CredentialRecord.credential_id == credential_id)
        )
        account = await session.scalar(
            select(Account).where(Account.user_id == user_id).with_for_update()
        ) if user_id else None
        credential = await session.scalar(
            select(CredentialRecord)
            .where(CredentialRecord.credential_id == credential_id)
            .with_for_update()
        )
        if not account or account.disabled or not credential or credential.revoked:
            raise ValueError(f"credential not found or revoked: {credential_id}")
        session.add(
            ClientKey(
                key_hash=_key_hash(client_key),
                key_prefix=client_key[:12],
                credential_id=credential_id,
            )
        )
    return client_key


async def revoke_user(user_id: str) -> int:
    async with session_factory()() as session, session.begin():
        account = await session.scalar(select(Account).where(Account.user_id == user_id).with_for_update())
        if not account:
            return 0
        account.disabled = True
        credentials = (await session.scalars(
            select(CredentialRecord)
            .where(CredentialRecord.user_id == user_id)
            .order_by(CredentialRecord.credential_id)
            .with_for_update()
        )).all()
        for credential in credentials:
            credential.revoked = True
            credential.token_ciphertext = None
            keys = await session.scalars(
                select(ClientKey).where(ClientKey.credential_id == credential.credential_id).with_for_update()
            )
            for key in keys:
                key.revoked = True
        return len(credentials)


async def import_legacy(entries: Sequence[LegacyCredential]) -> int:
    imported = 0
    async with session_factory()() as session, session.begin():
        for entry in entries:
            account = await session.scalar(
                select(Account).where(Account.user_id == entry.user_id).with_for_update()
            )
            if account and account.disabled:
                raise ValueError(f"legacy user is disabled: {entry.user_id}")
            if not account:
                session.add(Account(user_id=entry.user_id, created_at=datetime.now(timezone.utc)))
                await session.flush()

            credential = await session.scalar(
                select(CredentialRecord)
                .where(CredentialRecord.credential_id == entry.credential_id)
                .with_for_update()
            )
            if credential:
                if (
                    credential.user_id != entry.user_id
                    or credential.credential_type != entry.credential_type
                    or credential.rpm != entry.rpm
                    or credential.daily != entry.daily
                    or credential.revoked
                ):
                    raise ValueError(f"legacy credential conflicts with database: {entry.credential_id}")
            else:
                credential = CredentialRecord(
                    credential_id=entry.credential_id,
                    user_id=entry.user_id,
                    credential_type=entry.credential_type,
                    rpm=entry.rpm,
                    daily=entry.daily,
                    token_ciphertext=_encode_tokens(entry.tokens),
                )
                session.add(credential)
                await session.flush()

            digest = _key_hash(entry.client_key)
            key = await session.scalar(select(ClientKey).where(ClientKey.key_hash == digest).with_for_update())
            if key:
                if key.credential_id != entry.credential_id:
                    raise ValueError("legacy client key conflicts with database")
            else:
                session.add(
                    ClientKey(
                        key_hash=digest,
                        key_prefix=entry.client_key[:12],
                        credential_id=entry.credential_id,
                    )
                )
                imported += 1
    return imported


async def append_events(run_id: UUID, events: Sequence[StreamEvent], http_status: int) -> None:
    if not events:
        return
    async with session_factory()() as session, session.begin():
        run = await session.scalar(select(Run).where(Run.id == run_id).with_for_update())
        if not run or run.outcome != "open":
            return
        run.http_status = http_status
        for event in events:
            session.add(
                RunEvent(
                    run_id=run_id,
                    ordinal=event.ordinal,
                    event_type=event.event_type,
                    data=event.data,
                )
            )
            if event.complete and run.outcome == "open" and event.event_type in (
                "response.completed", "response.failed", "response.incomplete", "error"
            ):
                try:
                    payload = json.loads(event.data)
                except json.JSONDecodeError:
                    payload = None
                response = payload.get("response") if isinstance(payload, dict) else None
                if not isinstance(payload, dict) or (
                    event.event_type != "error" and not isinstance(response, dict)
                ):
                    continue
                if isinstance(response, dict):
                    run.response_json = response
                    run.usage_json = response.get("usage")
                run.outcome = {
                    "response.completed": "completed",
                    "response.failed": "failed",
                    "response.incomplete": "incomplete",
                    "error": "failed",
                }[event.event_type]
                run.finished_at = datetime.now(timezone.utc)


async def finish_transport(
    run_id: UUID,
    http_status: int | None,
    outcome: str,
    error_code: str | None = None,
) -> None:
    async with session_factory()() as session, session.begin():
        run = await session.scalar(select(Run).where(Run.id == run_id).with_for_update())
        if run and run.outcome == "open":
            run.http_status = http_status
            run.outcome = outcome
            run.error_code = error_code
            run.finished_at = datetime.now(timezone.utc)
