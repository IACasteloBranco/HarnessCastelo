"""Department-scoped samples and bounded, nonverbatim analysis results."""

import json
from collections import Counter
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from sqlalchemy import select, text

from maximus.backend.chat import _assistant_text
from maximus.backend.database import (AlertOutbox, Department, Employee, PromptFinding, Run,
                                      session_factory)
from maximus.backend.governance import current_prompt


CATEGORIES = {
    "procedures": "Dúvidas sobre procedimentos",
    "deadlines": "Prazos e fluxo de trabalho",
    "systems": "Sistemas e ferramentas",
    "data": "Tratamento de dados",
    "review": "Revisão e conferência",
    "training": "Necessidade de capacitação",
    "other": "Outros temas",
}


class AnalysisForbidden(Exception):
    pass


class AnalysisUnavailable(Exception):
    pass


async def require_department_access(actor_id: UUID, department_code: str) -> None:
    async with session_factory()() as session:
        actor = await session.get(Employee, actor_id)
        if (actor is None or actor.disabled or actor.must_change_password
                or actor.role not in {"auditor", "governance"}
                or not await session.scalar(select(Department.id).where(
                    Department.organization_id == actor.organization_id,
                    Department.code == department_code))):
            raise AnalysisForbidden


async def department_samples(actor_id: UUID, department_code: str, days: int) -> list[tuple[str, str]]:
    since = datetime.now(timezone.utc) - timedelta(days=days)
    async with session_factory()() as session:
        actor = await session.get(Employee, actor_id)
        if (actor is None or actor.disabled or actor.must_change_password
                or actor.role not in {"auditor", "governance"}):
            raise AnalysisForbidden
        department = await session.scalar(select(Department).where(
            Department.organization_id == actor.organization_id,
            Department.code == department_code))
        if department is None:
            raise AnalysisForbidden
        runs = (await session.execute(select(Run, Employee.code).join(
            Employee, Employee.id == Run.employee_id).where(
            Run.organization_id == actor.organization_id,
            Run.department_id == department.id,
            Run.origin.in_(("chat", "api")), Run.started_at >= since)
            .order_by(Run.started_at.desc()).limit(80))).all()
        samples = [(run.started_at, code,
                    f"Pergunta: {prompt[:1200]}\nResposta: {(_assistant_text(run.response_json) or '')[:1200]}")
                   for run, code in runs
                   if (prompt := run.chat_prompt or current_prompt(run.request_json, run.path))]
        if await session.scalar(text("SELECT to_regclass('governance_capture.interactions')")):
            captures = (await session.execute(text("""
                SELECT i.received_at, i.employee_id, i.prompt_json,
                       (SELECT r.text FROM governance_capture.responses AS r
                        WHERE r.interaction_id = i.interaction_id
                        ORDER BY r.received_at DESC LIMIT 1) AS response_text
                FROM governance_capture.interactions AS i
                JOIN public.employees AS employee ON employee.code = i.employee_id
                WHERE employee.organization_id = :organization_id
                  AND i.department_code = :department_code
                  AND CAST(i.received_at AS TIMESTAMPTZ) >= :since
                ORDER BY i.received_at DESC LIMIT 80
            """), {"organization_id": actor.organization_id,
                   "department_code": department_code, "since": since})).all()
            for received_at, author, raw_prompt, response in captures:
                prompt = json.loads(raw_prompt).get("text", "")
                timestamp = datetime.fromisoformat(received_at)
                if timestamp.tzinfo is None:
                    timestamp = timestamp.replace(tzinfo=timezone.utc)
                if isinstance(prompt, str) and prompt:
                    samples.append((timestamp, author,
                                    f"Pergunta: {prompt[:1200]}\nResposta: {(response or '')[:1200]}"))
    samples.sort(key=lambda item: item[0], reverse=True)
    per_author: Counter[str] = Counter()
    limited = []
    for sample in samples:
        if per_author[sample[1]] < 10 and len(limited) < 80:
            limited.append(sample)
            per_author[sample[1]] += 1
    samples = limited
    if len(samples) < 5:
        return []
    return [(author, content) for _, author, content in samples]


def aggregate_analysis(model_text: str, sample_count: int, department_code: str,
                       days: int) -> tuple[dict, bool]:
    try:
        payload = json.loads(model_text)
        items = payload["items"]
        if not isinstance(items, list) or len(items) != sample_count:
            raise ValueError
        indexes = set()
        counts: Counter[str] = Counter()
        relevant = 0
        incident = False
        for item in items:
            index = item["index"]
            category = item["category"]
            if (type(index) is not int or not 0 <= index < sample_count or index in indexes
                    or category not in CATEGORIES or type(item["relevant"]) is not bool
                    or type(item["possible_incident"]) is not bool):
                raise ValueError
            indexes.add(index)
            if item["relevant"]:
                relevant += 1
                counts[category] += 1
            incident |= item["possible_incident"]
    except (TypeError, KeyError, ValueError, json.JSONDecodeError) as exc:
        raise AnalysisUnavailable from exc
    themes = [{"theme": CATEGORIES[key], "interactions": count}
              for key, count in counts.most_common() if count >= 3]
    return {"department": department_code, "period_days": days,
            "sample_size": sample_count,
            "relevant_interactions": relevant if relevant >= 3 else "menos de 3",
            "themes": themes,
            "note": "Análise de até 80 interações recentes; temas com menos de três ocorrências não são exibidos."}, incident


async def notify_possible_incident(run_id: UUID) -> None:
    now = datetime.now(timezone.utc)
    async with session_factory()() as session, session.begin():
        finding_id = uuid4()
        session.add(PromptFinding(id=finding_id, run_id=run_id, category="department_review",
                                  rule_id="department_analysis_review", confidence="review",
                                  created_at=now))
        await session.flush()
        session.add(AlertOutbox(id=uuid4(), finding_id=finding_id, status="pending",
                                attempts=0, created_at=now, next_attempt_at=now))
