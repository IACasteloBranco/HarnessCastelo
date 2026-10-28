"""Transactional raw retention and daily governance metrics."""

from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import delete, func, or_, select, text
from sqlalchemy.dialects.postgresql import insert

from backend.database import (DailyFinding, DailyUsage, Department,
                              PromptFinding, Run, session_factory)
from backend.governance import _governance_actor

LEGACY = "legacy"
UNATTRIBUTED = "unattributed"


def _expiry(now: datetime) -> datetime:
    try:
        return now.replace(year=now.year + 1)
    except ValueError:
        return now.replace(year=now.year + 1, day=28)


def _scope(organization_id: UUID | None, department_id: UUID | None) -> tuple[str, str]:
    if organization_id is None:
        return LEGACY, LEGACY
    return str(organization_id), str(department_id) if department_id else UNATTRIBUTED


def _latency_ms(run: Run) -> int | None:
    if run.finished_at is None:
        return None
    return max(0, round((run.finished_at - run.started_at).total_seconds() * 1000))


def _is_error(run: Run) -> int:
    return int(run.outcome not in ("open", "completed") or
               (run.http_status is not None and run.http_status >= 400))


async def retain_once(now: datetime | None = None, batch_size: int = 500) -> int:
    if batch_size < 1:
        raise ValueError("batch_size must be positive")
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("now must have a timezone")
    async with session_factory()() as session, session.begin():
        await session.execute(delete(DailyUsage).where(DailyUsage.expires_at <= now))
        await session.execute(delete(DailyFinding).where(DailyFinding.expires_at <= now))
        selected = (await session.scalars(select(Run).where(
            Run.started_at < now - timedelta(days=90)
        ).order_by(Run.started_at, Run.id).limit(batch_size)
            .with_for_update(of=Run, skip_locked=True))).all()
        usage = defaultdict(lambda: [0, 0, 0, 0])
        findings = defaultdict(int)
        if selected:
            for run in selected:
                organization, department = _scope(run.organization_id, run.department_id)
                key = (organization, department, run.started_at.date())
                values = usage[key]
                values[0] += 1
                values[1] += _is_error(run)
                latency = _latency_ms(run)
                if latency is not None:
                    values[2] += latency
                    values[3] += 1
            rows = (await session.execute(select(PromptFinding.run_id, PromptFinding.category).where(
                PromptFinding.run_id.in_([run.id for run in selected])))).all()
            run_scopes = {run.id: _scope(run.organization_id, run.department_id)
                          for run in selected}
            run_days = {run.id: run.started_at.date() for run in selected}
            for run_id, category in rows:
                findings[(*run_scopes[run_id], run_days[run_id], category)] += 1
            expiry = _expiry(now)
            for (organization, department, day), values in usage.items():
                stmt = insert(DailyUsage).values(organization_code=organization,
                    department_code=department, day=day, runs=values[0], errors=values[1],
                    latency_ms=values[2], latency_samples=values[3], expires_at=expiry)
                await session.execute(stmt.on_conflict_do_update(
                    index_elements=[DailyUsage.organization_code, DailyUsage.department_code, DailyUsage.day],
                    set_={"runs": DailyUsage.runs + stmt.excluded.runs,
                          "errors": DailyUsage.errors + stmt.excluded.errors,
                          "latency_ms": DailyUsage.latency_ms + stmt.excluded.latency_ms,
                          "latency_samples": DailyUsage.latency_samples + stmt.excluded.latency_samples,
                          "expires_at": func.least(DailyUsage.expires_at, stmt.excluded.expires_at)}))
            for (organization, department, day, category), count in findings.items():
                stmt = insert(DailyFinding).values(organization_code=organization,
                    department_code=department, day=day, category=category,
                    findings=count, expires_at=expiry)
                await session.execute(stmt.on_conflict_do_update(
                    index_elements=[DailyFinding.organization_code, DailyFinding.department_code,
                                    DailyFinding.day, DailyFinding.category],
                    set_={"findings": DailyFinding.findings + stmt.excluded.findings,
                          "expires_at": func.least(DailyFinding.expires_at, stmt.excluded.expires_at)}))
            await session.execute(delete(Run).where(Run.id.in_([run.id for run in selected])))
        return len(selected)


async def retain_daily(now: datetime | None = None) -> int:
    now = now or datetime.now(timezone.utc)
    total = 0
    while count := await retain_once(now):
        total += count
    return total


