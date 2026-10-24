"""Internal employee identity, independent of OAuth credential ownership."""

import asyncio
import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from sqlalchemy import delete, func, select

from backend.database import Department, Employee, InternalSession, Organization, session_factory

SESSION_DURATION = timedelta(hours=8)
LOCK_DURATION = timedelta(minutes=15)


@dataclass(frozen=True)
class EmployeeInfo:
    employee_id: UUID
    code: str
    organization_code: str
    department_code: str | None
    role: str
    must_change_password: bool


def _code(value: str, limit: int) -> str:
    if not value or len(value) > limit or value != value.strip() or any(ord(char) < 32 for char in value):
        raise ValueError("invalid code")
    return value


def _name(value: str) -> str:
    if not value or len(value) > 255 or value != value.strip():
        raise ValueError("invalid name")
    return value


def _password_hash(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=16384, r=8, p=1, dklen=32)
    return f"scrypt$16384$8$1${salt.hex()}${digest.hex()}"


def _password_matches(password: str, encoded: str) -> bool:
    algorithm, n, r, p, salt, expected = encoded.split("$")
    if algorithm != "scrypt":
        raise RuntimeError("unsupported password hash")
    actual = hashlib.scrypt(
        password.encode("utf-8"), salt=bytes.fromhex(salt), n=int(n), r=int(r), p=int(p), dklen=32
    )
    return hmac.compare_digest(actual, bytes.fromhex(expected))


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _temporary_password() -> str:
    return secrets.token_urlsafe(24)


async def provision_organization(code: str, name: str) -> None:
    code, name = _code(code, 64), _name(name)
    async with session_factory()() as session, session.begin():
        if await session.scalar(select(func.count()).select_from(Organization)):
            raise ValueError("MVP allows one organization")
        session.add(Organization(id=uuid4(), code=code, name=name, created_at=datetime.now(timezone.utc)))


async def provision_department(organization_code: str, code: str, name: str) -> None:
    organization_code, code, name = _code(organization_code, 64), _code(code, 64), _name(name)
    async with session_factory()() as session, session.begin():
        organization = await session.scalar(select(Organization).where(Organization.code == organization_code))
        if organization is None:
            raise ValueError("organization not found")
        if await session.scalar(
            select(Department.id).where(Department.organization_id == organization.id, Department.code == code)
        ):
            raise ValueError("department already exists")
        session.add(Department(
            id=uuid4(), organization_id=organization.id, code=code, name=name,
            created_at=datetime.now(timezone.utc),
        ))


async def provision_employee(
    organization_code: str, employee_code: str, role: str, department_code: str | None = None
) -> str:
    organization_code, employee_code = _code(organization_code, 64), _code(employee_code, 128)
    if role not in {"collaborator", "governance"}:
        raise ValueError("invalid role")
    if role == "collaborator" and not department_code:
        raise ValueError("collaborator requires a department")
    if role == "governance" and department_code:
        raise ValueError("governance account has no department")
    if department_code:
        department_code = _code(department_code, 64)
    password = _temporary_password()
    encoded = await asyncio.to_thread(_password_hash, password)
    async with session_factory()() as session, session.begin():
        organization = await session.scalar(select(Organization).where(Organization.code == organization_code))
        if organization is None:
            raise ValueError("organization not found")
        if await session.scalar(select(Employee.id).where(Employee.code == employee_code)):
            raise ValueError("employee code already exists")
        department_id = None
        if department_code:
            department_id = await session.scalar(select(Department.id).where(
                Department.organization_id == organization.id, Department.code == department_code
            ))
            if department_id is None:
                raise ValueError("department not found")
        session.add(Employee(
            id=uuid4(), organization_id=organization.id, department_id=department_id,
            code=employee_code, role=role, password_hash=encoded, must_change_password=True,
            disabled=False, failed_logins=0, created_at=datetime.now(timezone.utc),
        ))
    return password


