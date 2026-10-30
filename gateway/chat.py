"""Session-bound chat and history APIs."""

from datetime import date
import asyncio
import base64
import binascii
import hashlib
import json
import re
from pathlib import PurePath
from typing import Literal
from urllib.parse import quote
from uuid import UUID, uuid4

import httpx
import av
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field, ConfigDict, model_validator

from backend.artifacts import InvalidArtifact, build_artifact, preview_table
from backend.transcription import AudioTooLong, transcribe_local
from backend.chat import (ChatConflict, HistoryNotFound, admit_chat, artifact_source, claim_title_prompt,
                          add_context_note, context_notes, delete_context_note,
                          update_context_note,
                          update_user_profile, user_profile,
                          create_project, delete_conversation, delete_project, employee_conversations,
                          employee_projects, existing_chat_run, move_conversation, rename_project,
                          employee_artifact, employee_attachment, employee_history, employee_run, governance_run, governance_runs,
                          release_title_prompt, rename_conversation, save_suggested_title,
                          save_artifact, suggested_title_response)
from backend.internal_auth import EmployeeInfo
from backend.knowledge import (KnowledgeError, departments_for_manager, documents_for_manager,
                               upload_document, delete_document, document_for_employee,
                               search_department)
from backend.governance import (GovernanceNotFound, alerts_for_governance,
                                findings_for_governance)
from backend.store import (QuotaExceeded, RequestRecord, UnavailableAssignment,
                           admit_employee, credential_for_employee)
from backend.retention import governance_report
from gateway.auth_store import get_valid_token
from gateway.forwarder import forward
from gateway.internal_auth import _check_origin, current_employee
from gateway.profile_learning import process_profile_learning

router = APIRouter(prefix="/api/chat", tags=["chat"])
governance_router = APIRouter(prefix="/api/governance", tags=["governance"])
transcription_slots = asyncio.Semaphore(1)


FILE_TYPES = {
    ".pdf": "application/pdf", ".txt": "text/plain", ".md": "text/markdown",
    ".csv": "text/csv", ".tsv": "text/tab-separated-values",
    ".doc": "application/msword", ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".rtf": "application/rtf", ".odt": "application/vnd.oasis.opendocument.text",
    ".ppt": "application/vnd.ms-powerpoint", ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".xls": "application/vnd.ms-excel", ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".json": "application/json", ".xml": "application/xml", ".html": "text/html",
    ".py": "text/plain", ".js": "text/plain", ".ts": "text/plain",
    ".css": "text/plain", ".sql": "text/plain", ".yaml": "text/plain", ".yml": "text/plain",
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
    ".webp": "image/webp", ".gif": "image/gif",
}


class Attachment(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=255)
    data: str = Field(min_length=1, max_length=70_000_000)


class MessageBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    client_message_id: UUID
    credential_id: str = Field(min_length=1, max_length=255)
    model: str = Field(min_length=1, max_length=255)
    text: str = Field(max_length=100000)
    attachments: list[Attachment] = Field(default_factory=list, max_length=5)
    conversation_id: UUID | None = None
    new_conversation: bool = False
    project_id: UUID | None = None

    @model_validator(mode="after")
    def check_content(self):
        if not self.text.strip() and not self.attachments:
            raise ValueError("message is empty")
        return self


def _files(attachments: list[Attachment]) -> tuple[list[dict], list[tuple[dict, bytes]]]:
    content, files = [], []
    total = 0
    for attachment in attachments:
        name = attachment.name
        if PurePath(name).name != name or "\\" in name or any(ord(char) < 32 for char in name):
            raise HTTPException(422, "invalid filename")
        mime = FILE_TYPES.get(PurePath(name).suffix.lower())
        if not mime:
            raise HTTPException(422, "unsupported file type")
        try:
            data = base64.b64decode(attachment.data, validate=True)
        except (ValueError, binascii.Error):
            raise HTTPException(422, "invalid file data")
        total += len(data)
        if not data or total > 50_000_000:
            raise HTTPException(413, "attachments exceed 50 MB")
        if mime == "application/pdf" and not data.startswith(b"%PDF-"):
            raise HTTPException(422, "invalid PDF")
        if mime.startswith("image/") and not (
            (mime == "image/png" and data.startswith(b"\x89PNG\r\n\x1a\n")) or
            (mime == "image/jpeg" and data.startswith(b"\xff\xd8\xff")) or
            (mime == "image/gif" and data.startswith((b"GIF87a", b"GIF89a"))) or
            (mime == "image/webp" and data.startswith(b"RIFF") and data[8:12] == b"WEBP")
        ):
            raise HTTPException(422, "invalid image")
        encoded = f"data:{mime};base64,{attachment.data}"
        content.append({"type": "input_image", "image_url": encoded} if mime.startswith("image/") else
                       {"type": "input_file", "filename": name, "file_data": encoded})
        files.append(({"id": str(uuid4()), "name": name, "mime_type": mime,
                       "size": len(data), "sha256": hashlib.sha256(data).hexdigest()}, data))
    return content, files


