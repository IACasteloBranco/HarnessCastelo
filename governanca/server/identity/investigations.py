"""Approval and scope for exceptional Governança reads."""

from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from sqlalchemy import select

from .database import session_factory
from .models import Employee, GovernanceInvestigation


class InvestigationDenied(Exception):
    pass


class InvestigationNotFound(Exception):
    pass


class InvestigationConflict(Exception):
    pass


def _active(actor: Employee | None) -> bool:
    return bool(actor and actor.role == "governance" and not actor.disabled
                and not actor.must_change_password)


async def request_investigation(actor_id: UUID, purpose: str, viewer_codes: list[str], employee_code: str) -> dict:
    purpose = purpose.strip()
    if len(purpose) < 20 or len(purpose) > 2000 or not viewer_codes or len(viewer_codes) > 10:
        raise ValueError("A finalidade e os responsáveis pelo acesso são obrigatórios.")
    if len(set(viewer_codes)) != len(viewer_codes):
        raise ValueError("Há responsáveis repetidos.")
    async with session_factory()() as session, session.begin():
        actor = await session.get(Employee, actor_id)
        if actor is None or not _active(actor):
            raise InvestigationDenied
        viewers = (await session.scalars(select(Employee).where(
            Employee.code.in_(viewer_codes), Employee.organization_id == actor.organization_id,
            Employee.role == "governance", Employee.disabled.is_(False)))).all()
        if len(viewers) != len(viewer_codes):
            raise ValueError("Todos os responsáveis devem pertencer à governança da empresa.")
        subject = await session.scalar(select(Employee).where(
            Employee.code == employee_code, Employee.organization_id == actor.organization_id))
        if subject is None:
            raise ValueError("Colaborador investigado não encontrado na empresa.")
        case = GovernanceInvestigation(
            id=uuid4(), organization_id=actor.organization_id, requested_by=actor.id,
            purpose=purpose, viewer_ids=[str(viewer.id) for viewer in viewers], status="pending",
            target_employee_id=subject.id,
            created_at=datetime.now(timezone.utc))
        session.add(case)
        return {"id": case.id, "status": case.status, "purpose": case.purpose,
                "viewers": viewer_codes, "employee_code": subject.code, "created_at": case.created_at}


async def list_investigations(actor_id: UUID) -> list[dict]:
    async with session_factory()() as session:
        actor = await session.get(Employee, actor_id)
        if actor is None or not _active(actor):
            raise InvestigationDenied
        cases = (await session.scalars(select(GovernanceInvestigation).where(
            GovernanceInvestigation.organization_id == actor.organization_id)
            .order_by(GovernanceInvestigation.created_at.desc()).limit(50))).all()
        codes = {str(employee.id): employee.code for employee in (await session.scalars(
            select(Employee).where(Employee.organization_id == actor.organization_id))).all()}
        return [{"id": case.id, "status": case.status, "purpose": case.purpose,
                 "requested_by": codes.get(str(case.requested_by)),
                 "viewers": [codes.get(item, item) for item in case.viewer_ids],
                 "target_employee_code": codes.get(str(case.target_employee_id)),
                 "approved_by": codes.get(str(case.approved_by)),
                 "can_approve": case.status == "pending" and case.target_employee_id is not None
                     and case.requested_by != actor.id
                     and str(actor.id) not in case.viewer_ids,
                 "can_reject": case.status == "pending" and case.requested_by != actor.id
                     and str(actor.id) not in case.viewer_ids,
                 "can_use": case.status == "approved" and case.target_employee_id is not None
                     and case.expires_at is not None
                     and case.expires_at > datetime.now(timezone.utc)
                     and str(actor.id) in case.viewer_ids,
                 "expires_at": case.expires_at,
                 "created_at": case.created_at} for case in cases]


async def decide_investigation(actor_id: UUID, case_id: UUID, approve: bool) -> dict:
    async with session_factory()() as session, session.begin():
        actor = await session.get(Employee, actor_id)
        if actor is None or not _active(actor):
            raise InvestigationDenied
        case = await session.scalar(select(GovernanceInvestigation).where(
            GovernanceInvestigation.id == case_id).with_for_update())
        if case is None or case.organization_id != actor.organization_id:
            raise InvestigationNotFound
        if case.status != "pending" or (approve and case.target_employee_id is None):
            raise InvestigationConflict
        if case.requested_by == actor.id or str(actor.id) in case.viewer_ids:
            raise InvestigationDenied
        now = datetime.now(timezone.utc)
        case.status = "approved" if approve else "rejected"
        case.approved_by = actor.id
        case.decided_at = now
        case.expires_at = now + timedelta(hours=1) if approve else None
        return {"id": case.id, "status": case.status, "expires_at": case.expires_at}


async def select_subject(actor_id: UUID, case_id: UUID, employee_code: str) -> dict:
    async with session_factory()() as session, session.begin():
        actor = await session.get(Employee, actor_id)
        case = await session.scalar(select(GovernanceInvestigation).where(
            GovernanceInvestigation.id == case_id).with_for_update())
        if actor is None or not _active(actor) or case is None or case.organization_id != actor.organization_id:
            raise InvestigationDenied
        if (case.status != "approved" or case.expires_at is None
                or case.expires_at <= datetime.now(timezone.utc)
                or str(actor.id) not in case.viewer_ids):
            raise InvestigationDenied
        subject = await session.scalar(select(Employee).where(
            Employee.code == employee_code, Employee.organization_id == actor.organization_id))
        if subject is None:
            raise InvestigationNotFound
        if case.target_employee_id is not None and case.target_employee_id != subject.id:
            raise InvestigationConflict
        case.target_employee_id = subject.id
        return {"id": case.id, "employee_code": subject.code, "expires_at": case.expires_at}


async def require_investigation(actor_id: UUID, case_id: UUID, subject_id: UUID) -> None:
    async with session_factory()() as session:
        actor = await session.get(Employee, actor_id)
        case = await session.get(GovernanceInvestigation, case_id)
        if (actor is None or not _active(actor) or case is None or case.organization_id != actor.organization_id
                or case.status != "approved" or case.expires_at is None
                or case.expires_at <= datetime.now(timezone.utc)
                or str(actor.id) not in case.viewer_ids or case.target_employee_id != subject_id):
            raise InvestigationDenied


async def require_investigation_for_code(actor_id: UUID, case_id: UUID, employee_code: str | None) -> None:
    if not employee_code:
        raise InvestigationDenied
    async with session_factory()() as session:
        subject_id = await session.scalar(select(Employee.id).where(Employee.code == employee_code))
    if subject_id is None:
        raise InvestigationDenied
    await require_investigation(actor_id, case_id, subject_id)