async def reset_password(employee_code: str) -> str:
    employee_code = _code(employee_code, 128)
    password = _temporary_password()
    encoded = await asyncio.to_thread(_password_hash, password)
    async with session_factory()() as session, session.begin():
        employee = await session.scalar(select(Employee).where(Employee.code == employee_code).with_for_update())
        if employee is None or employee.disabled:
            raise ValueError("active employee not found")
        employee.password_hash = encoded
        employee.must_change_password = True
        employee.failed_logins = 0
        employee.locked_until = None
        await session.execute(delete(InternalSession).where(InternalSession.employee_id == employee.id))
    return password


async def disable_employee(employee_code: str) -> None:
    employee_code = _code(employee_code, 128)
    async with session_factory()() as session, session.begin():
        employee = await session.scalar(select(Employee).where(Employee.code == employee_code).with_for_update())
        if employee is None:
            raise ValueError("employee not found")
        employee.disabled = True
        await session.execute(delete(InternalSession).where(InternalSession.employee_id == employee.id))


async def login(employee_code: str, password: str) -> tuple[str, bool] | None:
    if not employee_code or len(employee_code) > 128 or len(password) > 1024:
        return None
    now = datetime.now(timezone.utc)
    async with session_factory()() as session, session.begin():
        employee = await session.scalar(select(Employee).where(Employee.code == employee_code).with_for_update())
        if employee is None or employee.disabled or (employee.locked_until and employee.locked_until > now):
            return None
        if not await asyncio.to_thread(_password_matches, password, employee.password_hash):
            employee.failed_logins += 1
            if employee.failed_logins >= 5:
                employee.failed_logins = 0
                employee.locked_until = now + LOCK_DURATION
            return None
        employee.failed_logins = 0
        employee.locked_until = None
        token = secrets.token_urlsafe(32)
        session.add(InternalSession(
            token_hash=_token_hash(token), employee_id=employee.id,
            created_at=now, expires_at=now + SESSION_DURATION,
        ))
        return token, employee.must_change_password


async def resolve_session(token: str | None) -> EmployeeInfo | None:
    if not token:
        return None
    now = datetime.now(timezone.utc)
    async with session_factory()() as session:
        result = await session.execute(
            select(Employee, Organization.code, Department.code)
            .join(InternalSession, InternalSession.employee_id == Employee.id)
            .join(Organization, Organization.id == Employee.organization_id)
            .outerjoin(Department, Department.id == Employee.department_id)
            .where(
                InternalSession.token_hash == _token_hash(token),
                InternalSession.expires_at > now,
                Employee.disabled.is_(False),
            )
        )
        row = result.first()
        if row is None:
            return None
        employee, organization_code, department_code = row
        return EmployeeInfo(
            employee.id, employee.code, organization_code, department_code,
            employee.role, employee.must_change_password,
        )


async def change_password(token: str, current_password: str, new_password: str) -> bool:
    if not 12 <= len(new_password) <= 1024 or len(current_password) > 1024:
        raise ValueError("new password must contain 12 to 1024 characters")
    encoded = await asyncio.to_thread(_password_hash, new_password)
    async with session_factory()() as session, session.begin():
        current_session = await session.scalar(select(InternalSession).where(
            InternalSession.token_hash == _token_hash(token), InternalSession.expires_at > datetime.now(timezone.utc)
        ))
        if current_session is None:
            return False
        employee = await session.scalar(select(Employee).where(
            Employee.id == current_session.employee_id, Employee.disabled.is_(False)
        ).with_for_update())
        if employee is None or not await asyncio.to_thread(_password_matches, current_password, employee.password_hash):
            return False
        if current_password == new_password:
            raise ValueError("new password must differ from current password")
        employee.password_hash = encoded
        employee.must_change_password = False
        await session.execute(delete(InternalSession).where(
            InternalSession.employee_id == employee.id,
            InternalSession.token_hash != current_session.token_hash,
        ))
        return True


async def logout(token: str | None) -> None:
    if token:
        async with session_factory()() as session, session.begin():
            await session.execute(delete(InternalSession).where(InternalSession.token_hash == _token_hash(token)))
