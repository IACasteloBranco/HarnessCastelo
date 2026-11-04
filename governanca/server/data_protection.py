"""Local text inspection. No logging, persistence, or network access."""

import re
from collections import Counter
from dataclasses import dataclass
from enum import Enum
from typing import Mapping


class Category(str, Enum):
    CPF = "CPF"
    CNPJ = "CNPJ"
    EMAIL = "EMAIL"
    PHONE = "PHONE"
    PERSON_NAME = "PERSON_NAME"
    AGE = "AGE"
    GENDER = "GENDER"
    ETHNIC_GROUP = "ETHNIC_GROUP"
    MARITAL_STATUS = "MARITAL_STATUS"
    SEXUAL_ORIENTATION = "SEXUAL_ORIENTATION"
    MEDICAL_DATA = "MEDICAL_DATA"
    EMPLOYMENT_STATUS = "EMPLOYMENT_STATUS"
    IMMIGRATION_STATUS = "IMMIGRATION_STATUS"
    RELIGIOUS_TERM = "RELIGIOUS_TERM"
    POLITICAL_TERM = "POLITICAL_TERM"


class Action(str, Enum):
    ALLOW = "allow"
    MASK = "mask"
    BLOCK = "block"


@dataclass(frozen=True)
class Finding:
    category: Category
    start: int
    end: int


@dataclass(frozen=True)
class Decision:
    action: Action
    text: str | None
    findings: tuple[Finding, ...]
    policy_version: str


_PATTERNS = {
    Category.EMAIL: re.compile(r"(?<![\w.+-])[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?)+(?![\w-])"),
    Category.CNPJ: re.compile(r"(?<!\w)(?:[A-Za-z0-9]{12}[0-9]{2}|[A-Za-z0-9]{2}\.[A-Za-z0-9]{3}\.[A-Za-z0-9]{3}/[A-Za-z0-9]{4}-[0-9]{2})(?!\w)"),
    Category.CPF: re.compile(r"(?<!\w)(?:[0-9]{11}|[0-9]{3}\.[0-9]{3}\.[0-9]{3}-[0-9]{2})(?!\w)"),
    Category.PHONE: re.compile(r"(?<![\w+])(?:\+55[ .-]?)?(?:\([1-9][0-9]\)[ .-]?|[1-9][0-9][ .-]?)(?:9[0-9]{4}|[2-5][0-9]{3})[ .-]?[0-9]{4}(?!\w)"),
}
_DDDS = set("11 12 13 14 15 16 17 18 19 21 22 24 27 28 31 32 33 34 35 37 38 41 42 43 44 45 46 47 48 49 51 53 54 55 61 62 63 64 65 66 67 68 69 71 73 74 75 77 79 81 82 83 84 85 86 87 88 89 91 92 93 94 95 96 97 98 99".split())


def valid_document(value: str, category: Category) -> bool:
    value = re.sub(r"[./-]", "", value).upper()
    if len(set(value)) == 1:
        return False
    digits = [ord(char) - 48 for char in value]
    for length in (len(value) - 2, len(value) - 1):
        weights = (range(length + 1, 1, -1) if category == Category.CPF
                   else reversed([2 + i % 8 for i in range(length)]))
        remainder = sum(digit * weight for digit, weight in zip(digits[:length], weights)) % 11
        if digits[length] != (0 if remainder < 2 else 11 - remainder):
            return False
    return True


def detect(text: str) -> tuple[Finding, ...]:
    """Return all candidates, including overlaps, in Python character offsets [start, end)."""
    findings = []
    for category, pattern in _PATTERNS.items():
        for match in pattern.finditer(text):
            value = match.group()
            if category in (Category.CPF, Category.CNPJ) and not valid_document(value, category):
                continue
            if category == Category.PHONE:
                national = re.sub(r"\D", "", value)
                if value.startswith("+55"):
                    national = national[2:]
                if national[:2] not in _DDDS:
                    continue
            findings.append(Finding(category, match.start(), match.end()))
    return tuple(sorted(findings, key=lambda item: (item.start, item.end, item.category.value)))


def inspect(text: str, policy: Mapping[Category, Action], *, policy_version: str,
            additional_findings: tuple[Finding, ...] = ()) -> Decision:
    """Apply a complete explicit policy. A blocked decision never returns sendable text."""
    if set(policy) != set(Category) or any(not isinstance(action, Action) for action in policy.values()):
        raise ValueError("Policy must specify an Action for every Category")
    if not policy_version.strip():
        raise ValueError("Policy version is required")
    if any(not isinstance(item, Finding) or not isinstance(item.category, Category)
           or item.start < 0 or item.start >= item.end
           or item.end > len(text) for item in additional_findings):
        raise ValueError("Additional findings must be valid text ranges")
    findings = tuple(sorted(set(detect(text) + additional_findings),
                            key=lambda item: (item.start, item.end, item.category.value)))
    if any(policy[item.category] == Action.BLOCK for item in findings):
        return Decision(Action.BLOCK, None, findings, policy_version)
    # Prefer complete email/document spans over phone-shaped substrings.
    priority = {category: index for index, category in enumerate(_PATTERNS)}
    for category in Category:
        priority.setdefault(category, len(priority))
    preserved = [item for item in findings if policy[item.category] == Action.ALLOW]
    selected = []
    for item in sorted(findings, key=lambda item: (priority[item.category], item.start)):
        if policy[item.category] == Action.MASK and not any(
            item.start < other.end and other.start < item.end for other in (*preserved, *selected)
        ):
            selected.append(item)
    parts = []
    cursor = 0
    counts = Counter()
    for item in sorted(selected, key=lambda item: item.start):
        counts[item.category] += 1
        marker = f"[{item.category.value}_{counts[item.category]}]"
        while marker in text:
            counts[item.category] += 1
            marker = f"[{item.category.value}_{counts[item.category]}]"
        parts.extend((text[cursor:item.start], marker))
        cursor = item.end
    parts.append(text[cursor:])
    return Decision(Action.MASK if selected else Action.ALLOW, "".join(parts), findings, policy_version)
