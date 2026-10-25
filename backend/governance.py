"""Local prompt analysis, governance metadata, and durable alert delivery."""

import asyncio
import os
import re
import smtplib
import ssl
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from uuid import UUID, uuid4

from sqlalchemy import or_, select, tuple_, update

from backend.database import AlertOutbox, Employee, PromptFinding, Run, session_factory


class GovernanceNotFound(Exception):
    pass


@dataclass(frozen=True)
class Rule:
    rule_id: str
    category: str
    confidence: str
    pattern: re.Pattern[str]


RULES = (
    Rule("pem_private_key", "sensitive_data", "high", re.compile(
        r"-----BEGIN (?:RSA |EC |OPENSSH |ENCRYPTED )?PRIVATE KEY-----")),
    Rule("cpf_format", "sensitive_data", "review", re.compile(r"(?<!\d)\d{3}\.\d{3}\.\d{3}-\d{2}(?!\d)")),
    Rule("cnpj_format", "sensitive_data", "review", re.compile(r"(?<!\d)\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}(?!\d)")),
    Rule("policy_override", "policy_bypass", "review", re.compile(
        r"\b(?:ignore (?:todas? as |as |the |all )?instru[çc][õo]es anteriores|"
        r"ignore previous instructions|disregard previous instructions|"
        r"desconsidere as instru[çc][õo]es anteriores|"
        r"contorne (?:as )?(?:pol[ií]ticas|regras))\b", re.IGNORECASE)),
)


def current_prompt(payload: dict | list | None, path: str) -> str:
    if path != "responses" or not isinstance(payload, dict):
        return ""
    items = payload.get("input")
    if isinstance(items, str):
        return items[:100000]
    if not isinstance(items, list):
        return ""
    for item in reversed(items):
        if not isinstance(item, dict) or item.get("role") != "user":
            continue
        content = item.get("content")
        if isinstance(content, str):
            return content[:100000]
        if isinstance(content, list):
            return "\n".join(part["text"] for part in content
                             if isinstance(part, dict) and part.get("type") == "input_text"
                             and isinstance(part.get("text"), str))[:100000]
    return ""


def scan_prompt(text: str) -> tuple[Rule, ...]:
    return tuple(rule for rule in RULES if rule.pattern.search(text[:100000]))


async def queue_findings(session, run_id: UUID, text: str, now: datetime) -> None:
    rules = scan_prompt(text)
    if not rules:
        return
    await session.flush()
    high_confidence = []
    for rule in rules:
        finding_id = uuid4()
        session.add(PromptFinding(id=finding_id, run_id=run_id, category=rule.category,
                                  rule_id=rule.rule_id, confidence=rule.confidence,
                                  created_at=now))
        if rule.confidence == "high":
            high_confidence.append(finding_id)
    if high_confidence:
        await session.flush()
        for finding_id in high_confidence:
            session.add(AlertOutbox(id=uuid4(), finding_id=finding_id, status="pending",
                                    attempts=0, created_at=now, next_attempt_at=now))


async def _governance_actor(session, actor_id: UUID) -> Employee:
    actor = await session.get(Employee, actor_id)
    if actor is None or actor.disabled or actor.must_change_password or actor.role != "governance":
        raise PermissionError
    return actor


async def findings_for_governance(actor_id: UUID, before: UUID | None, limit: int) -> list[dict]:
    async with session_factory()() as session:
        actor = await _governance_actor(session, actor_id)
        query = (select(PromptFinding).join(Run, Run.id == PromptFinding.run_id)
                 .outerjoin(Employee, Employee.id == Run.employee_id)
                 .where(or_(Run.employee_id.is_(None), Employee.organization_id == actor.organization_id)))
        if before:
            cursor = await session.scalar(query.where(PromptFinding.id == before))
            if cursor is None:
                raise GovernanceNotFound
            query = query.where(tuple_(PromptFinding.created_at, PromptFinding.id) <
                                tuple_(cursor.created_at, cursor.id))
        rows = (await session.scalars(query.order_by(
            PromptFinding.created_at.desc(), PromptFinding.id.desc()).limit(limit))).all()
        return [{"finding_id": row.id, "run_id": row.run_id, "category": row.category,
                 "rule_id": row.rule_id, "confidence": row.confidence,
                 "created_at": row.created_at} for row in rows]


