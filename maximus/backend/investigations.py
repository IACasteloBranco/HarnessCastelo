"""Compatibility import for the shared investigation authorization contract."""

from shared.identity.investigations import (
    InvestigationConflict,
    InvestigationDenied,
    InvestigationNotFound,
    decide_investigation,
    list_investigations,
    request_investigation,
    require_investigation,
    require_investigation_for_code,
    select_subject,
)