class TitleBody(BaseModel):
    title: str = Field(min_length=1, max_length=60)


class ProjectBody(BaseModel):
    name: str = Field(min_length=1, max_length=80)


class ProjectAssignmentBody(BaseModel):
    project_id: UUID | None


class ContextBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scope: Literal["profile", "project", "conversation"]
    target_id: UUID | None = None
    kind: Literal["instruction", "memory"]
    content: str = Field(min_length=1, max_length=1000)


class ContextEditBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    content: str = Field(min_length=1, max_length=1000)


class ProfileBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(max_length=3000)


class ArtifactBody(BaseModel):
    format: Literal["csv", "xlsx", "pdf"]


class KnowledgeUploadBody(BaseModel):
    department_id: UUID
    name: str = Field(min_length=1, max_length=255)
    data: str = Field(min_length=1, max_length=21_000_000)


def _knowledge_error(exc: KnowledgeError):
    status = 403 if exc.__class__.__name__ == "KnowledgeForbidden" else 404 if exc.__class__.__name__ == "KnowledgeNotFound" else 422 if exc.__class__.__name__ == "KnowledgeInvalid" else 503
    raise HTTPException(status, str(exc) or "Knowledge library unavailable") from exc


def _ready(employee: EmployeeInfo, role: str) -> None:
    allowed = employee.role == role or (role == "governance" and employee.can_govern) or (role == "collaborator" and employee.role == "governance")
    if employee.must_change_password or not allowed:
        raise HTTPException(403, "account unavailable")


@router.post("/transcriptions")
async def transcribe_audio(request: Request, employee: EmployeeInfo = Depends(current_employee)):
    _check_origin(request)
    _ready(employee, "collaborator")
    if PurePath(request.headers.get("X-Audio-Filename", "")).suffix.lower() not in (
        ".mp3", ".mp4", ".mpeg", ".mpga", ".m4a", ".wav", ".webm", ".ogg", ".opus"
    ):
        raise HTTPException(422, "Formato de áudio não aceito.")
    chunks = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > 25_000_000:
            raise HTTPException(413, "O áudio deve ter até 25 MB.")
        chunks.append(chunk)
    data = b"".join(chunks)
    if not data:
        raise HTTPException(422, "O arquivo de áudio está vazio.")
    try:
        async with transcription_slots:
            text = await asyncio.to_thread(transcribe_local, data)
    except AudioTooLong as exc:
        raise HTTPException(413, str(exc)) from exc
    except av.InvalidDataError as exc:
        raise HTTPException(422, "Não foi possível ler o áudio.") from exc
    except Exception as exc:
        raise HTTPException(503, "A transcrição local está indisponível.") from exc
    if not text:
        raise HTTPException(422, "Nenhuma fala foi detectada no áudio.")
    return {"text": text}


@governance_router.get("/knowledge/departments")
async def knowledge_departments(employee: EmployeeInfo = Depends(current_employee)):
    _ready(employee, "governance")
    try:
        return {"departments": await departments_for_manager(employee.employee_id)}
    except KnowledgeError as exc:
        _knowledge_error(exc)


@governance_router.get("/knowledge/departments/{department_id}/documents")
async def knowledge_documents(department_id: UUID, employee: EmployeeInfo = Depends(current_employee)):
    _ready(employee, "governance")
    try:
        return {"documents": await documents_for_manager(employee.employee_id, department_id)}
    except KnowledgeError as exc:
        _knowledge_error(exc)