async def governance_report(actor_id: UUID, start: date, end: date) -> dict:
    if end < start or (end - start).days > 455:
        raise ValueError("invalid report period")
    async with session_factory()() as session, session.begin():
        await session.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"))
        actor = await _governance_actor(session, actor_id)
        org = str(actor.organization_id)
        usage = defaultdict(lambda: [0, 0, 0, 0, 0, 0])
        findings = defaultdict(int)
        archived = (await session.scalars(select(DailyUsage).where(
            DailyUsage.organization_code.in_((org, LEGACY)),
            DailyUsage.day.between(start, end)))).all()
        for row in archived:
            current = usage[(row.department_code, row.day)]
            for index, value in enumerate((row.runs, row.errors, row.latency_ms, row.latency_samples, 0, 0)):
                current[index] += value
        archived_findings = (await session.scalars(select(DailyFinding).where(
            DailyFinding.organization_code.in_((org, LEGACY)),
            DailyFinding.day.between(start, end)))).all()
        for row in archived_findings:
            findings[(row.department_code, row.day, row.category)] += row.findings
        raw = (await session.execute(select(Run)
            .where(func.date(Run.started_at).between(start, end),
                   or_(Run.employee_id.is_(None), Run.organization_id == actor.organization_id)))).scalars().all()
        scopes = {}
        for run in raw:
            _, department = _scope(run.organization_id, run.department_id)
            scopes[run.id] = (department, run.started_at.date())
            current = usage[scopes[run.id]]
            current[0] += 1
            current[1] += _is_error(run)
            latency = _latency_ms(run)
            if latency is not None:
                current[2] += latency
                current[3] += 1
        if scopes:
            raw_findings = (await session.execute(select(PromptFinding.run_id, PromptFinding.category).where(
                PromptFinding.run_id.in_(scopes)))).all()
            for run_id, category in raw_findings:
                department, day = scopes[run_id]
                findings[(department, day, category)] += 1
        departments = {
            key: row.code
            for row in (await session.scalars(select(Department).where(
                Department.organization_id == actor.organization_id))).all()
            for key in (str(row.id), row.code)
        }
        capture_table = await session.scalar(text("SELECT to_regclass('governance_capture.interactions')"))
        if capture_table:
            captures = (await session.execute(text("""
                SELECT i.department_code,
                       (CAST(i.received_at AS TIMESTAMPTZ) AT TIME ZONE 'UTC')::date AS day,
                       i.platform, COUNT(DISTINCT i.interaction_id) AS interactions
                FROM governance_capture.interactions AS i
                JOIN public.employees AS employee ON employee.code = i.employee_id
                    AND employee.organization_id = :organization_id
                WHERE CAST(i.received_at AS TIMESTAMPTZ) >= :start_at
                  AND CAST(i.received_at AS TIMESTAMPTZ) < :end_at
                GROUP BY i.department_code,
                         (CAST(i.received_at AS TIMESTAMPTZ) AT TIME ZONE 'UTC')::date, i.platform
            """), {
                "organization_id": actor.organization_id,
                "start_at": datetime.combine(start, datetime.min.time(), timezone.utc),
                "end_at": datetime.combine(end + timedelta(days=1), datetime.min.time(), timezone.utc),
            })).all()
            for department, day, platform, interactions in captures:
                if platform not in {"chatgpt_web", "claude_web"}:
                    continue
                current = usage[(department or UNATTRIBUTED, day)]
                current[4 if platform == "chatgpt_web" else 5] += interactions
        def label(department: str) -> str:
            return departments.get(department, department if department in (LEGACY, UNATTRIBUTED) else UNATTRIBUTED)

        return {
            "usage": [{"day": day, "department": label(department),
                       "runs": values[0], "errors": values[1], "latency_ms": values[2],
                       "latency_samples": values[3], "chatgpt_interactions": values[4],
                       "claude_interactions": values[5],
                       "total_uses": values[0] + values[4] + values[5]}
                      for (department, day), values in sorted(usage.items(), key=lambda x: (x[0][1], x[0][0]))],
            "findings": [{"day": day, "department": label(department),
                          "category": category, "count": count}
                         for (department, day, category), count in sorted(
                             findings.items(), key=lambda x: (x[0][1], x[0][0], x[0][2]))],
        }
