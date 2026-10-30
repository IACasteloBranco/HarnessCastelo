"""Local preview of the frontend with simulated accounts and API data."""

import base64
import json
import mimetypes
import secrets
import time
from datetime import date, datetime, timezone
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, urlparse
from uuid import uuid4

from backend.artifacts import MIME, build_artifact, preview_table


PUBLIC = Path(__file__).resolve().parent / "public"
SESSIONS = {}
RUNS = {}
CONVERSATIONS = {}
PROJECTS = {}
CONTEXT = {}
PROFILES = {}
ATTACHMENTS = {}
ARTIFACTS = {}
SAMPLE_RUN_ID = "11111111-1111-4111-8111-111111111111"
SAMPLE_RUN = {
    "run_id": SAMPLE_RUN_ID,
    "outcome": "completed",
    "started_at": "2026-10-25T10:00:00Z",
    "source": "Chat do Maximus",
    "duration_ms": 2400,
    "prompt": "Como consultar o relatório mensal?",
    "response": {"output": [{"type": "message", "role": "assistant", "content": [
        {"type": "output_text", "text": "Esta é uma resposta simulada para a prévia da interface."}
    ]}]},
}


class PreviewHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(PUBLIC), **kwargs)

    def log_message(self, format, *args):
        pass

    def _session(self):
        cookies = SimpleCookie()
        try:
            cookies.load(self.headers.get("Cookie", ""))
        except Exception:
            return None
        token = cookies.get("preview_session")
        return SESSIONS.get(token.value) if token else None

    def _json(self, status, data, headers=None):
        body = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(body)

    def _body(self):
        length = int(self.headers.get("Content-Length", "0"))
        if length > 70_000_000:
            raise ValueError("body too large")
        return json.loads(self.rfile.read(length))

    def _authorized(self, role=None):
        session = self._session()
        if not session:
            self._json(HTTPStatus.UNAUTHORIZED, {"detail": "authentication required"})
            return None
        if role and session["role"] != role and not (role == "collaborator" and session["role"] == "governance"):
            self._json(HTTPStatus.FORBIDDEN, {"detail": "account unavailable"})
            return None
        return session

    def do_GET(self):
        path = urlparse(self.path).path
        if path in ("/", "/index.html"):
            page = (PUBLIC / "index.html").read_text(encoding="utf-8")
            page = page.replace("<body>", '<body><div class="preview-banner" role="note">Prévia local com dados simulados. Nenhuma mensagem é enviada à IA.</div>', 1)
            encoded = page.encode()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(encoded)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(encoded)
            return
        if not path.startswith("/api/"):
            return super().do_GET()
        if path == "/api/auth/me":
            session = self._authorized()
            if session:
                self._json(HTTPStatus.OK, {"employee_code": session["code"], "role": session["role"], "can_govern": session["role"] == "governance", "must_change_password": False})
            return
        if path == "/api/oauth/credentials":
            if self._authorized("collaborator"):
                self._json(HTTPStatus.OK, [{"credential_id": "CONTA-DEMO", "connected": True, "can_connect": True}])
            return
        if path == "/api/chat/history":
            session = self._authorized("collaborator")
            if session:
                requested = parse_qs(urlparse(self.path).query).get("conversation_id", [None])[0]
                items = CONVERSATIONS.get(session["code"], [])
                conversation = next((item for item in items if item["id"] == requested), None) if requested else next(iter(reversed(items)), None)
                runs = [run for run in RUNS.get(session["code"], []) if run.get("conversation_id") == conversation["id"]] if conversation else []
                self._json(HTTPStatus.OK, {"conversation_id": conversation["id"] if conversation else None,
                                            "project_id": conversation.get("project_id") if conversation else None,
                                            "title": conversation["title"] if conversation else None,
                                            "runs": list(reversed(runs))})
            return
        if path == "/api/chat/projects":
            session = self._authorized("collaborator")
            if session:
                self._json(HTTPStatus.OK, {"projects": PROJECTS.get(session["code"], [])})
            return
        if path == "/api/chat/context":
            session = self._authorized("collaborator")
            if session:
                query = parse_qs(urlparse(self.path).query)
                scope = query.get("scope", ["profile"])[0]
                target = query.get("target_id", [None])[0]
                self._json(HTTPStatus.OK, {"notes": [item for item in CONTEXT.get(session["code"], [])
                    if item["scope"] == scope and item["target_id"] == target]})
            return
        if path == "/api/chat/profile":
            session = self._authorized("collaborator")
            if session:
                self._json(HTTPStatus.OK, {"text": PROFILES.get(session["code"], ""), "version": 0,
                                            "updated_at": None, "source": "manual",
                                            "source_run_id": None, "quarantined": False,
                                            "learning_status": None})
            return
        if path == "/api/chat/conversations":
            session = self._authorized("collaborator")
            if session:
                term = parse_qs(urlparse(self.path).query).get("q", [""])[0].casefold()
                project_id = parse_qs(urlparse(self.path).query).get("project_id", [None])[0]
                unassigned = parse_qs(urlparse(self.path).query).get("unassigned", ["false"])[0] == "true"
                rows = []
                for item in reversed(CONVERSATIONS.get(session["code"], [])):
                    if not term and (project_id and item.get("project_id") != project_id or
                                     unassigned and item.get("project_id")):
                        continue
                    runs = [run for run in RUNS.get(session["code"], []) if run.get("conversation_id") == item["id"]]
                    match = next((run for run in runs if term in run["prompt"].casefold()), None) if term else None
                    if not term or term in (item["title"] or "").casefold() or match:
                        rows.append({**item, "snippet": match["prompt"] if match else None,
                                     "match_run_id": match["run_id"] if match else None})
                self._json(HTTPStatus.OK, {"conversations": rows, "next_before": None})
            return
        if path.startswith("/api/chat/attachments/"):
            session = self._authorized("collaborator")
            if session:
                is_preview = path.endswith("/preview")
                attachment_id = path.split("/")[-2] if is_preview else path.rsplit("/", 1)[-1]
                attachment = ATTACHMENTS.get(attachment_id)
                active = {item["id"] for item in CONVERSATIONS.get(session["code"], [])}
                if not attachment or attachment[0] != session["code"] or attachment[1] not in active:
                    self._json(HTTPStatus.NOT_FOUND, {"detail": "attachment not found"})
                    return
                _, _, name, mime, data = attachment
                if is_preview and name.lower().endswith((".csv", ".tsv", ".xlsx")):
                    self._json(HTTPStatus.OK, preview_table(name.rsplit(".", 1)[-1].lower(), data))
                    return
                if is_preview and (mime.startswith("text/") or name.lower().endswith((".json", ".xml"))):
                    self._json(HTTPStatus.OK, {"text": data[:200_000].decode("utf-8-sig", errors="replace"),
                                                "truncated": len(data) > 200_000})
                    return
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", mime)
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Content-Disposition", "inline" if is_preview else
                                 f"attachment; filename=download; filename*=UTF-8''{quote(name)}")
                self.send_header("Cache-Control", "private, no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.end_headers()
                self.wfile.write(data)
            return
        if path.startswith("/api/chat/artifacts/"):
            session = self._authorized("collaborator")
            if session:
                is_preview = path.endswith("/preview")
                artifact_id = path.split("/")[-2] if is_preview else path.rsplit("/", 1)[-1]
                artifact = ARTIFACTS.get(artifact_id)
                active = {item["id"] for item in CONVERSATIONS.get(session["code"], [])}
                if not artifact or artifact[0] != session["code"] or artifact[1] not in active:
                    self._json(HTTPStatus.NOT_FOUND, {"detail": "artifact not found"})
                    return
                _, _, name, mime, data = artifact
                if is_preview and mime != "application/pdf":
                    self._json(HTTPStatus.OK, preview_table("csv" if name.endswith(".csv") else "xlsx", data))
                    return
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", mime)
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Content-Disposition", "inline" if is_preview else
                                 f"attachment; filename=download; filename*=UTF-8''{quote(name)}")
                self.send_header("Cache-Control", "private, no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.end_headers()
                self.wfile.write(data)
            return
        if path.startswith("/api/chat/runs/"):
            session = self._authorized("collaborator")
            if session:
                active = {item["id"] for item in CONVERSATIONS.get(session["code"], [])}
                run = next((item for item in RUNS.get(session["code"], []) if item["run_id"] == path.rsplit("/", 1)[-1] and item.get("conversation_id") in active), None)
                self._json(HTTPStatus.OK if run else HTTPStatus.NOT_FOUND, run or {"detail": "run not found"})
            return
        if path == "/api/capture/v1/admin/machines/assignment-requests":
            if self._authorized("governance"):
                self._json(HTTPStatus.OK, {"items": []})
            return
        if path.startswith("/api/governance/"):
            if not self._authorized("governance"):
                return
            if path in ("/api/governance/reports/daily", "/api/governance/reports/daily/export"):
                report = {"usage": [{"day": date.today().isoformat(), "department": "CONTABIL", "runs": 12, "errors": 1, "latency_ms": 18000, "latency_samples": 10}], "findings": [{"day": date.today().isoformat(), "department": "CONTABIL", "category": "sensitive_data", "count": 2}]}
                headers = {"Content-Disposition": 'attachment; filename="governanca-demo.json"'} if path.endswith("/export") else None
                self._json(HTTPStatus.OK, report, headers)
            elif path == "/api/governance/runs":
                self._json(HTTPStatus.OK, {"runs": [SAMPLE_RUN]})
            elif path in (f"/api/governance/runs/{SAMPLE_RUN_ID}", f"/api/governance/runs/{SAMPLE_RUN_ID}/export"):
                headers = {"Content-Disposition": 'attachment; filename="run-demo.json"'} if path.endswith("/export") else None
                self._json(HTTPStatus.OK, {**SAMPLE_RUN, "request": {"input": [{"role": "user", "content": SAMPLE_RUN["prompt"]}]}}, headers)
            elif path == "/api/governance/findings":
                self._json(HTTPStatus.OK, {"findings": [{"finding_id": str(uuid4()), "run_id": SAMPLE_RUN_ID, "category": "sensitive_data", "confidence": "review", "created_at": datetime.now(timezone.utc).isoformat()}]})
            elif path == "/api/governance/alerts":
                self._json(HTTPStatus.OK, {"alerts": [{"alert_id": str(uuid4()), "run_id": SAMPLE_RUN_ID, "category": "sensitive_data", "status": "sent"}]})
            elif path == "/api/governance/knowledge/departments":
                self._json(HTTPStatus.OK, {"departments": [{"id": "dept-demo", "code": "CONTABIL", "name": "Contabilidade"}]})
            elif path == "/api/governance/knowledge/departments/dept-demo/documents":
                self._json(HTTPStatus.OK, {"documents": []})
            else:
                self._json(HTTPStatus.NOT_FOUND, {"detail": "not found"})
            return
        self._json(HTTPStatus.NOT_FOUND, {"detail": "not found"})

    def do_POST(self):
        path = urlparse(self.path).path
        if path == "/api/chat/transcriptions":
            if self._authorized("collaborator"):
                self.rfile.read(int(self.headers.get("Content-Length", "0")))
                self._json(HTTPStatus.OK, {"text": "Transcrição simulada da prévia."})
            return
        try:
            body = self._body() if int(self.headers.get("Content-Length", "0")) else {}
        except (ValueError, json.JSONDecodeError):
            self._json(HTTPStatus.BAD_REQUEST, {"detail": "invalid body"})
            return
        if path == "/api/auth/login":
            code = body.get("employee_code", "").upper()
            role = {"DEMOCHAT": "collaborator", "DEMOGOV": "governance"}.get(code)
            if not role or body.get("password") != "demo12345":
                self._json(HTTPStatus.UNAUTHORIZED, {"detail": "invalid credentials"})
                return
            token = secrets.token_urlsafe(32)
            SESSIONS[token] = {"code": code, "role": role}
            self._json(HTTPStatus.OK, {"must_change_password": False}, {"Set-Cookie": f"preview_session={token}; HttpOnly; SameSite=Lax; Path=/api"})
            return
        if path == "/api/auth/logout":
            cookies = SimpleCookie()
            cookies.load(self.headers.get("Cookie", ""))
            token = cookies.get("preview_session")
            if token:
                SESSIONS.pop(token.value, None)
            self.send_response(HTTPStatus.NO_CONTENT)
            self.send_header("Set-Cookie", "preview_session=; Max-Age=0; Path=/api")
            self.end_headers()
            return
        if path == "/api/chat/projects":
            session = self._authorized("collaborator")
            if session:
                name = str(body.get("name", "")).strip()
                if not name:
                    self._json(HTTPStatus.UNPROCESSABLE_ENTITY, {"detail": "name required"})
                    return
                project = {"id": str(uuid4()), "name": name}
                PROJECTS.setdefault(session["code"], []).append(project)
                self._json(HTTPStatus.CREATED, project)
            return
        if path == "/api/chat/context":
            session = self._authorized("collaborator")
            if session:
                note = {"id": str(uuid4()), "scope": body.get("scope"),
                        "target_id": body.get("target_id"), "kind": body.get("kind"),
                        "content": str(body.get("content", "")).strip(), "automatic": False}
                CONTEXT.setdefault(session["code"], []).append(note)
                self._json(HTTPStatus.CREATED, note)
            return
        if path == "/api/chat/messages":
            session = self._authorized("collaborator")
            if not session:
                return
            text = str(body.get("text", "")).strip()
            message_id = body.get("client_message_id")
            attachments = body.get("attachments", [])
            if (not text and not attachments) or not message_id:
                self._json(HTTPStatus.UNPROCESSABLE_ENTITY, {"detail": "invalid message"})
                return
            existing = next((item for item in RUNS.get(session["code"], []) if item["client_message_id"] == message_id), None)
            if existing:
                self._json(HTTPStatus.CONFLICT, {"detail": {"code": "duplicate_message", "run_id": existing["run_id"]}})
                return
            answer = f"Prévia simulada: recebi sua mensagem — {text}" if text else "Prévia simulada: recebi seus arquivos."
            items = CONVERSATIONS.setdefault(session["code"], [])
            conversation_id = body.get("conversation_id")
            if body.get("new_conversation") or not conversation_id:
                project_id = body.get("project_id")
                if project_id and not any(item["id"] == project_id for item in PROJECTS.get(session["code"], [])):
                    self._json(HTTPStatus.CONFLICT, {"detail": {"code": "project_not_found"}})
                    return
                conversation_id = str(uuid4())
                items.append({"id": conversation_id, "title": None, "project_id": project_id})
            file_info = []
            for item in attachments:
                attachment_id = str(uuid4())
                data = base64.b64decode(item["data"])
                ATTACHMENTS[attachment_id] = (session["code"], conversation_id, item["name"],
                                              mimetypes.guess_type(item["name"])[0] or "application/octet-stream", data)
                file_info.append({"id": attachment_id, "name": item["name"], "size": len(data)})
            run = {"run_id": str(uuid4()), "conversation_id": conversation_id, "client_message_id": message_id, "credential_id": "CONTA-DEMO", "prompt": text,
                   "attachments": file_info,
                   "response": {"output": [{"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": answer}]}]},
                   "outcome": "completed", "started_at": datetime.now(timezone.utc).isoformat()}
            RUNS.setdefault(session["code"], []).append(run)
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Conversation-ID", conversation_id)
            self.send_header("X-Run-ID", run["run_id"])
            self.end_headers()
            try:
                for chunk in (answer[:18], answer[18:]):
                    event = {"type": "response.output_text.delta", "delta": chunk}
                    self.wfile.write(f"event: response.output_text.delta\ndata: {json.dumps(event, ensure_ascii=False)}\n\n".encode())
                    self.wfile.flush()
                    time.sleep(.12)
                completed = {"type": "response.completed", "response": run["response"]}
                self.wfile.write(f"event: response.completed\ndata: {json.dumps(completed, ensure_ascii=False)}\n\n".encode())
            except BrokenPipeError:
                pass
            return
        if path.startswith("/api/chat/runs/") and path.endswith("/artifacts"):
            session = self._authorized("collaborator")
            if not session:
                return
            run_id = path.split("/")[4]
            active = {item["id"] for item in CONVERSATIONS.get(session["code"], [])}
            run = next((item for item in RUNS.get(session["code"], []) if item["run_id"] == run_id and item["conversation_id"] in active), None)
            format = body.get("format")
            if not run or format not in MIME:
                self._json(HTTPStatus.NOT_FOUND, {"detail": "run not found"})
                return
            existing = next((item for item in run.get("artifacts", []) if item["format"] == format), None)
            if existing:
                self._json(HTTPStatus.OK, existing)
                return
            source = run["response"]["output"][0]["content"][0]["text"] if format == "pdf" else json.dumps(
                {"columns": ["Mensagem"], "rows": [[run["prompt"]]]}, ensure_ascii=False)
            data = build_artifact(format, source)
            artifact_id = str(uuid4())
            name = f"maximus-demo.{format}"
            ARTIFACTS[artifact_id] = (session["code"], run["conversation_id"], name, MIME[format], data)
            item = {"id": artifact_id, "name": name, "format": format, "size": len(data)}
            run.setdefault("artifacts", []).append(item)
            self._json(HTTPStatus.OK, item)
            return
        if path.startswith("/api/chat/runs/") and path.endswith("/learn"):
            if self._authorized("collaborator"):
                self._json(HTTPStatus.OK, {"updated": False})
            return
        if path.endswith("/suggest-title") and path.startswith("/api/chat/conversations/"):
            session = self._authorized("collaborator")
            if session:
                conversation_id = path.split("/")[4]
                item = next((entry for entry in CONVERSATIONS.get(session["code"], []) if entry["id"] == conversation_id), None)
                if item:
                    item["title"] = item["title"] or "Conversa de demonstração"
                self._json(HTTPStatus.OK, {"title": item["title"] if item else None})
            return
        if path.endswith("/start") and path.startswith("/api/oauth/credentials/"):
            if self._authorized("collaborator"):
                self._json(HTTPStatus.OK, {"connection_id": str(uuid4()), "authorize_url": "https://example.com/"})
            return
        if path.endswith("/complete") and path.startswith("/api/oauth/connections/"):
            if self._authorized("collaborator"):
                self._json(HTTPStatus.OK, {"connected": True})
            return
        self._json(HTTPStatus.NOT_FOUND, {"detail": "not found"})

    def do_PATCH(self):
        path = urlparse(self.path).path
        session = self._authorized("collaborator")
        if not session:
            return
        body = self._body()
        if path == "/api/chat/profile":
            PROFILES[session["code"]] = str(body.get("text", "")).strip()[:3000]
            self._json(HTTPStatus.OK, {"text": PROFILES[session["code"]], "version": 1,
                                        "updated_at": datetime.now(timezone.utc).isoformat(),
                                        "source": "manual", "source_run_id": None,
                                        "quarantined": False, "learning_status": None})
            return
        if path.startswith("/api/chat/context/"):
            note = next((item for item in CONTEXT.get(session["code"], []) if path.endswith(item["id"])), None)
            if not note:
                self._json(HTTPStatus.NOT_FOUND, {"detail": "not found"})
                return
            note["content"] = str(body.get("content", "")).strip()
            self._json(HTTPStatus.OK, note)
            return
        if path.startswith("/api/chat/projects/"):
            project = next((entry for entry in PROJECTS.get(session["code"], []) if path.endswith(entry["id"])), None)
            if not project:
                self._json(HTTPStatus.NOT_FOUND, {"detail": "not found"})
                return
            project["name"] = str(body.get("name", "")).strip()[:80]
            self._json(HTTPStatus.OK, project)
            return
        conversation_id = path.split("/")[4] if path.endswith("/project") else path.rsplit("/", 1)[-1]
        item = next((entry for entry in CONVERSATIONS.get(session["code"], []) if entry["id"] == conversation_id), None)
        if not item:
            self._json(HTTPStatus.NOT_FOUND, {"detail": "not found"})
            return
        if path.endswith("/project"):
            project_id = body.get("project_id")
            if project_id and not any(project["id"] == project_id for project in PROJECTS.get(session["code"], [])):
                self._json(HTTPStatus.NOT_FOUND, {"detail": "not found"})
                return
            item["project_id"] = project_id
            self._json(HTTPStatus.OK, {"project_id": project_id})
            return
        item["title"] = body.get("title", "")[:60]
        self._json(HTTPStatus.OK, {"title": item["title"]})

    def do_DELETE(self):
        path = urlparse(self.path).path
        session = self._authorized("collaborator")
        if not session:
            return
        if path.startswith("/api/chat/context/"):
            notes = CONTEXT.get(session["code"], [])
            note = next((item for item in notes if path.endswith(item["id"])), None)
            if not note:
                self._json(HTTPStatus.NOT_FOUND, {"detail": "not found"})
                return
            notes.remove(note)
            self.send_response(HTTPStatus.NO_CONTENT)
            self.end_headers()
            return
        if path.startswith("/api/chat/projects/"):
            projects = PROJECTS.get(session["code"], [])
            project = next((entry for entry in projects if path.endswith(entry["id"])), None)
            if not project:
                self._json(HTTPStatus.NOT_FOUND, {"detail": "not found"})
                return
            projects.remove(project)
            for conversation in CONVERSATIONS.get(session["code"], []):
                if conversation.get("project_id") == project["id"]:
                    conversation["project_id"] = None
            self.send_response(HTTPStatus.NO_CONTENT)
            self.end_headers()
            return
        items = CONVERSATIONS.get(session["code"], [])
        item = next((entry for entry in items if path.endswith(entry["id"])), None)
        if not item:
            self._json(HTTPStatus.NOT_FOUND, {"detail": "not found"})
            return
        items.remove(item)
        for attachment_id, attachment in list(ATTACHMENTS.items()):
            if attachment[0] == session["code"] and attachment[1] == item["id"]:
                ATTACHMENTS.pop(attachment_id)
        for artifact_id, artifact in list(ARTIFACTS.items()):
            if artifact[0] == session["code"] and artifact[1] == item["id"]:
                ARTIFACTS.pop(artifact_id)
        self.send_response(HTTPStatus.NO_CONTENT)
        self.end_headers()


if __name__ == "__main__":
    server = ThreadingHTTPServer(("127.0.0.1", 18444), PreviewHandler)
    print("Prévia local: http://localhost:18444/", flush=True)
    server.serve_forever()
