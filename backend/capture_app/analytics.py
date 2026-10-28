from collections import defaultdict
from datetime import datetime, timezone
import json

from fastapi import APIRouter, Depends, HTTPException, Query, Response

from .db import connect, iso, record_privacy_audit
from .security import require_analytics_operator, require_content_viewer
from .settings import Settings, get_settings


router = APIRouter(prefix="/v1/admin/analytics", tags=["analytics"])


def _normalize_period(start: datetime | None, end: datetime | None) -> tuple[datetime | None, datetime | None]:
    if start is not None and start.tzinfo is None:
        raise HTTPException(status_code=422, detail="from must include a timezone")
    if end is not None and end.tzinfo is None:
        raise HTTPException(status_code=422, detail="to must include a timezone")
    start = start.astimezone(timezone.utc) if start else None
    end = end.astimezone(timezone.utc) if end else None
    if start and end and start >= end:
        raise HTTPException(status_code=422, detail="from must be earlier than to")
    return start, end


def _interaction_filter(organization_code: str, department_code: str | None, start: datetime | None,
                        end: datetime | None) -> tuple[str, list[str]]:
    clauses: list[str] = ["EXISTS (SELECT 1 FROM public.employees AS employee "
                          "WHERE employee.code = i.employee_id AND employee.organization_id = "
                          "(SELECT id FROM public.organizations WHERE code = ?))"]
    values: list[str] = [organization_code]
    if department_code is not None:
        clauses.append("i.department_code = ?")
        values.append(department_code)
    if start is not None:
        clauses.append("i.received_at >= ?")
        values.append(iso(start))
    if end is not None:
        clauses.append("i.received_at < ?")
        values.append(iso(end))
    return (" AND ".join(clauses) or "1 = 1"), values


def _event_count(db, table: str, organization_code: str, department_code: str | None,
                 start: datetime | None, end: datetime | None) -> int:
    clauses: list[str] = ["employee_id IN (SELECT employee.code FROM public.employees AS employee "
                          "WHERE employee.organization_id = "
                          "(SELECT id FROM public.organizations WHERE code = ?))"]
    values: list[str] = [organization_code]
    if department_code is not None:
        clauses.append("department_code = ?")
        values.append(department_code)
    if start is not None:
        clauses.append("received_at >= ?")
        values.append(iso(start))
    if end is not None:
        clauses.append("received_at < ?")
        values.append(iso(end))
    where = " AND ".join(clauses) or "1 = 1"
    return db.execute(f"SELECT COUNT(*) AS count FROM {table} WHERE {where}", values).fetchone()["count"]


@router.get("/summary")
def analytics_summary(
    response: Response,
    start: datetime | None = Query(default=None, alias="from"),
    end: datetime | None = Query(default=None, alias="to"),
    scope: dict = Depends(require_analytics_operator),
    settings: Settings = Depends(get_settings),
) -> dict:
    response.headers["Cache-Control"] = "no-store"
    start, end = _normalize_period(start, end)
    where, values = _interaction_filter(scope["organization_code"], scope["department_code"], start, end)
    with connect(settings) as db:
        rows = db.execute(
            f"""SELECT
                    COALESCE(i.employee_id, 'unknown') AS employee_id,
                    MAX(COALESCE(i.attributed_person, 'Não atribuído')) AS person_name,
                    COALESCE(i.department_code, 'unknown') AS department_code,
                    MAX(COALESCE(d.department_name, i.department_code, 'Não atribuído')) AS department_name,
                    COUNT(DISTINCT i.interaction_id) AS interactions,
                    COUNT(r.response_id) AS responses,
                    SUM(CASE WHEN r.capture_status = 'complete' THEN 1 ELSE 0 END) AS complete_responses,
                    SUM(CASE WHEN r.capture_status = 'incomplete' THEN 1 ELSE 0 END) AS incomplete_responses,
                    MAX(COALESCE(r.received_at, i.received_at)) AS last_activity_at
                FROM interactions i
                LEFT JOIN responses r ON r.interaction_id = i.interaction_id
                LEFT JOIN employees e ON e.employee_id = i.employee_id
                LEFT JOIN departments d ON d.department_code = i.department_code
                    AND d.organization_id = e.organization_id
                WHERE {where}
                GROUP BY COALESCE(i.employee_id, 'unknown'), COALESCE(i.department_code, 'unknown')
                ORDER BY interactions DESC, employee_id""",
            values,
        ).fetchall()
        streams = _event_count(db, "stream_captures", scope["organization_code"], scope["department_code"], start, end)
        artifacts = _event_count(db, "artifact_metadata", scope["organization_code"], scope["department_code"], start, end)

    employees = [dict(row) for row in rows]
    departments: dict[str, dict] = defaultdict(lambda: {
        "interactions": 0,
        "responses": 0,
        "complete_responses": 0,
        "incomplete_responses": 0,
        "last_activity_at": None,
    })
    for employee in employees:
        department = departments[employee["department_code"]]
        department["department_name"] = employee["department_name"]
        for field in ("interactions", "responses", "complete_responses", "incomplete_responses"):
            department[field] += employee[field]
        if employee["last_activity_at"] and (
                department["last_activity_at"] is None or
                employee["last_activity_at"] > department["last_activity_at"]):
            department["last_activity_at"] = employee["last_activity_at"]
    by_department = [
        {"department_code": code, **totals}
        for code, totals in sorted(departments.items())
    ]
    totals = {
        "interactions": sum(item["interactions"] for item in employees),
        "responses": sum(item["responses"] for item in employees),
        "complete_responses": sum(item["complete_responses"] for item in employees),
        "incomplete_responses": sum(item["incomplete_responses"] for item in employees),
        "stream_captures": streams,
        "artifact_metadata": artifacts,
    }
    return {
        "period": {"from": iso(start) if start else None, "to": iso(end) if end else None},
        "department_scope": scope["department_code"],
        "totals": totals,
        "by_department": by_department,
        "by_employee": employees,
    }


