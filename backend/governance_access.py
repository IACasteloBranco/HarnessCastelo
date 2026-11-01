"""Shared eligibility rule for governance access."""


def has_governance_access(role: str, can_govern: bool) -> bool:
    return role == "governance" or can_govern