@governance_router.post("/knowledge/documents")
async def knowledge_upload(body: KnowledgeUploadBody, request: Request,
                           employee: EmployeeInfo = Depends(current_employee)):
    _check_origin(request)
    _ready(employee, "governance")
    try:
        data = base64.b64decode(body.data, validate=True)
        return await upload_document(employee.employee_id, body.department_id, body.name, data)
    except (ValueError, binascii.Error):
        raise HTTPException(422, "invalid file data")
    except KnowledgeError as exc:
        _knowledge_error(exc)


@governance_router.delete("/knowledge/documents/{document_id}", status_code=204)
async def knowledge_delete(document_id: UUID, request: Request,
                           employee: EmployeeInfo = Depends(current_employee)):
    _check_origin(request)
    _ready(employee, "governance")
    try:
        await delete_document(employee.employee_id, document_id)
    except KnowledgeError as exc:
        _knowledge_error(exc)


@router.get("/knowledge/documents/{document_id}/download")
async def knowledge_download(document_id: UUID, employee: EmployeeInfo = Depends(current_employee)):
    _ready(employee, "collaborator")
    try:
        name, mime_type, data = await document_for_employee(employee.employee_id, document_id)
    except KnowledgeError as exc:
        _knowledge_error(exc)
    return Response(data, media_type=mime_type,
                    headers={"Content-Disposition": f'attachment; filename="{quote(name)}"',
                             "X-Content-Type-Options": "nosniff"})


@router.post("/messages")
async def send_message(body: MessageBody, request: Request,
                       employee: EmployeeInfo = Depends(current_employee)):
    _check_origin(request)
    _ready(employee, "collaborator")
    file_content, files = _files(body.attachments)
    duplicate = await existing_chat_run(employee.employee_id, body.client_message_id)
    if duplicate:
        raise HTTPException(409, {"code": "duplicate_message", "run_id": str(duplicate)})
    try:
        credential = await credential_for_employee(employee.employee_id, body.credential_id)
    except UnavailableAssignment:
        raise HTTPException(403, "credential unavailable")
    try:
        token = await get_valid_token(credential)
    except PermissionError:
        duplicate = await existing_chat_run(employee.employee_id, body.client_message_id)
        if duplicate:
            raise HTTPException(409, {"code": "duplicate_message", "run_id": str(duplicate)})
        return JSONResponse(status_code=409, content={
            "code": "reconnect_required", "client_message_id": str(body.client_message_id),
        })
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code in (400, 401, 403):
            duplicate = await existing_chat_run(employee.employee_id, body.client_message_id)
            if duplicate:
                raise HTTPException(409, {"code": "duplicate_message", "run_id": str(duplicate)})
            return JSONResponse(status_code=409, content={
                "code": "reconnect_required", "client_message_id": str(body.client_message_id),
            })
        raise HTTPException(502, "OAuth refresh failed") from exc
    except httpx.HTTPError as exc:
        raise HTTPException(502, "OAuth service unavailable") from exc

    try:
        admitted, conversation_id, request_body = await admit_chat(
            employee.employee_id, body.credential_id, body.client_message_id,
            body.model, body.text or "Analise os arquivos anexados.", body.conversation_id, body.new_conversation,
            file_content, files, body.project_id,
        )
    except UnavailableAssignment:
        raise HTTPException(403, "credential unavailable")
    except QuotaExceeded as exc:
        raise HTTPException(429, "rate limit exceeded" if exc.kind == "rate" else "daily quota exceeded")
    except ChatConflict as exc:
        raise HTTPException(409, {"code": exc.code, "run_id": str(exc.run_id) if exc.run_id else None})

    response = await forward(request, "responses", admitted, request_body,
                             browser_session=True, access_token=token,
                             knowledge_search=lambda query: search_department(employee.employee_id, query))
    response.headers["X-Conversation-ID"] = str(conversation_id)
    response.headers["X-Run-ID"] = str(admitted.run_id)
    return response


@router.get("/history")
async def history(before: UUID | None = None, conversation_id: UUID | None = None,
                  limit: int = Query(50, ge=1, le=50),
                  employee: EmployeeInfo = Depends(current_employee)):
    _ready(employee, "collaborator")
    try:
        return await employee_history(employee.employee_id, before, limit, conversation_id)
    except HistoryNotFound:
        raise HTTPException(404, "history cursor not found")


