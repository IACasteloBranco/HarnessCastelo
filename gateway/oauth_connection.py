"""Browser OAuth endpoints for assigned employees."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError

from backend.internal_auth import EmployeeInfo
from backend.oauth_connection import ConnectionUnavailable, complete_connection, start_connection
from backend.shared_oauth import assigned_credentials, create_shared_credential
from gateway.internal_auth import COOKIE_NAME, _check_origin, current_employee

router = APIRouter(prefix="/api/oauth", tags=["oauth"])


class CallbackBody(BaseModel):
    callback_url: str = Field(min_length=1, max_length=4096)


class CreateCredentialBody(BaseModel):
    credential_id: str = Field(min_length=1, max_length=255, pattern=r"^[A-Za-z0-9_-]+$")


@router.get("/credentials")
async def credentials(employee: EmployeeInfo = Depends(current_employee)):
    if employee.must_change_password:
        raise HTTPException(403, "change password required")
    return await assigned_credentials(employee.employee_id)


@router.post("/credentials", status_code=201)
async def create_credential(body: CreateCredentialBody, request: Request,
                            employee: EmployeeInfo = Depends(current_employee)):
    _check_origin(request)
    if employee.must_change_password:
        raise HTTPException(403, "change password required")
    try:
        await create_shared_credential(
            f"employee-{employee.employee_id.hex}", body.credential_id, employee.code)
    except (IntegrityError, ValueError) as exc:
        raise HTTPException(409, "credential already exists") from exc
    return {"credential_id": body.credential_id, "connected": False, "can_connect": True}


@router.post("/credentials/{credential_id}/start")
async def start(credential_id: str, request: Request, employee: EmployeeInfo = Depends(current_employee)):
    _check_origin(request)
    try:
        intent_id, authorize_url = await start_connection(
            employee.employee_id, request.cookies[COOKIE_NAME], credential_id)
    except ConnectionUnavailable:
        raise HTTPException(403, "credential unavailable")
    return {"connection_id": intent_id, "authorize_url": authorize_url}


@router.post("/connections/{connection_id}/complete")
async def complete(connection_id: UUID, body: CallbackBody, request: Request,
                   employee: EmployeeInfo = Depends(current_employee)):
    _check_origin(request)
    try:
        await complete_connection(employee.employee_id, request.cookies[COOKIE_NAME],
                                  connection_id, body.callback_url)
    except ConnectionUnavailable:
        raise HTTPException(403, "connection unavailable; start again")
    return {"connected": True}
