"""Governance-owned access requests for captured content."""

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from governanca.server.identity.api import _check_origin, current_employee
from governanca.server.identity.auth import EmployeeInfo
from governanca.server.identity.investigations import (
    InvestigationDenied, list_investigations, request_investigation,
)

router = APIRouter(prefix="/api/governance/investigations", tags=["investigations"])


class InvestigationRequest(BaseModel):
    purpose: str = Field(min_length=20, max_length=2000)
    employee_code: str = Field(min_length=1, max_length=128)


def _governance(employee: EmployeeInfo) -> None:
    if employee.role != "governance" or employee.must_change_password:
        raise HTTPException(403, "Governance access required")


def _error(exc: Exception) -> None:
    if isinstance(exc, ValueError):
        raise HTTPException(400, str(exc)) from exc
    raise HTTPException(403, "investigation access required") from exc


@router.post("")
async def create_investigation(body: InvestigationRequest, request: Request,
                               employee: EmployeeInfo = Depends(current_employee)):
    _check_origin(request)
    _governance(employee)
    try:
        return await request_investigation(employee.employee_id, body.purpose, body.employee_code)
    except (InvestigationDenied, ValueError) as exc:
        _error(exc)


@router.get("")
async def get_investigations(employee: EmployeeInfo = Depends(current_employee)):
    _governance(employee)
    try:
        return {"investigations": await list_investigations(employee.employee_id)}
    except InvestigationDenied as exc:
        _error(exc)
