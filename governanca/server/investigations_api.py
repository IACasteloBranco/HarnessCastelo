"""Governance-owned approvals for reading captured content."""

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from governanca.server.identity.api import _check_origin, current_employee
from governanca.server.identity.auth import EmployeeInfo
from governanca.server.identity.investigations import (
    InvestigationConflict, InvestigationDenied, InvestigationNotFound,
    decide_investigation, list_investigations, request_investigation,
)

router = APIRouter(prefix="/api/governance/investigations", tags=["investigations"])


class InvestigationRequest(BaseModel):
    purpose: str = Field(min_length=20, max_length=2000)
    viewers: list[str] = Field(min_length=1, max_length=10)
    employee_code: str = Field(min_length=1, max_length=128)


def _governance(employee: EmployeeInfo) -> None:
    if employee.role != "governance" or employee.must_change_password:
        raise HTTPException(403, "Governance access required")


def _error(exc: Exception) -> None:
    if isinstance(exc, InvestigationNotFound):
        raise HTTPException(404, "investigation not found") from exc
    if isinstance(exc, InvestigationConflict):
        raise HTTPException(409, "investigation state changed") from exc
    if isinstance(exc, ValueError):
        raise HTTPException(400, str(exc)) from exc
    raise HTTPException(403, "investigation access required") from exc


@router.post("")
async def create_investigation(body: InvestigationRequest, request: Request,
                               employee: EmployeeInfo = Depends(current_employee)):
    _check_origin(request)
    _governance(employee)
    try:
        return await request_investigation(employee.employee_id, body.purpose, body.viewers, body.employee_code)
    except (InvestigationDenied, ValueError) as exc:
        _error(exc)


@router.get("")
async def get_investigations(employee: EmployeeInfo = Depends(current_employee)):
    _governance(employee)
    try:
        return {"investigations": await list_investigations(employee.employee_id)}
    except InvestigationDenied as exc:
        _error(exc)


@router.post("/{investigation_id}/decision/{decision}")
async def decide(investigation_id: UUID, decision: Literal["approve", "reject"], request: Request,
                 employee: EmployeeInfo = Depends(current_employee)):
    _check_origin(request)
    _governance(employee)
    try:
        return await decide_investigation(employee.employee_id, investigation_id, decision == "approve")
    except (InvestigationDenied, InvestigationNotFound, InvestigationConflict) as exc:
        _error(exc)