@router.get("/attachments/{attachment_id}")
async def download_attachment(attachment_id: UUID,
                              employee: EmployeeInfo = Depends(current_employee)):
    _ready(employee, "collaborator")
    try:
        name, mime, data = await employee_attachment(employee.employee_id, attachment_id)
    except HistoryNotFound:
        raise HTTPException(404, "attachment not found")
    return Response(data, media_type=mime, headers={
        "Content-Disposition": f"attachment; filename=download; filename*=UTF-8''{quote(name)}",
        "Cache-Control": "private, no-store",
        "X-Content-Type-Options": "nosniff",
    })


@router.get("/attachments/{attachment_id}/preview")
async def preview_attachment(attachment_id: UUID,
                             employee: EmployeeInfo = Depends(current_employee)):
    _ready(employee, "collaborator")
    try:
        name, mime, data = await employee_attachment(employee.employee_id, attachment_id)
    except HistoryNotFound:
        raise HTTPException(404, "attachment not found")
    suffix = PurePath(name).suffix.lower()
    if mime == "application/pdf" or mime.startswith("image/"):
        return Response(data, media_type=mime, headers={
            "Content-Disposition": "inline", "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
        })
    try:
        if suffix in (".csv", ".tsv", ".xlsx"):
            return JSONResponse(preview_table(suffix[1:], data), headers={"Cache-Control": "private, no-store"})
        if mime.startswith("text/") or suffix in (".json", ".xml"):
            return JSONResponse({"text": data[:200_000].decode("utf-8-sig", errors="replace"),
                                 "truncated": len(data) > 200_000}, headers={"Cache-Control": "private, no-store"})
    except Exception as exc:
        raise HTTPException(422, "Não foi possível visualizar este arquivo.") from exc
    raise HTTPException(415, "Prévia indisponível para este formato.")


@router.get("/projects")
async def projects(employee: EmployeeInfo = Depends(current_employee)):
    _ready(employee, "collaborator")
    return {"projects": await employee_projects(employee.employee_id)}


@router.get("/context")
async def get_context(scope: Literal["profile", "project", "conversation"],
                      response: Response, target_id: UUID | None = None,
                      employee: EmployeeInfo = Depends(current_employee)):
    _ready(employee, "collaborator")
    response.headers["Cache-Control"] = "private, no-store"
    try:
        return {"notes": await context_notes(employee.employee_id, scope, target_id)}
    except HistoryNotFound:
        raise HTTPException(404, "context scope not found")


@router.get("/profile")
async def get_profile(response: Response, employee: EmployeeInfo = Depends(current_employee)):
    _ready(employee, "collaborator")
    response.headers["Cache-Control"] = "private, no-store"
    return await user_profile(employee.employee_id)


@router.patch("/profile")
async def edit_profile(body: ProfileBody, request: Request,
                       employee: EmployeeInfo = Depends(current_employee)):
    _check_origin(request)
    _ready(employee, "collaborator")
    return await update_user_profile(employee.employee_id, body.text.strip())


@router.post("/context", status_code=201)
async def create_context(body: ContextBody, request: Request,
                         employee: EmployeeInfo = Depends(current_employee)):
    _check_origin(request)
    _ready(employee, "collaborator")
    content = body.content.strip()
    if not content:
        raise HTTPException(422, "empty context note")
    try:
        return await add_context_note(employee.employee_id, body.scope, body.target_id,
                                      body.kind, content)
    except HistoryNotFound:
        raise HTTPException(404, "context scope not found")
    except ChatConflict:
        raise HTTPException(409, "Limite de 30 notas neste contexto.")


@router.patch("/context/{note_id}")
async def edit_context(note_id: UUID, body: ContextEditBody, request: Request,
                       employee: EmployeeInfo = Depends(current_employee)):
    _check_origin(request)
    _ready(employee, "collaborator")
    content = body.content.strip()
    if not content:
        raise HTTPException(422, "empty context note")
    try:
        return await update_context_note(employee.employee_id, note_id, content)
    except HistoryNotFound:
        raise HTTPException(404, "context note not found")


@router.delete("/context/{note_id}", status_code=204)
async def remove_context(note_id: UUID, request: Request,
                         employee: EmployeeInfo = Depends(current_employee)):
    _check_origin(request)
    _ready(employee, "collaborator")
    try:
        await delete_context_note(employee.employee_id, note_id)
    except HistoryNotFound:
        raise HTTPException(404, "context note not found")


