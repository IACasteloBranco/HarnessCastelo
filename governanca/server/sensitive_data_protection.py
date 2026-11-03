"""Google Sensitive Data Protection adapter for text inspection."""

import os
import re
from functools import lru_cache

from google.api_core.client_options import ClientOptions
from google.cloud import dlp_v2

from governanca.server.data_protection import Category, Finding, valid_document

_INFO_TYPES = {
    "BRAZIL_CPF_NUMBER": Category.CPF,
    "EMAIL_ADDRESS": Category.EMAIL,
    "PHONE_NUMBER": Category.PHONE,
    "PERSON_NAME": Category.PERSON_NAME,
    "AGE": Category.AGE,
    "GENDER": Category.GENDER,
    "ETHNIC_GROUP": Category.ETHNIC_GROUP,
    "MARITAL_STATUS": Category.MARITAL_STATUS,
    "SEXUAL_ORIENTATION": Category.SEXUAL_ORIENTATION,
    "MEDICAL_DATA": Category.MEDICAL_DATA,
    "EMPLOYMENT_STATUS": Category.EMPLOYMENT_STATUS,
    "IMMIGRATION_STATUS": Category.IMMIGRATION_STATUS,
    "RELIGIOUS_TERM": Category.RELIGIOUS_TERM,
    "POLITICAL_TERM": Category.POLITICAL_TERM,
}
_CONTEXTUAL_INFO_TYPES = tuple(name for name in _INFO_TYPES if name not in {
    "BRAZIL_CPF_NUMBER", "EMAIL_ADDRESS", "PHONE_NUMBER",
})
# shortcut: uses explicit Portuguese context cues; extend this list with approved policy vocabulary.
_CONTEXT_RULES = [{
    "info_types": [{"name": name} for name in _CONTEXTUAL_INFO_TYPES],
    "rules": [{"hotword_rule": {
        "hotword_regex": {
            "pattern": (
                r"(?i)\b(?:nome|me chamo|sou|cliente|consumidor|titular|perfil|cadastro|"
                r"paciente|colaborador|colaboradora)\b"
            )
        },
        "proximity": {"window_before": 120, "window_after": 40},
        "likelihood_adjustment": {"relative_likelihood": 1},
    }}],
}]


class InspectionUnavailable(Exception):
    """Mandatory remote inspection could not produce a trustworthy result."""


@lru_cache(maxsize=1)
def _client(location: str):
    return dlp_v2.DlpServiceAsyncClient(
        client_options=ClientOptions(api_endpoint=f"dlp.{location}.rep.googleapis.com")
    )


async def inspect_sensitive_data(text: str) -> tuple[Finding, ...]:
    project_id = os.environ.get("SENSITIVE_DATA_PROTECTION_PROJECT_ID", "").strip()
    location = os.environ.get("SENSITIVE_DATA_PROTECTION_LOCATION", "southamerica-east1").strip()
    if not project_id or "/" in project_id or not re.fullmatch(r"[a-z0-9-]+", location):
        raise InspectionUnavailable("Sensitive Data Protection is not configured")

    try:
        response = await _client(location).inspect_content(
            request={
                "parent": f"projects/{project_id}/locations/{location}",
                "inspect_config": {
                    "info_types": [{"name": name} for name in _INFO_TYPES],
                    "min_likelihood": dlp_v2.Likelihood.POSSIBLE,
                    "min_likelihood_per_info_type": [{
                        "info_type": {"name": name},
                        "min_likelihood": dlp_v2.Likelihood.LIKELY,
                    } for name in _CONTEXTUAL_INFO_TYPES],
                    "rule_set": _CONTEXT_RULES,
                    "include_quote": False,
                },
                "item": {"value": text},
            },
            timeout=8.0,
        )
    except Exception as exc:
        raise InspectionUnavailable("Sensitive Data Protection inspection failed") from exc

    try:
        findings = []
        for result in response.result.findings:
            category = _INFO_TYPES.get(result.info_type.name)
            if category is None:
                continue
            location = result.location
            ranges = location.codepoint_range if location else None
            if ranges is None:
                raise InspectionUnavailable("Sensitive Data Protection returned no text range")
            finding = Finding(category, int(ranges.start), int(ranges.end))
            if finding.start < 0 or finding.start >= finding.end or finding.end > len(text):
                raise InspectionUnavailable("Sensitive Data Protection returned an invalid text range")
            if category == Category.CPF and not valid_document(text[finding.start:finding.end], category):
                continue
            findings.append(finding)
        return tuple(findings)
    except InspectionUnavailable:
        raise
    except Exception as exc:
        raise InspectionUnavailable("Sensitive Data Protection returned an invalid response") from exc
