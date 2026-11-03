"""Shared eligibility rule for governance access."""


def has_governance_access(role: str) -> bool:
    return role == "governance"