@router.post("/projects", status_code=201)
async def add_project(body: ProjectBody, request: Request,
                      employee: EmployeeInfo = Depends(current_employee)):
    _check_origin(request)
    _ready(employee, "collaborator")
    name = body.name.strip()
    if not name:
        raise HTTPException(422, "O nome do projeto está vazio.")
    return await create_project(employee.employee_id, name)


@router.patch("/projects/{project_id}")
async def update_project(project_id: UUID, body: ProjectBody, request: Request,
                         employee: EmployeeInfo = Depends(current_employee)):
    _check_origin(request)
    _ready(employee, "collaborator")
    name = body.name.strip()
    if not name:
        raise HTTPException(422, "O nome do projeto está vazio.")
    try:
        return await rename_project(employee.employee_id, project_id, name)
    except HistoryNotFound:
        raise HTTPException(404, "project not found")


@router.delete("/projects/{project_id}", status_code=204)
async def remove_project(project_id: UUID, request: Request,
                         employee: EmployeeInfo = Depends(current_employee)):
    _check_origin(request)
    _ready(employee, "collaborator")
    try:
        await delete_project(employee.employee_id, project_id)
    except HistoryNotFound:
        raise HTTPException(404, "project not found")
    except ChatConflict:
        raise HTTPException(409, "Aguarde a resposta terminar antes de excluir o projeto.")


@router.get("/conversations")
async def conversations(q: str = Query("", max_length=200), before: UUID | None = None,
                        limit: int = Query(50, ge=1, le=50),
                        project_id: UUID | None = None, unassigned: bool = False,
                        employee: EmployeeInfo = Depends(current_employee)):
    _ready(employee, "collaborator")
    try:
        return await employee_conversations(employee.employee_id, q, before, limit,
                                            project_id, unassigned)
    except HistoryNotFound:
        raise HTTPException(404, "conversation or project not found")


@router.patch("/conversations/{conversation_id}/project")
async def assign_project(conversation_id: UUID, body: ProjectAssignmentBody, request: Request,
                         employee: EmployeeInfo = Depends(current_employee)):
    _check_origin(request)
    _ready(employee, "collaborator")
    try:
        return {"project_id": await move_conversation(employee.employee_id, conversation_id, body.project_id)}
    except HistoryNotFound:
        raise HTTPException(404, "conversation or project not found")
    except ChatConflict:
        raise HTTPException(409, "Aguarde a resposta terminar antes de mover a conversa.")


@router.patch("/conversations/{conversation_id}")
async def update_title(conversation_id: UUID, body: TitleBody, request: Request,
                       employee: EmployeeInfo = Depends(current_employee)):
    _check_origin(request)
    _ready(employee, "collaborator")
    title = body.title.strip()
    if not title:
        raise HTTPException(422, "title is empty")
    try:
        return {"title": await rename_conversation(employee.employee_id, title, conversation_id)}
    except HistoryNotFound:
        raise HTTPException(404, "conversation not found")


@router.delete("/conversations/{conversation_id}", status_code=204)
async def remove_conversation(conversation_id: UUID, request: Request,
                              employee: EmployeeInfo = Depends(current_employee)):
    _check_origin(request)
    _ready(employee, "collaborator")
    try:
        await delete_conversation(employee.employee_id, conversation_id)
    except HistoryNotFound:
        raise HTTPException(404, "conversation not found")
    except ChatConflict:
        raise HTTPException(409, "Aguarde a resposta terminar antes de excluir.")


