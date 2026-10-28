"""Encrypted department documents and local vector retrieval."""

import asyncio
from datetime import datetime, timezone
import hashlib
import io
import json
import re
from functools import lru_cache
from pathlib import PurePath
from uuid import UUID, uuid4

from fastembed import TextEmbedding
from pypdf import PdfReader
from sqlalchemy import select

from backend.database import (Department, DepartmentDocument, DepartmentDocumentChunk,
                              Employee, session_factory)
from backend.store import _fernet

EMBEDDING_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
MAX_DOCUMENT_BYTES = 15_000_000
MAX_EXTRACTED_CHARS = 1_000_000
MAX_PDF_PAGES = 600
ALLOWED_TYPES = {".pdf": "application/pdf", ".txt": "text/plain", ".md": "text/markdown"}


class KnowledgeError(Exception):
    pass


class KnowledgeForbidden(KnowledgeError):
    pass


class KnowledgeNotFound(KnowledgeError):
    pass


class KnowledgeInvalid(KnowledgeError):
    pass


class KnowledgeUnavailable(KnowledgeError):
    pass


@lru_cache(maxsize=1)
def _embedding_model() -> TextEmbedding:
    return TextEmbedding(model_name=EMBEDDING_MODEL)


def _embed(texts: list[str]) -> list[list[float]]:
    return [vector.tolist() for vector in _embedding_model().embed(texts)]


def _split_pages(pages: list[tuple[int | None, str]]) -> list[tuple[int | None, str]]:
    chunks = []
    for page, text in pages:
        words = re.findall(r"\S+", text)
        for start in range(0, len(words), 145):
            chunk = " ".join(words[start:start + 180]).strip()
            if chunk:
                chunks.append((page, chunk))
    return chunks


def _extract(name: str, data: bytes) -> list[tuple[int | None, str]]:
    suffix = PurePath(name).suffix.lower()
    if suffix not in ALLOWED_TYPES or not data or len(data) > MAX_DOCUMENT_BYTES:
        raise KnowledgeInvalid("Formato ou tamanho de documento não aceito.")
    if suffix == ".pdf":
        if not data.startswith(b"%PDF-"):
            raise KnowledgeInvalid("O arquivo PDF é inválido.")
        try:
            reader = PdfReader(io.BytesIO(data), strict=True)
            if len(reader.pages) > MAX_PDF_PAGES:
                raise KnowledgeInvalid("O PDF excede o limite de páginas do piloto.")
            pages = [(index + 1, page.extract_text() or "")
                     for index, page in enumerate(reader.pages)]
        except KnowledgeInvalid:
            raise
        except Exception as exc:
            raise KnowledgeInvalid("Não foi possível ler o PDF.") from exc
    else:
        try:
            pages = [(None, data.decode("utf-8-sig"))]
        except UnicodeDecodeError as exc:
            raise KnowledgeInvalid("Arquivos TXT e MD precisam estar em UTF-8.") from exc
    if sum(len(text) for _, text in pages) > MAX_EXTRACTED_CHARS:
        raise KnowledgeInvalid("O texto extraído excede o limite do piloto.")
    chunks = _split_pages(pages)
    if not chunks:
        raise KnowledgeInvalid("O documento não contém texto pesquisável; PDFs digitalizados precisam de OCR.")
    return chunks


async def _manager(session, employee_id: UUID) -> Employee:
    employee = await session.get(Employee, employee_id)
    if (employee is None or employee.disabled or employee.must_change_password
            or not (employee.role == "governance" or employee.can_govern)):
        raise KnowledgeForbidden
    return employee


def _document_meta(document: DepartmentDocument) -> dict:
    return {"id": document.id, "department_id": document.department_id,
            "name": document.name, "mime_type": document.mime_type,
            "size": document.size, "created_at": document.created_at}


async def departments_for_manager(employee_id: UUID) -> list[dict]:
    async with session_factory()() as session:
        employee = await _manager(session, employee_id)
        rows = (await session.scalars(select(Department).where(
            Department.organization_id == employee.organization_id
        ).order_by(Department.code))).all()
        return [{"id": row.id, "code": row.code, "name": row.name} for row in rows]


async def documents_for_manager(employee_id: UUID, department_id: UUID) -> list[dict]:
    async with session_factory()() as session:
        employee = await _manager(session, employee_id)
        department = await session.scalar(select(Department).where(
            Department.id == department_id,
            Department.organization_id == employee.organization_id))
        if department is None:
            raise KnowledgeNotFound
        rows = (await session.scalars(select(DepartmentDocument).where(
            DepartmentDocument.organization_id == employee.organization_id,
            DepartmentDocument.department_id == department_id
        ).order_by(DepartmentDocument.created_at.desc(), DepartmentDocument.id))).all()
        return [_document_meta(row) for row in rows]


