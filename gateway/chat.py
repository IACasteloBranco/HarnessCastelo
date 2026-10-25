"""Session-bound chat and history APIs."""

from datetime import date
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, ConfigDict

from backend.chat import (ChatConflict, HistoryNotFound, admit_chat, existing_chat_run,
                          employee_history, employee_run, governance_run, governance_runs)
from backend.internal_auth import EmployeeInfo
from backend.governance import (GovernanceNotFound, alerts_for_governance,
                                findings_for_governance)
from backend.store import QuotaExceeded, UnavailableAssignment, credential_for_employee
from backend.retention import governance_report
from gateway.auth_store import get_valid_token
from gateway.forwarder import forward
from gateway.internal_auth import _check_origin, current_employee

router = APIRouter(prefix="/api/chat", tags=["chat"])
governance_router = APIRouter(prefix="/api/governance", tags=["governance"])


class MessageBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    client_message_id: UUID
    credential_id: str = Field(min_length=1, max_length=255)
    model: str = Field(min_length=1, max_length=255)
    text: str = Field(min_length=1, max_length=100000)


def _ready(employee: EmployeeInfo, role: str) -> None:
    if employee.must_change_password or employee.role != role:
        raise HTTPException(403, "account unavailable")


@router.post("/messages")
async def send_message(body: MessageBody, request: Request,
                       employee: EmployeeInfo = Depends(current_employee)):
    _check_origin(request)
    _ready(employee, "collaborator")
    if not body.text.strip():
        raise HTTPException(422, "message is empty")
    duplicate = await existing_chat_run(employee.employee_id, body.client_message_id)
    if duplicate:
        raise HTTPException(409, {"code": "duplicate_message", "run_id": str(duplicate)})
    try:
        credential = await credential_for_employee(employee.employee_id, body.credential_id)
    except UnavailableAssignment:
        raise HTTPException(403, "credential unavailable")
    try:
        token = await get_valid_token(credential)
    except PermissionError:
        duplicate = await existing_chat_run(employee.employee_id, body.client_message_id)
        if duplicate:
            raise HTTPException(409, {"code": "duplicate_message", "run_id": str(duplicate)})
        return JSONResponse(status_code=409, content={
            "code": "reconnect_required", "client_message_id": str(body.client_message_id),
        })
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code in (400, 401, 403):
            duplicate = await existing_chat_run(employee.employee_id, body.client_message_id)
            if duplicate:
                raise HTTPException(409, {"code": "duplicate_message", "run_id": str(duplicate)})
            return JSONResponse(status_code=409, content={
                "code": "reconnect_required", "client_message_id": str(body.client_message_id),
            })
        raise HTTPException(502, "OAuth refresh failed") from exc
    except httpx.HTTPError as exc:
        raise HTTPException(502, "OAuth service unavailable") from exc

    try:
        admitted, conversation_id, request_body = await admit_chat(
            employee.employee_id, body.credential_id, body.client_message_id,
            body.model, body.text,
        )
    except UnavailableAssignment:
        raise HTTPException(403, "credential unavailable")
    except QuotaExceeded as exc:
        raise HTTPException(429, "rate limit exceeded" if exc.kind == "rate" else "daily quota exceeded")
    except ChatConflict as exc:
        raise HTTPException(409, {"code": exc.code, "run_id": str(exc.run_id) if exc.run_id else None})

    response = await forward(request, "responses", admitted, request_body,
                             browser_session=True, access_token=token)
    response.headers["X-Conversation-ID"] = str(conversation_id)
    response.headers["X-Run-ID"] = str(admitted.run_id)
    return response


@router.get("/history")
async def history(before: UUID | None = None, limit: int = Query(50, ge=1, le=50),
                  employee: EmployeeInfo = Depends(current_employee)):
    _ready(employee, "collaborator")
    try:
        return await employee_history(employee.employee_id, before, limit)
    except HistoryNotFound:
        raise HTTPException(404, "history cursor not found")


@router.get("/runs/{run_id}")
async def run_detail(run_id: UUID, employee: EmployeeInfo = Depends(current_employee)):
    _ready(employee, "collaborator")
    try:
        return await employee_run(employee.employee_id, run_id)
    except HistoryNotFound:
        raise HTTPException(404, "run not found")


@governance_router.get("/runs")
async def governance_history(before: UUID | None = None, limit: int = Query(50, ge=1, le=50),
                             employee: EmployeeInfo = Depends(current_employee)):
    _ready(employee, "governance")
    try:
        return {"runs": await governance_runs(employee.employee_id, before, limit)}
    except HistoryNotFound:
        raise HTTPException(404, "history cursor not found")


@governance_router.get("/runs/{run_id}")
async def governance_detail(run_id: UUID, employee: EmployeeInfo = Depends(current_employee)):
    _ready(employee, "governance")
    try:
        return await governance_run(employee.employee_id, run_id)
    except HistoryNotFound:
        raise HTTPException(404, "run not found")


@governance_router.get("/runs/{run_id}/export")
async def governance_export(run_id: UUID, employee: EmployeeInfo = Depends(current_employee)):
    _ready(employee, "governance")
    try:
        data = await governance_run(employee.employee_id, run_id, action="export")
    except HistoryNotFound:
        raise HTTPException(404, "run not found")
    return JSONResponse(content=jsonable_encoder(data), headers={
        "Content-Disposition": f'attachment; filename="run-{run_id}.json"',
    })


@governance_router.get("/findings")
async def governance_findings(before: UUID | None = None, limit: int = Query(50, ge=1, le=50),
                              employee: EmployeeInfo = Depends(current_employee)):
    _ready(employee, "governance")
    try:
        return {"findings": await findings_for_governance(employee.employee_id, before, limit)}
    except GovernanceNotFound:
        raise HTTPException(404, "finding cursor not found")


@governance_router.get("/alerts")
async def governance_alerts(before: UUID | None = None, limit: int = Query(50, ge=1, le=50),
                            employee: EmployeeInfo = Depends(current_employee)):
    _ready(employee, "governance")
    try:
        return {"alerts": await alerts_for_governance(employee.employee_id, before, limit)}
    except GovernanceNotFound:
        raise HTTPException(404, "alert cursor not found")


@governance_router.get("/reports/daily")
async def governance_daily_report(start: date, end: date,
                                  employee: EmployeeInfo = Depends(current_employee)):
    _ready(employee, "governance")
    try:
        return await governance_report(employee.employee_id, start, end)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@governance_router.get("/reports/daily/export")
async def governance_daily_export(start: date, end: date,
                                  employee: EmployeeInfo = Depends(current_employee)):
    _ready(employee, "governance")
    try:
        data = await governance_report(employee.employee_id, start, end)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return JSONResponse(content=jsonable_encoder(data), headers={
        "Content-Disposition": f'attachment; filename="governance-{start}-{end}.json"',
    })
