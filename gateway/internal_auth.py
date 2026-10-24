"""Browser endpoints for the company's internal employee session."""

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field

from backend.internal_auth import EmployeeInfo, change_password, login, logout, resolve_session

router = APIRouter(prefix="/api/auth", tags=["internal-auth"])
COOKIE_NAME = "harness_session"
COOKIE_PATH = "/api"


class LoginBody(BaseModel):
    employee_code: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=1, max_length=1024)


class PasswordBody(BaseModel):
    current_password: str = Field(min_length=1, max_length=1024)
    new_password: str = Field(min_length=12, max_length=1024)


def _check_origin(request: Request) -> None:
    allowed = f"{request.url.scheme}://{request.url.netloc}"
    if request.headers.get("Origin") != allowed:
        raise HTTPException(403, "invalid origin")


async def current_employee(request: Request) -> EmployeeInfo:
    employee = await resolve_session(request.cookies.get(COOKIE_NAME))
    if employee is None:
        raise HTTPException(401, "authentication required")
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


@router.get("/me")
async def me_route(employee: EmployeeInfo = Depends(current_employee)):
    return {
        "employee_code": employee.code,
        "organization_code": employee.organization_code,
        "department_code": employee.department_code,
        "role": employee.role,
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
