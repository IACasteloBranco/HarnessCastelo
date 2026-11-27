"""Governance-managed extension and server inspection actions."""

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import select

from governanca.server.data_protection import Action
from governanca.server.inspection import DEFAULT_SERVER_ACTIONS, policy_configuration
from governanca.server.identity.database import session_factory
from governanca.server.identity.models import GovernancePolicyRevision, Organization

EXTENSION_POLICY_VERSION = "0.1.3"

_EXTENSION_RULES = [
    {"id": "R01", "label": "Chave privada", "effect": "Bloqueia o envio."},
    {"id": "R02", "label": "Credencial ou token", "effect": "Bloqueia credenciais; retém tokens para revisão local."},
    {"id": "R03", "label": "Senha ou chave declarada", "effect": "Bloqueia valores explícitos; retém valores ambíguos para revisão local."},
    {"id": "R04", "label": "Código de recuperação", "effect": "Bloqueia conjuntos; retém um código isolado para revisão local."},
    {"id": "R05", "label": "CPF válido", "effect": "Bloqueia no destino atual; pode avisar em destino aprovado."},
    {"id": "R06", "label": "Tabela com dados identificáveis", "effect": "Impede ou retém para revisão local; pode avisar em destino aprovado."},
    {"id": "R07", "label": "Dado sensível associado a CPF", "effect": "Impede ou retém para revisão local."},
    {"id": "R08", "label": "Conteúdo extenso confidencial", "effect": "Impede o envio e pede revisão local."},
    {"id": "R09", "label": "Lote de CNPJs com faturamento", "effect": "Impede o envio e pede revisão local."},
    {"id": "LIMIT", "label": "Texto acima do limite de análise", "effect": "Impede o envio e pede revisão local."},
]
EDITABLE_RULES = tuple(f"R{number:02}" for number in range(1, 10))
EDITABLE_ACTIONS = ("ALLOW", "WARN", "REVIEW", "BLOCK")
EDITABLE_SERVER_ACTIONS = tuple(action.value for action in Action)


def _snapshot(version=0, actions=None):
    actions = actions or {rule: None for rule in EDITABLE_RULES}
    return {"version": version, "extension_engine_version": 0, "actions": actions}


async def policy_for_organization(organization_code: str) -> dict:
    async with session_factory()() as session:
        organization_id = await session.scalar(select(Organization.id).where(Organization.code == organization_code))
        revision = await session.scalar(select(GovernancePolicyRevision).where(
            GovernancePolicyRevision.organization_id == organization_id
        ).order_by(GovernancePolicyRevision.version.desc()).limit(1)) if organization_id else None
    return _snapshot(revision.version, revision.actions) | {
        "extension_engine_version": revision.extension_engine_version,
    } if revision else _snapshot()


async def server_policy_for_organization(organization_code: str) -> dict:
    async with session_factory()() as session:
        organization_id = await session.scalar(select(Organization.id).where(Organization.code == organization_code))
        revision = await session.scalar(select(GovernancePolicyRevision).where(
            GovernancePolicyRevision.organization_id == organization_id
        ).order_by(GovernancePolicyRevision.version.desc()).limit(1)) if organization_id else None
    return {
        "version": revision.version if revision else 0,
        "actions": revision.server_actions if revision and revision.server_actions else DEFAULT_SERVER_ACTIONS.copy(),
    }


async def save_policy(organization_code: str, employee_id, expected_version: int, actions: dict,
                      server_actions: dict | None = None) -> dict:
    async with session_factory()() as session, session.begin():
        organization = await session.scalar(select(Organization).where(
            Organization.code == organization_code
        ).with_for_update())
        if organization is None:
            raise ValueError("organization not found")
        current = await session.scalar(select(GovernancePolicyRevision).where(
            GovernancePolicyRevision.organization_id == organization.id
        ).order_by(GovernancePolicyRevision.version.desc()).limit(1))
        version = current.version if current else 0
        if version != expected_version:
            raise RuntimeError("policy version conflict")
        extension_engine_version = current.extension_engine_version if current else 0
        previous_actions = current.actions if current else _snapshot()["actions"]
        if actions != previous_actions:
            extension_engine_version += 1
        revision = GovernancePolicyRevision(
            id=uuid4(), organization_id=organization.id, version=version + 1,
            extension_engine_version=extension_engine_version,
            actions=actions,
            server_actions=(server_actions or (current.server_actions if current and current.server_actions
                                               else DEFAULT_SERVER_ACTIONS.copy())),
            changed_by=employee_id, created_at=datetime.now(timezone.utc),
        )
        session.add(revision)
    return _snapshot(revision.version, revision.actions) | {
        "extension_engine_version": revision.extension_engine_version,
    }


def get_policy_catalog(policy=None, server_policy=None) -> dict:
    policy = policy or _snapshot()
    server_policy = server_policy or {"version": 0, "actions": DEFAULT_SERVER_ACTIONS}
    return {
        "extension": {
            "version": EXTENSION_POLICY_VERSION,
            "policy_version": policy["version"],
            "configured_actions": policy["actions"],
            "destination": "not_approved",
            "actions": ["ALLOW", "WARN", "REVIEW", "BLOCK"],
            "warning_rules": ["R05", "R06"],
            "rules": _EXTENSION_RULES,
            "decision_counts": "local_only",
        },
        "server_inspection": policy_configuration(server_policy["actions"], server_policy["version"]),
    }
