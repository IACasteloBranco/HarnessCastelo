from typing import Annotated

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from governanca.server.identity.auth import EmployeeInfo, resolve_session
from governanca.server.identity.access import has_governance_access
from governanca.server.identity.api import COOKIE_NAME
from .db import connect, record_privacy_audit
from .settings import Settings, get_settings

_bearer = HTTPBearer(auto_error=False)
async def require_capture_token(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    request: Request,
):
    token = credentials.credentials if credentials and credentials.scheme.lower() == "bearer" else ""
    if not token:
        token = request.cookies.get(COOKIE_NAME, "")
        if token and request.method in {"POST", "PUT", "PATCH", "DELETE"}:
            origin = f"{request.url.scheme}://{request.url.netloc}"
            if request.headers.get("Origin") != origin:
                raise HTTPException(status_code=403, detail="Invalid request origin")
    employee = await resolve_session(token)
    if employee is None:
        raise HTTPException(status_code=401, detail="Harness login required")
    if employee.must_change_password:
        raise HTTPException(status_code=403, detail="Change your Harness password before using the extension")
    return employee


def require_machine_viewer(
    employee: Annotated[EmployeeInfo, Depends(require_capture_token)],
) -> EmployeeInfo:
    return employee


def require_operator_token(
    employee: Annotated[EmployeeInfo, Depends(require_capture_token)],
) -> dict:
    if not has_governance_access(employee.role):
        raise HTTPException(status_code=403, detail="Governance access required")
    return {"organization_code": employee.organization_code, "department_code": None}

def require_content_viewer(
    request: Request,
    employee: EmployeeInfo = Depends(require_capture_token),
    settings: Settings = Depends(get_settings),
) -> dict:
    if not has_governance_access(employee.role):
        with connect(settings) as db:
            route = request.scope["route"].path
            record_privacy_audit(db, "content_read_denied", employee.code,
                                 f"{request.method} {route}", 0)
        raise HTTPException(status_code=403, detail="Governance access required")
    return {"actor_sub": employee.code, "actor_id": employee.employee_id,
            "organization_code": employee.organization_code, "department_code": None}


def require_analytics_operator(
    employee: Annotated[EmployeeInfo, Depends(require_capture_token)],
) -> dict:
    if employee.role not in {"auditor", "governance"}:
        raise HTTPException(status_code=403, detail="Audit access required")
    return {"organization_code": employee.organization_code, "department_code": None,
            "role": employee.role}


def require_governance_analytics(
    employee: Annotated[EmployeeInfo, Depends(require_capture_token)],
) -> dict:
    if employee.role != "governance":
        raise HTTPException(status_code=403, detail="Governance access required")
    return {"organization_code": employee.organization_code, "department_code": None}