@router.post("/conversations/{conversation_id}/suggest-title")
async def suggest_title(conversation_id: UUID, request: Request,
                        employee: EmployeeInfo = Depends(current_employee)):
    _check_origin(request)
    _ready(employee, "collaborator")
    try:
        source = await claim_title_prompt(employee.employee_id, conversation_id)
    except HistoryNotFound:
        raise HTTPException(404, "conversation not found")
    if not source:
        return {"title": None}
    prompt, answer, credential_id = source
    payload = {"model": "gpt-6-luna", "input": [
        {"role": "system", "content": "Crie um título em português de até 6 palavras para esta conversa. Responda somente com o título, sem aspas."},
        {"role": "user", "content": f"Pergunta: {prompt[:2000]}\nResposta: {answer[:2000]}"},
    ], "stream": True, "store": False}
    body = json.dumps(payload, ensure_ascii=False).encode()
    try:
        admitted = await admit_employee(employee.employee_id, credential_id,
                                        RequestRecord("POST", "responses", body))
    except UnavailableAssignment:
        await release_title_prompt(employee.employee_id, conversation_id)
        raise HTTPException(403, "credential unavailable")
    except QuotaExceeded as exc:
        await release_title_prompt(employee.employee_id, conversation_id)
        raise HTTPException(429, "rate limit exceeded" if exc.kind == "rate" else "daily quota exceeded")
    try:
        response = await forward(request, "responses", admitted, body, browser_session=True)
        if response.status_code >= 400:
            raise RuntimeError("title generation unavailable")
        async for _ in response.body_iterator:
            pass
        generated = await suggested_title_response(admitted.run_id)
        title = generated.strip().strip('"“”').splitlines()[0][:60].strip() if generated else ""
        if not title:
            raise RuntimeError("title generation unavailable")
    except Exception as exc:
        await release_title_prompt(employee.employee_id, conversation_id)
        raise HTTPException(502, "title generation unavailable") from exc
    return {"title": await save_suggested_title(employee.employee_id, conversation_id, title)}


@router.post("/runs/{run_id}/learn")
async def learn_context(run_id: UUID, request: Request,
                        employee: EmployeeInfo = Depends(current_employee)):
    _check_origin(request)
    _ready(employee, "collaborator")
    try:
        updated = await process_profile_learning(employee.employee_id, run_id)
    except HistoryNotFound:
        raise HTTPException(404, "run not found")
    return {"updated": updated}


@router.patch("/conversation")
async def update_conversation_title(body: TitleBody, request: Request,
                                    employee: EmployeeInfo = Depends(current_employee)):
    _check_origin(request)
    _ready(employee, "collaborator")
    title = body.title.strip()
    if not title:
        raise HTTPException(422, "title is empty")
    try:
        return {"title": await rename_conversation(employee.employee_id, title)}
    except HistoryNotFound:
        raise HTTPException(404, "conversation not found")


@router.get("/runs/{run_id}")
async def run_detail(run_id: UUID, employee: EmployeeInfo = Depends(current_employee)):
    _ready(employee, "collaborator")
    try:
        return await employee_run(employee.employee_id, run_id)
    except HistoryNotFound:
        raise HTTPException(404, "run not found")


@router.post("/runs/{run_id}/artifacts")
async def create_artifact(run_id: UUID, body: ArtifactBody, request: Request,
                          employee: EmployeeInfo = Depends(current_employee)):
    _check_origin(request)
    _ready(employee, "collaborator")
    try:
        prompt, answer, credential_id, existing = await artifact_source(
            employee.employee_id, run_id, body.format)
    except HistoryNotFound:
        raise HTTPException(404, "run not found")
    except ChatConflict:
        raise HTTPException(409, "A resposta ainda não está disponível.")
    if existing:
        return existing
    content = answer
    if body.format in ("csv", "xlsx"):
        payload = {"model": "gpt-6-luna", "input": [
            {"role": "system", "content": (
                "Crie uma tabela a partir do pedido e da resposta abaixo. Responda SOMENTE com JSON "
                "no formato {\"columns\":[\"Coluna\"],\"rows\":[[\"valor\"]]}. "
                "Não invente dados ausentes. Se não houver dados estruturados, organize os pontos da "
                "resposta em colunas úteis. Limite a 50 colunas e 10000 linhas.")},
            {"role": "user", "content": f"Pedido: {prompt}\n\nResposta: {answer}"},
        ], "stream": True, "store": False}
        upstream_body = json.dumps(payload, ensure_ascii=False).encode()
        try:
            admitted = await admit_employee(employee.employee_id, credential_id,
                                            RequestRecord("POST", "responses", upstream_body))
        except UnavailableAssignment:
            raise HTTPException(403, "credential unavailable")
        except QuotaExceeded as exc:
            raise HTTPException(429, "rate limit exceeded" if exc.kind == "rate" else "daily quota exceeded")
        try:
            response = await forward(request, "responses", admitted, upstream_body, browser_session=True)
            if response.status_code >= 400:
                raise RuntimeError("artifact generation unavailable")
            async for _ in response.body_iterator:
                pass
            content = await suggested_title_response(admitted.run_id)
        except Exception as exc:
            raise HTTPException(502, "Não foi possível gerar a planilha.") from exc
    try:
        data = build_artifact(body.format, content or "")
        return await save_artifact(employee.employee_id, run_id, body.format, data)
    except InvalidArtifact as exc:
        raise HTTPException(422, str(exc)) from exc
    except HistoryNotFound:
        raise HTTPException(404, "run not found")