@router.get("/interactions")
def search_interactions(
    response: Response,
    department_code: str | None = Query(default=None, min_length=1, max_length=128),
    employee_id: str | None = Query(default=None, min_length=1, max_length=128),
    start: datetime | None = Query(default=None, alias="from"),
    end: datetime | None = Query(default=None, alias="to"),
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    viewer: dict = Depends(require_content_viewer),
    settings: Settings = Depends(get_settings),
) -> dict:
    response.headers["Cache-Control"] = "no-store"
    scoped_department = viewer["department_code"]
    start, end = _normalize_period(start, end)
    clauses = ["EXISTS (SELECT 1 FROM public.employees AS employee "
        "WHERE employee.code = i.employee_id AND employee.organization_id = "
        "(SELECT id FROM public.organizations WHERE code = ?))"]
    values: list[str | int] = [viewer["organization_code"]]
    if scoped_department:
        clauses.append("i.department_code = ?")
        values.append(scoped_department)
    for column, value in (("i.department_code", department_code), ("i.employee_id", employee_id)):
        if value is not None:
            clauses.append(f"{column} = ?")
            values.append(value)
    if start is not None:
        clauses.append("i.received_at >= ?")
        values.append(iso(start))
    if end is not None:
        clauses.append("i.received_at < ?")
        values.append(iso(end))
    where = " AND ".join(clauses) or "1 = 1"
    with connect(settings) as db:
        rows = db.execute(
            f"""SELECT i.interaction_id, i.employee_id,
                       COALESCE(i.attributed_person, e.person_name, 'Não atribuído') AS person_name,
                       i.department_code, COALESCE(d.department_name, i.department_code, 'Não atribuído') AS department_name,
                       i.platform, i.status, i.received_at, i.prompt_json,
                       (SELECT r.text FROM responses r WHERE r.interaction_id = i.interaction_id
                        ORDER BY r.received_at DESC LIMIT 1) AS response_text
                FROM interactions i
                LEFT JOIN employees e ON e.employee_id = i.employee_id
                LEFT JOIN departments d ON d.department_code = i.department_code
                    AND d.organization_id = e.organization_id
                WHERE {where}
                ORDER BY i.received_at DESC, i.interaction_id
                LIMIT ? OFFSET ?""",
            [*values, limit, offset],
        ).fetchall()
        total = db.execute(f"SELECT COUNT(*) AS count FROM interactions i WHERE {where}", values).fetchone()["count"]
        record_privacy_audit(db, "content_read", viewer["actor_sub"],
                             "GET /v1/admin/analytics/interactions", len(rows))
    return {
        "items": [{
            "interaction_id": row["interaction_id"],
            "employee_id": row["employee_id"],
            "person_name": row["person_name"],
            "department_code": row["department_code"],
            "department_name": row["department_name"],
            "platform": row["platform"],
            "status": row["status"],
            "received_at": row["received_at"],
            "prompt": json.loads(row["prompt_json"]),
            "response": row["response_text"],
        } for row in rows],
        "total": total,
        "limit": limit,
        "offset": offset,
    }
