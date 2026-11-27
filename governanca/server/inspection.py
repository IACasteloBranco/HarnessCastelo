"""Shared governance inspection and storage protection policy."""

from fastapi import HTTPException

from governanca.server.data_protection import Action, Category, Decision, inspect
from governanca.server.sensitive_data_protection import InspectionUnavailable, inspect_sensitive_data

POLICY_VERSION = "governanca-2"
DEFAULT_SERVER_ACTIONS = {category.value: Action.MASK.value for category in Category}
DEFAULT_SERVER_ACTIONS[Category.CNPJ.value] = Action.ALLOW.value
_POLICY = {Category(name): Action(action) for name, action in DEFAULT_SERVER_ACTIONS.items()}


async def inspect_text(text: str, organization_code: str | None = None) -> Decision:
    findings = await inspect_sensitive_data(text)
    policy = _POLICY
    policy_version = POLICY_VERSION
    if organization_code:
        from governanca.server.policy_catalog import server_policy_for_organization

        configured = await server_policy_for_organization(organization_code)
        policy = {Category(name): Action(action) for name, action in configured["actions"].items()}
        if configured["version"]:
            policy_version = f"{POLICY_VERSION}:{configured['version']}"
    return inspect(text, policy, policy_version=policy_version, additional_findings=findings)


async def protect_stored_text(text: str, organization_code: str | None = None) -> str:
    try:
        decision = await inspect_text(text, organization_code)
    except InspectionUnavailable as exc:
        raise HTTPException(503, "Sensitive data inspection is unavailable") from exc
    if decision.action == Action.BLOCK or decision.text is None:
        raise HTTPException(422, "Content was blocked by the storage policy")
    return decision.text


def policy_configuration(actions=None, policy_version=0) -> dict:
    actions = actions or DEFAULT_SERVER_ACTIONS
    return {
        "version": POLICY_VERSION,
        "policy_version": policy_version,
        "categories": [
            {"name": category.value, "action": actions[category.value]}
            for category in Category
        ],
    }