@router.get("/artifacts/{artifact_id}")
async def download_artifact(artifact_id: UUID,
                            employee: EmployeeInfo = Depends(current_employee)):
    _ready(employee, "collaborator")
    try:
        name, mime, data = await employee_artifact(employee.employee_id, artifact_id)
    except HistoryNotFound:
        raise HTTPException(404, "artifact not found")
    return Response(data, media_type=mime, headers={
        "Content-Disposition": f"attachment; filename=download; filename*=UTF-8''{quote(name)}",
        "Cache-Control": "private, no-store",
        "X-Content-Type-Options": "nosniff",
    })


@router.get("/artifacts/{artifact_id}/preview")
async def preview_generated_artifact(artifact_id: UUID,
                                     employee: EmployeeInfo = Depends(current_employee)):
    _ready(employee, "collaborator")
    try:
        name, mime, data = await employee_artifact(employee.employee_id, artifact_id)
    except HistoryNotFound:
        raise HTTPException(404, "artifact not found")
    if mime == "application/pdf":
        return Response(data, media_type="application/pdf", headers={
            "Content-Disposition": "inline",
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
        })
    return JSONResponse(preview_table("csv" if mime.startswith("text/csv") else "xlsx", data),
                        headers={"Cache-Control": "private, no-store"})


@governance_router.get("/runs")
async def governance_history(before: UUID | None = None, limit: int = Query(50, ge=1, le=50),
                             employee: EmployeeInfo = Depends(current_employee)):
    _ready(employee, "governance")
    try:
        return {"runs": await governance_runs(employee.employee_id, before, limit)}
    except HistoryNotFound:
        raise HTTPException(404, "history cursor not found")


@governance_router.get("/runs/{run_id}")
async def governance_detail(run_id: UUID, employee: EmployeeInfo = Depends(current_employee)):
    _ready(employee, "governance")
    try:
        return await governance_run(employee.employee_id, run_id)
    except HistoryNotFound:
        raise HTTPException(404, "run not found")


@governance_router.get("/runs/{run_id}/export")
async def governance_export(run_id: UUID, employee: EmployeeInfo = Depends(current_employee)):
    _ready(employee, "governance")
    try:
        data = await governance_run(employee.employee_id, run_id, action="export")
    except HistoryNotFound:
        raise HTTPException(404, "run not found")
    return JSONResponse(content=jsonable_encoder(data), headers={
        "Content-Disposition": f'attachment; filename="run-{run_id}.json"',
    })


@governance_router.get("/findings")
async def governance_findings(before: UUID | None = None, limit: int = Query(50, ge=1, le=50),
                              employee: EmployeeInfo = Depends(current_employee)):
    _ready(employee, "governance")
    try:
        return {"findings": await findings_for_governance(employee.employee_id, before, limit)}
    except GovernanceNotFound:
        raise HTTPException(404, "finding cursor not found")


@governance_router.get("/alerts")
async def governance_alerts(before: UUID | None = None, limit: int = Query(50, ge=1, le=50),
                            employee: EmployeeInfo = Depends(current_employee)):
    _ready(employee, "governance")
    try:
        return {"alerts": await alerts_for_governance(employee.employee_id, before, limit)}
    except GovernanceNotFound:
        raise HTTPException(404, "alert cursor not found")


@governance_router.get("/reports/daily")
async def governance_daily_report(start: date, end: date,
                                  employee: EmployeeInfo = Depends(current_employee)):
    _ready(employee, "governance")
    try:
        return await governance_report(employee.employee_id, start, end)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@governance_router.get("/reports/daily/export")
async def governance_daily_export(start: date, end: date,
                                  employee: EmployeeInfo = Depends(current_employee)):
    _ready(employee, "governance")
    try:
        data = await governance_report(employee.employee_id, start, end)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return JSONResponse(content=jsonable_encoder(data), headers={
        "Content-Disposition": f'attachment; filename="governance-{start}-{end}.json"',
    })
