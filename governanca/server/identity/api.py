"""Browser endpoints for the company's internal employee session."""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from .auth import (EmployeeInfo, EXTENSION_SESSION_DURATION, SESSION_DURATION,
                   change_password, login, logout, provision_employee, reset_password,
                   renew_extension_session, resolve_session)
from .database import session_factory
from .models import Department, Employee

router = APIRouter(prefix="/api/auth", tags=["internal-auth"])
COOKIE_NAME = "governanca_session"
COOKIE_PATH = "/api"
EXTENSION_ORIGIN = "chrome-extension://njcbfaglhfigplenmpaojjgdbcjcfbjh"
EXTENSION_ORIGINS = {EXTENSION_ORIGIN, "chrome-extension://cnbpiejbofngbdncgppaniclkjeigboa"}


class LoginBody(BaseModel):
    employee_code: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=1, max_length=1024)


class PasswordBody(BaseModel):
    current_password: str = Field(min_length=1, max_length=1024)
    new_password: str = Field(min_length=12, max_length=1024)


class CollaboratorBody(BaseModel):
    employee_code: str = Field(min_length=1, max_length=128)
    display_name: str = Field(min_length=1, max_length=255)
    department_code: str = Field(min_length=1, max_length=64)


class CollaboratorResetBody(BaseModel):
    employee_code: str = Field(min_length=1, max_length=128)


def _check_origin(request: Request) -> None:
    allowed = f"{request.url.scheme}://{request.url.netloc}"
    if request.headers.get("Origin") != allowed:
        raise HTTPException(403, "invalid origin")


async def current_employee(request: Request) -> EmployeeInfo:
    employee = await resolve_session(request.cookies.get(COOKIE_NAME))
    if employee is None:
        raise HTTPException(401, "authentication required")
    return employee


def require_governance(employee: EmployeeInfo) -> None:
    if employee.role != "governance" or employee.must_change_password:
        raise HTTPException(403, "governance access required")


@router.get("/governance/departments")
async def governance_departments(employee: EmployeeInfo = Depends(current_employee)):
    require_governance(employee)
    async with session_factory()() as session:
        actor = await session.get(Employee, employee.employee_id)
        departments = (await session.scalars(select(Department).where(
            Department.organization_id == actor.organization_id).order_by(Department.name))).all()
    return {"departments": [{"code": item.code, "name": item.name} for item in departments]}


@router.post("/governance/accounts", status_code=201)
async def create_collaborator(body: CollaboratorBody, request: Request, response: Response,
                              employee: EmployeeInfo = Depends(current_employee)):
    _check_origin(request)
    require_governance(employee)
    response.headers["Cache-Control"] = "no-store"
    try:
        password = await provision_employee(employee.organization_code, body.employee_code,
                                            "collaborator", body.department_code, body.display_name)
    except (ValueError, IntegrityError) as exc:
        raise HTTPException(409, str(exc) if isinstance(exc, ValueError) else "employee code already exists") from exc
    return {"employee_code": body.employee_code, "temporary_password": password,
            "must_change_password": True}


@router.post("/governance/accounts/reset-password")
async def reset_collaborator_password(body: CollaboratorResetBody, request: Request, response: Response,
                                      employee: EmployeeInfo = Depends(current_employee)):
    _check_origin(request)
    require_governance(employee)
    response.headers["Cache-Control"] = "no-store"
    try:
        password = await reset_password(
            body.employee_code, organization_code=employee.organization_code, role="collaborator"
        )
    except ValueError as exc:
        raise HTTPException(404, "active collaborator not found") from exc
    return {"employee_code": body.employee_code, "temporary_password": password,
            "must_change_password": True}


async def extension_employee(request: Request) -> EmployeeInfo:
    authorization = request.headers.get("Authorization", "")
    scheme, _, token = authorization.partition(" ")
    employee = await resolve_session(token.strip() if scheme.lower() == "bearer" else None)
    if employee is None:
        raise HTTPException(401, "Harness login required")
    return employee


@router.post("/login")
async def login_route(body: LoginBody, request: Request, response: Response):
    _check_origin(request)
    result = await login(body.employee_code, body.password)
    if result is None:
        raise HTTPException(401, "invalid credentials")
    token, must_change_password = result
    response.set_cookie(
        COOKIE_NAME, token, max_age=8 * 60 * 60, path=COOKIE_PATH,
        httponly=True, secure=True, samesite="lax",
    )
    return {"must_change_password": must_change_password}


@router.post("/extension/login")
async def extension_login_route(body: LoginBody, request: Request, response: Response):
    response.headers["Cache-Control"] = "no-store"
    if request.headers.get("Origin") not in EXTENSION_ORIGINS:
        raise HTTPException(403, "invalid extension origin")
    result = await login(body.employee_code, body.password, extension=True)
    if result is None:
        raise HTTPException(401, "invalid credentials")
    token, must_change_password = result
    if must_change_password:
        await logout(token)
        return {"must_change_password": True}
    employee = await resolve_session(token)
    return {
        "access_token": token,
        "expires_at": int((datetime.now(timezone.utc) + EXTENSION_SESSION_DURATION).timestamp()),
        "employee_code": employee.code,
        "organization_code": employee.organization_code,
        "department_code": employee.department_code,
        "role": employee.role,
        "must_change_password": must_change_password,
    }


@router.get("/extension/me")
async def extension_me_route(response: Response, employee: EmployeeInfo = Depends(extension_employee)):
    response.headers["Cache-Control"] = "no-store"
    return {
        "employee_code": employee.code,
        "organization_code": employee.organization_code,
        "department_code": employee.department_code,
        "role": employee.role,
        "can_govern": employee.role == "governance",
        "must_change_password": employee.must_change_password,
    }


@router.post("/extension/renew")
async def extension_renew_route(request: Request, response: Response):
    response.headers["Cache-Control"] = "no-store"
    if request.headers.get("Origin") not in EXTENSION_ORIGINS:
        raise HTTPException(403, "invalid extension origin")
    scheme, _, token = request.headers.get("Authorization", "").partition(" ")
    expires_at = await renew_extension_session(token.strip()) if scheme.lower() == "bearer" else None
    if expires_at is None:
        raise HTTPException(401, "Harness login required")
    return {"expires_at": int(expires_at.timestamp())}


@router.post("/extension/logout", status_code=204)
async def extension_logout_route(request: Request, response: Response):
    response.headers["Cache-Control"] = "no-store"
    authorization = request.headers.get("Authorization", "")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() == "bearer" and token.strip():
        await logout(token.strip())


@router.get("/me")
async def me_route(employee: EmployeeInfo = Depends(current_employee)):
    return {
        "employee_code": employee.code,
        "organization_code": employee.organization_code,
        "department_code": employee.department_code,
        "role": employee.role,
        "can_govern": employee.role == "governance",
        "must_change_password": employee.must_change_password,
    }


@router.post("/change-password")
async def change_password_route(
    body: PasswordBody, request: Request, employee: EmployeeInfo = Depends(current_employee)
):
    _check_origin(request)
    try:
        changed = await change_password(
            request.cookies[COOKIE_NAME], body.current_password, body.new_password
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    if not changed:
        raise HTTPException(401, "invalid credentials")
    return {"must_change_password": False}


@router.post("/logout", status_code=204)
async def logout_route(request: Request, response: Response):
    _check_origin(request)
    await logout(request.cookies.get(COOKIE_NAME))
    response.delete_cookie(COOKIE_NAME, path=COOKIE_PATH, secure=True, httponly=True, samesite="lax")