async def alerts_for_governance(actor_id: UUID, before: UUID | None, limit: int) -> list[dict]:
    async with session_factory()() as session:
        actor = await _governance_actor(session, actor_id)
        query = (select(AlertOutbox, PromptFinding).join(PromptFinding, PromptFinding.id == AlertOutbox.finding_id)
                 .join(Run, Run.id == PromptFinding.run_id)
                 .outerjoin(Employee, Employee.id == Run.employee_id)
                 .where(or_(Run.employee_id.is_(None), Employee.organization_id == actor.organization_id)))
        if before:
            cursor = await session.scalar(query.where(AlertOutbox.id == before))
            if cursor is None:
                raise GovernanceNotFound
            query = query.where(tuple_(AlertOutbox.created_at, AlertOutbox.id) <
                                tuple_(cursor.created_at, cursor.id))
        rows = (await session.execute(query.order_by(
            AlertOutbox.created_at.desc(), AlertOutbox.id.desc()).limit(limit))).all()
        return [{"alert_id": alert.id, "finding_id": finding.id, "run_id": finding.run_id,
                 "category": finding.category, "status": alert.status, "attempts": alert.attempts,
                 "next_attempt_at": alert.next_attempt_at, "sent_at": alert.sent_at,
                 "last_error_code": alert.last_error_code} for alert, finding in rows]


@dataclass(frozen=True)
class ClaimedAlert:
    alert_id: UUID
    run_id: UUID
    category: str
    attempt: int


async def _claim_due() -> list[ClaimedAlert]:
    now = datetime.now(timezone.utc)
    async with session_factory()() as session, session.begin():
        rows = (await session.execute(
            select(AlertOutbox, PromptFinding)
            .join(PromptFinding, PromptFinding.id == AlertOutbox.finding_id)
            .where(or_(
                (AlertOutbox.status == "pending") & (AlertOutbox.next_attempt_at <= now),
                (AlertOutbox.status == "leased") & (AlertOutbox.lease_until <= now),
            ))
            .order_by(AlertOutbox.next_attempt_at, AlertOutbox.id)
            .limit(1).with_for_update(of=AlertOutbox, skip_locked=True)
        )).all()
        claimed = []
        for alert, finding in rows:
            alert.status = "leased"
            alert.attempts += 1
            alert.lease_until = now + timedelta(seconds=60)
            claimed.append(ClaimedAlert(alert.id, finding.run_id, finding.category, alert.attempts))
        return claimed


async def _finish_alert(alert: ClaimedAlert, sent: bool) -> None:
    now = datetime.now(timezone.utc)
    values = ({"status": "sent", "sent_at": now, "lease_until": None, "last_error_code": None}
              if sent else {"status": "pending", "lease_until": None,
                            "next_attempt_at": now + timedelta(seconds=min(3600, 30 * 2 ** (alert.attempt - 1))),
                            "last_error_code": "smtp_error"})
    async with session_factory()() as session, session.begin():
        await session.execute(update(AlertOutbox).where(
            AlertOutbox.id == alert.alert_id, AlertOutbox.status == "leased",
            AlertOutbox.attempts == alert.attempt).values(**values))


@dataclass(frozen=True)
class SMTPConfig:
    host: str
    port: int
    sender: str
    recipient: str
    username: str | None
    password: str | None


def _smtp_config() -> SMTPConfig:
    host = os.environ.get("ALERT_SMTP_HOST", "")
    sender = os.environ.get("ALERT_SMTP_FROM", "")
    recipient = os.environ.get("GOVERNANCE_ALERT_EMAIL", "")
    username = os.environ.get("ALERT_SMTP_USERNAME")
    password = os.environ.get("ALERT_SMTP_PASSWORD")
    if not host or not sender or not recipient or bool(username) != bool(password):
        raise RuntimeError("alert SMTP host, sender, recipient and matching credentials are required")
    port = int(os.environ.get("ALERT_SMTP_PORT", "465"))
    if not 1 <= port <= 65535:
        raise RuntimeError("ALERT_SMTP_PORT must be between 1 and 65535")
    return SMTPConfig(host, port, sender, recipient, username, password)


def _send_email(alert: ClaimedAlert, config: SMTPConfig) -> None:
    message = EmailMessage()
    message["From"] = config.sender
    message["To"] = config.recipient
    message["Subject"] = f"Alerta de governança: {alert.category}"
    message.set_content(f"Categoria: {alert.category}\nReferência protegida: /api/governance/runs/{alert.run_id}\n")
    with smtplib.SMTP_SSL(config.host, config.port, timeout=20, context=ssl.create_default_context()) as smtp:
        if config.username:
            smtp.login(config.username, config.password)
        smtp.send_message(message)


async def deliver_due() -> int:
    config = _smtp_config()
    alerts = await _claim_due()
    for alert in alerts:
        try:
            await asyncio.to_thread(_send_email, alert, config)
        except Exception:
            await _finish_alert(alert, False)
        else:
            await _finish_alert(alert, True)
    return len(alerts)
