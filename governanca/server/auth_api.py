"""Governança-only sensitive-text inspection route plus shared identity APIs."""

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field

from governanca.server.identity.api import (
    EXTENSION_ORIGIN,
    EXTENSION_ORIGINS,
    EmployeeInfo,
    extension_employee,
    router as identity_router,
)
from governanca.server.data_protection import Action
from governanca.server.inspection import inspect_text
from governanca.server.policy_catalog import EXTENSION_POLICY_VERSION, policy_for_organization
from governanca.server.sensitive_data_protection import InspectionUnavailable

router = APIRouter()
router.include_router(identity_router)

inspection_router = APIRouter(prefix="/api/auth", tags=["extension-inspection"])


class SensitiveTextBody(BaseModel):
    text: str = Field(max_length=100_000)
    policy_engine_version: str | None = Field(default=None, max_length=32)


@inspection_router.post("/extension/inspect")
async def extension_inspect_route(
    body: SensitiveTextBody,
    request: Request,
    response: Response,
    employee: EmployeeInfo = Depends(extension_employee),
):
    response.headers["Cache-Control"] = "no-store"
    if request.headers.get("Origin") not in EXTENSION_ORIGINS:
        raise HTTPException(403, "invalid extension origin")
    extension_policy = await policy_for_organization(employee.organization_code)
    if extension_policy.get("extension_engine_version", 0) and body.policy_engine_version != EXTENSION_POLICY_VERSION:
        raise HTTPException(426, "Update the extension to apply the active governance policy")
    try:
        decision = await inspect_text(body.text, employee.organization_code)
    except InspectionUnavailable as exc:
        raise HTTPException(503, "Sensitive data inspection is unavailable") from exc
    return {
        "action": decision.action.value,
        "text": decision.text if decision.action == Action.MASK else None,
        "requires_confirmation": decision.action == Action.MASK,
        "policy_version": decision.policy_version,
        "categories": sorted({finding.category.value for finding in decision.findings}),
        "extension_policy": {"version": extension_policy["version"], "actions": extension_policy["actions"]},
    }


router.include_router(inspection_router)
