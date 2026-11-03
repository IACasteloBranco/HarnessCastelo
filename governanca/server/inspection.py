"""Shared governance inspection and storage protection policy."""

from fastapi import HTTPException

from governanca.server.data_protection import Action, Category, Decision, inspect
from governanca.server.sensitive_data_protection import InspectionUnavailable, inspect_sensitive_data

POLICY_VERSION = "governanca-2"
_POLICY = {category: Action.MASK for category in Category}
_POLICY[Category.CNPJ] = Action.ALLOW


async def inspect_text(text: str) -> Decision:
    findings = await inspect_sensitive_data(text)
    return inspect(text, _POLICY, policy_version=POLICY_VERSION, additional_findings=findings)


async def protect_stored_text(text: str) -> str:
    try:
        decision = await inspect_text(text)
    except InspectionUnavailable as exc:
        raise HTTPException(503, "Sensitive data inspection is unavailable") from exc
    if decision.action == Action.BLOCK or decision.text is None:
        raise HTTPException(422, "Content was blocked by the storage policy")
    return decision.text
