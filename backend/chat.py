"""Employee chat, local context, and audited governance reads."""

import json
from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import or_, select, tuple_

from backend.database import (Conversation, Employee, GovernanceAccess, Run,
                              RunEvent, session_factory)
from backend.store import (AdmittedRun, ChatRun, RequestRecord,
                           _locked_employee_credential, _record_run)


class ChatConflict(Exception):
    def __init__(self, code: str, run_id: UUID | None = None):
        self.code = code
        self.run_id = run_id


class HistoryNotFound(Exception):
    pass


async def existing_chat_run(employee_id: UUID, client_message_id: UUID) -> UUID | None:
    async with session_factory()() as session:
        return await session.scalar(select(Run.id).where(
            Run.employee_id == employee_id, Run.client_message_id == client_message_id))


def _assistant_text(response: dict | list | None) -> str | None:
    if not isinstance(response, dict):
        return None
    output = response.get("output")
    if not isinstance(output, list):
        return None
    parts = []
    for item in output:
        if not isinstance(item, dict) or item.get("type") != "message" or item.get("role") != "assistant":
            continue
        content = item.get("content")
        if not isinstance(content, list):
            continue
        for part in content:
            if not isinstance(part, dict):
                continue
            text = (part.get("text") if part.get("type") == "output_text" else
                    part.get("refusal") if part.get("type") == "refusal" else None)
            if isinstance(text, str):
                parts.append(text)
    return "\n".join(parts) if parts else None


async def admit_chat(employee_id: UUID, credential_id: str, client_message_id: UUID,
                     model: str, text: str) -> tuple[AdmittedRun, UUID, bytes]:
    async with session_factory()() as session, session.begin():
        credential = await _locked_employee_credential(session, employee_id, credential_id)
        employee = await session.scalar(select(Employee).where(Employee.id == employee_id).with_for_update())
        if employee.role != "collaborator":
            raise ChatConflict("collaborator_required")
        conversation = await session.scalar(select(Conversation).where(
            Conversation.employee_id == employee_id).with_for_update())
        if conversation is None:
            conversation = Conversation(id=uuid4(), employee_id=employee_id,
                                        created_at=datetime.now(timezone.utc))
            session.add(conversation)
            await session.flush()

        duplicate = await session.scalar(select(Run.id).where(
            Run.employee_id == employee_id, Run.client_message_id == client_message_id))
        if duplicate:
            raise ChatConflict("duplicate_message", duplicate)
        if await session.scalar(select(Run.id).where(
            Run.conversation_id == conversation.id, Run.outcome == "open")):
            raise ChatConflict("conversation_busy")

        prior = (await session.scalars(select(Run).where(
            Run.conversation_id == conversation.id, Run.outcome == "completed"
        ).order_by(Run.started_at, Run.id))).all()
        input_items = []
        for run in prior:
            answer = _assistant_text(run.response_json)
            if not run.chat_prompt or answer is None:
                raise ChatConflict("context_unavailable", run.id)
            input_items.extend((
                {"role": "user", "content": run.chat_prompt},
                {"role": "assistant", "content": answer},
            ))
        input_items.append({"role": "user", "content": text})
        payload = {"model": model, "input": input_items, "store": False, "stream": True}
        request = RequestRecord("POST", "responses", json.dumps(payload, ensure_ascii=False).encode())
        admitted = await _record_run(session, credential, request, employee_id,
                                     ChatRun(conversation.id, client_message_id, text))
        return admitted, conversation.id, request.body


def _summary(run: Run) -> dict:
    return {
        "run_id": run.id,
        "conversation_id": run.conversation_id,
        "credential_id": run.credential_id,
        "client_message_id": run.client_message_id,
        "prompt": run.chat_prompt,
        "response": run.response_json,
        "outcome": run.outcome,
        "http_status": run.http_status,
        "started_at": run.started_at,
        "finished_at": run.finished_at,
    }


async def employee_history(employee_id: UUID, before: UUID | None, limit: int) -> dict:
    async with session_factory()() as session:
        conversation = await session.scalar(select(Conversation).where(
            Conversation.employee_id == employee_id))
        if conversation is None:
            return {"conversation_id": None, "runs": []}
        query = select(Run).where(Run.conversation_id == conversation.id)
        if before:
            cursor = await session.scalar(select(Run).where(
                Run.id == before, Run.conversation_id == conversation.id))
            if cursor is None:
                raise HistoryNotFound
            query = query.where(tuple_(Run.started_at, Run.id) <
                                tuple_(cursor.started_at, cursor.id))
        runs = (await session.scalars(query.order_by(
            Run.started_at.desc(), Run.id.desc()).limit(limit))).all()
        return {"conversation_id": conversation.id, "runs": [_summary(run) for run in runs]}


async def employee_run(employee_id: UUID, run_id: UUID) -> dict:
    async with session_factory()() as session:
        run = await session.scalar(select(Run).where(
            Run.id == run_id, Run.employee_id == employee_id,
            Run.conversation_id.is_not(None)))
        if run is None:
            raise HistoryNotFound
        events = (await session.scalars(select(RunEvent).where(
            RunEvent.run_id == run_id).order_by(RunEvent.ordinal))).all()
        return {**_summary(run), "request": run.request_json,
                "events": [{"ordinal": event.ordinal, "type": event.event_type,
                            "data": event.data} for event in events]}


async def governance_runs(actor_id: UUID, before: UUID | None, limit: int) -> list[dict]:
    async with session_factory()() as session:
        actor = await session.get(Employee, actor_id)
        if actor is None or actor.disabled or actor.must_change_password or actor.role != "governance":
            raise PermissionError
        scope = or_(Run.employee_id.is_(None), Employee.organization_id == actor.organization_id)
        query = select(Run).outerjoin(Employee, Employee.id == Run.employee_id).where(scope)
        if before:
            cursor = await session.scalar(query.where(Run.id == before))
            if cursor is None:
                raise HistoryNotFound
            query = query.where(tuple_(Run.started_at, Run.id) <
                                tuple_(cursor.started_at, cursor.id))
        runs = (await session.scalars(query.order_by(
            Run.started_at.desc(), Run.id.desc()).limit(limit))).all()
        return [{"run_id": run.id, "employee_id": run.employee_id,
                 "conversation_id": run.conversation_id, "outcome": run.outcome,
                 "started_at": run.started_at} for run in runs]


async def governance_run(actor_id: UUID, run_id: UUID, action: str = "read") -> dict:
    if action not in ("read", "export"):
        raise ValueError("invalid governance action")
    async with session_factory()() as session, session.begin():
        actor = await session.get(Employee, actor_id)
        if actor is None or actor.disabled or actor.must_change_password or actor.role != "governance":
            raise PermissionError
        run = await session.get(Run, run_id)
        author = await session.get(Employee, run.employee_id) if run and run.employee_id else None
        if run is None or (run.employee_id is not None and
                           (author is None or author.organization_id != actor.organization_id)):
            raise HistoryNotFound
        events = (await session.scalars(select(RunEvent).where(
            RunEvent.run_id == run_id).order_by(RunEvent.ordinal))).all()
        session.add(GovernanceAccess(id=uuid4(), actor_employee_id=actor_id,
                                     run_id=run_id, action=action,
                                     accessed_at=datetime.now(timezone.utc)))
        await session.flush()
        return {**_summary(run), "employee_id": run.employee_id,
                "request": run.request_json, "request_body": run.request_body,
                "events": [{"ordinal": event.ordinal, "type": event.event_type,
                            "data": event.data} for event in events]}
