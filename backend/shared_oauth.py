"""Operator ownership of shared OAuth credentials and employee assignments."""

import re
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import delete, select, update

from backend.database import Account, CredentialRecord, Employee, EmployeeCredential, session_factory


def _identifier(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,255}", value):
        raise ValueError("invalid OAuth identifier")
    return value


async def create_shared_credential(owner_id: str, credential_id: str, connector_code: str,
                                   rpm: int = 60, daily: int = 500) -> None:
    owner_id, credential_id = _identifier(owner_id), _identifier(credential_id)
    if rpm <= 0 or daily <= 0:
        raise ValueError("quotas must be positive")
    async with session_factory()() as session, session.begin():
        employee = await session.scalar(select(Employee).where(Employee.code == connector_code,
            Employee.disabled.is_(False)))
        if employee is None:
            raise ValueError("active connector not found")
        account = await session.scalar(select(Account).where(Account.user_id == owner_id).with_for_update())
        if account and account.disabled:
            raise ValueError("OAuth owner is disabled")
        if await session.get(CredentialRecord, credential_id):
            raise ValueError("credential already exists")
        if account is None:
            session.add(Account(user_id=owner_id, created_at=datetime.now(timezone.utc)))
            await session.flush()
        session.add(CredentialRecord(credential_id=credential_id, user_id=owner_id,
            credential_type="shared_oauth", rpm=rpm, daily=daily, token_ciphertext=None, revoked=False))
        session.add(EmployeeCredential(employee_id=employee.id, credential_id=credential_id,
            can_connect=True, assigned_at=datetime.now(timezone.utc)))


async def assign_credential(credential_id: str, employee_code: str) -> None:
    credential_id = _identifier(credential_id)
    async with session_factory()() as session, session.begin():
        credential = await session.scalar(select(CredentialRecord).where(
            CredentialRecord.credential_id == credential_id).with_for_update())
        employee = await session.scalar(select(Employee).where(
            Employee.code == employee_code, Employee.disabled.is_(False)))
        if credential is None or credential.revoked or employee is None:
            raise ValueError("active credential or employee not found")
        if await session.get(EmployeeCredential, (employee.id, credential_id)) is None:
            session.add(EmployeeCredential(employee_id=employee.id, credential_id=credential_id,
                can_connect=False, assigned_at=datetime.now(timezone.utc)))


async def set_connector(credential_id: str, employee_code: str) -> None:
    credential_id = _identifier(credential_id)
    async with session_factory()() as session, session.begin():
        credential = await session.scalar(select(CredentialRecord).where(
            CredentialRecord.credential_id == credential_id).with_for_update())
        employee = await session.scalar(select(Employee).where(
            Employee.code == employee_code, Employee.disabled.is_(False)))
        if credential is None or credential.revoked or employee is None:
            raise ValueError("active credential or employee not found")
        await session.execute(update(EmployeeCredential).where(
            EmployeeCredential.credential_id == credential_id).values(can_connect=False))
        assignment = await session.get(EmployeeCredential, (employee.id, credential_id))
        if assignment is None:
            session.add(EmployeeCredential(employee_id=employee.id, credential_id=credential_id,
                can_connect=True, assigned_at=datetime.now(timezone.utc)))
        else:
            assignment.can_connect = True


async def unassign_credential(credential_id: str, employee_code: str) -> None:
    credential_id = _identifier(credential_id)
    async with session_factory()() as session, session.begin():
        credential = await session.scalar(select(CredentialRecord).where(
            CredentialRecord.credential_id == credential_id).with_for_update())
        employee_id = await session.scalar(select(Employee.id).where(Employee.code == employee_code))
        if credential is None or employee_id is None:
            raise ValueError("credential or employee not found")
        await session.execute(delete(EmployeeCredential).where(
            EmployeeCredential.employee_id == employee_id,
            EmployeeCredential.credential_id == credential_id))


async def assigned_credentials(employee_id: UUID) -> list[dict]:
    async with session_factory()() as session:
        rows = await session.execute(select(CredentialRecord.credential_id,
            EmployeeCredential.can_connect, CredentialRecord.token_ciphertext).join(
            EmployeeCredential, EmployeeCredential.credential_id == CredentialRecord.credential_id).join(
            Account, Account.user_id == CredentialRecord.user_id).where(
            EmployeeCredential.employee_id == employee_id, CredentialRecord.revoked.is_(False),
            Account.disabled.is_(False)).order_by(CredentialRecord.credential_id))
        return [{"credential_id": credential_id, "can_connect": can_connect,
                 "connected": ciphertext is not None} for credential_id, can_connect, ciphertext in rows]