async def upload_document(employee_id: UUID, department_id: UUID, name: str,
                          data: bytes) -> dict:
    if (PurePath(name).name != name or "\\" in name or
            any(ord(char) < 32 for char in name) or len(name) > 255):
        raise KnowledgeInvalid("Nome de arquivo inválido.")
    mime_type = ALLOWED_TYPES.get(PurePath(name).suffix.lower())
    if mime_type is None:
        raise KnowledgeInvalid("Envie PDF, TXT ou MD.")
    digest = hashlib.sha256(data).hexdigest()
    async with session_factory()() as session:
        employee = await _manager(session, employee_id)
        department = await session.scalar(select(Department.id).where(
            Department.id == department_id,
            Department.organization_id == employee.organization_id))
        if department is None:
            raise KnowledgeNotFound
        existing = await session.scalar(select(DepartmentDocument).where(
            DepartmentDocument.organization_id == employee.organization_id,
            DepartmentDocument.department_id == department_id,
            DepartmentDocument.sha256 == digest))
        if existing:
            return _document_meta(existing)

    chunks = await asyncio.to_thread(_extract, name, data)
    try:
        embeddings = await asyncio.to_thread(_embed, [text for _, text in chunks])
    except Exception as exc:
        raise KnowledgeUnavailable("O modelo local de embeddings não está disponível.") from exc
    now = datetime.now(timezone.utc)
    document = DepartmentDocument(
        id=uuid4(), organization_id=employee.organization_id, department_id=department_id,
        name=name, mime_type=mime_type, size=len(data), sha256=digest,
        ciphertext=_fernet().encrypt(data), created_by=employee_id, created_at=now)
    async with session_factory()() as session, session.begin():
        current = await _manager(session, employee_id)
        department = await session.scalar(select(Department.id).where(
            Department.id == department_id,
            Department.organization_id == current.organization_id))
        if department is None or current.organization_id != employee.organization_id:
            raise KnowledgeNotFound
        session.add(document)
        session.add_all(DepartmentDocumentChunk(
            id=uuid4(), document_id=document.id, ordinal=index, page_number=page,
            text_ciphertext=_fernet().encrypt(text.encode("utf-8")), embedding=embedding,
        ) for index, ((page, text), embedding) in enumerate(zip(chunks, embeddings)))
    return _document_meta(document)


async def delete_document(employee_id: UUID, document_id: UUID) -> None:
    async with session_factory()() as session, session.begin():
        employee = await _manager(session, employee_id)
        document = await session.scalar(select(DepartmentDocument).where(
            DepartmentDocument.id == document_id,
            DepartmentDocument.organization_id == employee.organization_id))
        if document is None:
            raise KnowledgeNotFound
        await session.delete(document)


async def document_for_employee(employee_id: UUID, document_id: UUID) -> tuple[str, str, bytes]:
    async with session_factory()() as session:
        employee = await session.get(Employee, employee_id)
        document = await session.get(DepartmentDocument, document_id)
        if (employee is None or employee.disabled or employee.must_change_password or document is None
                or document.organization_id != employee.organization_id
                or not (employee.role == "governance" or employee.can_govern
                        or document.department_id == employee.department_id)):
            raise KnowledgeNotFound
        return document.name, document.mime_type, _fernet().decrypt(document.ciphertext)


async def search_department(employee_id: UUID, query: str) -> dict:
    query = query.strip()
    if not query or len(query) > 1000:
        raise KnowledgeInvalid("Consulta inválida.")
    async with session_factory()() as session:
        employee = await session.get(Employee, employee_id)
        if (employee is None or employee.disabled or employee.must_change_password
                or employee.role != "collaborator" or employee.department_id is None):
            raise KnowledgeForbidden
        organization_id = employee.organization_id
        department_id = employee.department_id
    try:
        vector = (await asyncio.to_thread(_embed, [query]))[0]
    except Exception as exc:
        raise KnowledgeUnavailable("O modelo local de embeddings não está disponível.") from exc
    async with session_factory()() as session:
        rows = (await session.execute(
            select(DepartmentDocument, DepartmentDocumentChunk,
                   DepartmentDocumentChunk.embedding.cosine_distance(vector).label("distance"))
            .join(DepartmentDocumentChunk,
                  DepartmentDocumentChunk.document_id == DepartmentDocument.id)
            .where(DepartmentDocument.organization_id == organization_id,
                   DepartmentDocument.department_id == department_id)
            .order_by(DepartmentDocumentChunk.embedding.cosine_distance(vector))
            .limit(5)
        )).all()
    sources = []
    passages = []
    for index, (document, chunk, distance) in enumerate(rows, 1):
        if distance > 0.65:
            continue
        try:
            text = _fernet().decrypt(chunk.text_ciphertext).decode("utf-8")
        except Exception:
            continue
        source = {"id": f"F{index}", "document_id": str(document.id),
                  "title": document.name, "page": chunk.page_number,
                  "url": f"/api/chat/knowledge/documents/{document.id}/download"}
        sources.append(source)
        passages.append({"source": source["id"], "text": text})
    output = json.dumps({"sources": sources, "passages": passages}, ensure_ascii=False)
    return {"output": output, "sources": sources}
