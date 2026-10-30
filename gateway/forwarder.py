import codecs
import asyncio
from contextlib import suppress
import json
import logging
import time

import anyio
import httpx
from fastapi import Request, Response
from fastapi.responses import StreamingResponse
from sqlalchemy.exc import IntegrityError, InterfaceError, OperationalError, SQLAlchemyError

from backend.store import AdmittedRun, RunClosed, StreamEvent, append_events, finish_transport, heartbeat_run
from gateway.auth_store import get_valid_token
from gateway.config import CODEX_BACKEND, UPSTREAM_TIMEOUT, UPSTREAM_CONNECT_TIMEOUT
from gateway.stream_capture import EventStreamDecoder

audit_log = logging.getLogger("audit")
_ARTIFACT_TOOL_SUPPORTED: bool | None = None


def _capture_failure_code(exc: Exception) -> str:
    if isinstance(exc, (OperationalError, InterfaceError)):
        return "capture_transient_error"
    if isinstance(exc, IntegrityError):
        return "capture_integrity_error"
    if isinstance(exc, SQLAlchemyError):
        return "capture_storage_error"
    return "capture_error"


def _disable_artifact_tool(payload: dict) -> dict:
    from backend.chat import CHAT_ARTIFACT_TOOL_FALLBACK

    fallback = {key: value for key, value in payload.items()
                if key not in ("tools", "tool_choice", "parallel_tool_calls")}
    input_items = fallback.get("input")
    for item in input_items if isinstance(input_items, list) else []:
        if (isinstance(item, dict) and item.get("role") == "system"
                and isinstance(item.get("content"), str) and "create_artifact" in item["content"]):
            item["content"] = CHAT_ARTIFACT_TOOL_FALLBACK
            break
    return fallback


async def forward(request: Request, path: str, admitted: AdmittedRun, body: bytes,
                  browser_session: bool = False, access_token: str | None = None,
                  knowledge_search=None) -> Response:
    global _ARTIFACT_TOOL_SUPPORTED
    credential = admitted.credential
    run_id = admitted.run_id
    t0 = time.time()
    knowledge_sources = []
    try:
        token = access_token if access_token is not None else await get_valid_token(credential)
    except Exception as exc:
        await finish_transport(run_id, None, "failed", "oauth_token_error")
        audit_log.warning("run=%s cred=%s OAuth token lookup failed: %s", run_id, credential.credential_id, type(exc).__name__)
        return Response(
            content=b'{"error":"credential unavailable"}',
            status_code=502,
            media_type="application/json",
        )

    payload = None
    if path.startswith("responses") and body:
        try:
            payload = json.loads(body)
            if isinstance(payload, dict):
                payload.setdefault("store", False)
                body = json.dumps(payload).encode()
        except json.JSONDecodeError:
            pass

    artifact_tool_requested = (isinstance(payload, dict)
                               and isinstance(payload.get("tools"), list)
                               and any(tool.get("name") == "create_artifact" for tool in payload["tools"]
                                       if isinstance(tool, dict)))
    artifact_tools_rejected = artifact_tool_requested and _ARTIFACT_TOOL_SUPPORTED is False
    if artifact_tools_rejected:
        payload = _disable_artifact_tool(payload)
        body = json.dumps(payload).encode()

    headers = {
        key.lower(): value for key, value in request.headers.items()
        if (key.lower() in ("accept", "content-type") if browser_session else
            key.lower() not in ("host", "authorization", "content-length"))
    }
    if path.startswith("responses") and isinstance(payload, dict):
        headers["content-type"] = "application/json"
    headers["Authorization"] = f"Bearer {token}"

    client = httpx.AsyncClient(
        timeout=httpx.Timeout(UPSTREAM_TIMEOUT, connect=UPSTREAM_CONNECT_TIMEOUT)
    )
    req = client.build_request(
        request.method,
        f"{CODEX_BACKEND}/{path}" + (f"?{request.url.query}" if request.url.query else ""),
        content=body,
        headers=headers,
    )

    try:
        resp = await client.send(req, stream=True)
    except httpx.HTTPError as exc:
        await client.aclose()
        await finish_transport(run_id, None, "failed", "upstream_connection_error")
        audit_log.warning(
            "cred=%s user=%s type=%s path=%s error=%s",
            credential.credential_id, credential.user_id, credential.type, path, type(exc).__name__,
        )
        return Response(
            content=b'{"error":"upstream error"}',
            status_code=502,
            media_type="application/json",
        )

    if resp.status_code in (400, 422) and artifact_tool_requested and not artifact_tools_rejected:
        try:
            error_body = await resp.aread()
        except httpx.HTTPError as exc:
            await resp.aclose()
            await client.aclose()
            await finish_transport(run_id, None, "failed", "upstream_connection_error")
            audit_log.warning("run=%s artifact-tool response read failed: %s", run_id, type(exc).__name__)
            return Response(content=b'{"error":"upstream error"}', status_code=502,
                            media_type="application/json")
        error_text = error_body.decode("utf-8", errors="replace").lower()
        if not any(term in error_text for term in ("tool", "function")):
            status_code = resp.status_code
            content_type = resp.headers.get("content-type")
            await resp.aclose()
            await client.aclose()
            await finish_transport(run_id, status_code, "failed", "upstream_error")
            return Response(content=error_body, status_code=status_code, media_type=content_type)
        _ARTIFACT_TOOL_SUPPORTED = False
        await resp.aclose()
        payload = _disable_artifact_tool(payload)
        body = json.dumps(payload).encode()
        req = client.build_request(
            request.method,
            f"{CODEX_BACKEND}/{path}" + (f"?{request.url.query}" if request.url.query else ""),
            content=body,
            headers=headers,
        )
        try:
            resp = await client.send(req, stream=True)
        except httpx.HTTPError as exc:
            await client.aclose()
            await finish_transport(run_id, None, "failed", "upstream_connection_error")
            audit_log.warning("run=%s artifact tools rejected; fallback request failed: %s", run_id, type(exc).__name__)
            return Response(content=b'{"error":"upstream error"}', status_code=502,
                            media_type="application/json")
        artifact_tools_rejected = True
        audit_log.warning("run=%s upstream rejected create_artifact; using standard chat", run_id)
    elif artifact_tool_requested and not artifact_tools_rejected and resp.status_code < 400:
        _ARTIFACT_TOOL_SUPPORTED = True

    try_knowledge = (knowledge_search and path.startswith("responses") and resp.status_code < 400
                     and isinstance(payload, dict) and payload.get("stream") is True)

    audit_log.info(
        "cred=%s user=%s type=%s path=%s status=%d latency=%.1fs",
        credential.credential_id, credential.user_id, credential.type, path,
        resp.status_code, time.time() - t0,
    )

    is_event_stream = ("text/event-stream" in resp.headers.get("content-type", "").lower()
                       or (path.startswith("responses") and resp.status_code < 400
                           and isinstance(payload, dict) and payload.get("stream") is True
                           and not resp.headers.get("content-type")))

    async def stream():
        nonlocal resp, knowledge_sources
        owner_task = asyncio.current_task()

        async def keep_alive():
            while True:
                await asyncio.sleep(20)
                try:
                    if await heartbeat_run(run_id):
                        continue
                    audit_log.warning("run=%s lease_lost", run_id)
                except Exception as exc:
                    audit_log.warning("run=%s heartbeat_error=%s", run_id, type(exc).__name__)
                owner_task.cancel()
                return

        heartbeat_task = asyncio.create_task(keep_alive())
        search_available = try_knowledge
        decoder = EventStreamDecoder() if is_event_stream else None
        body_decoder = None if decoder else codecs.getincrementaldecoder("utf-8")("replace")
        next_ordinal = 0
        completed_transport = False
        capture_error = None
        transport_error = None
        terminal_outcome = None
        terminal_response = None

        async def capture(events):
            nonlocal capture_error, next_ordinal, terminal_outcome, terminal_response
            if not events:
                return
            numbered = []
            for event in events:
                numbered.append(StreamEvent(next_ordinal, event.event_type, event.data, event.complete))
                next_ordinal += 1
                if event.complete and event.event_type in (
                    "response.completed", "response.failed", "response.incomplete", "error"
                ):
                    terminal_outcome = {"response.completed": "completed", "response.failed": "failed",
                                        "response.incomplete": "incomplete", "error": "failed"}[event.event_type]
                    if event.event_type == "response.completed":
                        try:
                            data = json.loads(event.data)
                        except json.JSONDecodeError:
                            data = None
                        terminal_response = data.get("response") if isinstance(data, dict) else None
            if capture_error:
                return
            try:
                await append_events(run_id, numbered, resp.status_code)
            except RunClosed:
                raise
            except Exception as exc:
                capture_error = _capture_failure_code(exc)
                audit_log.warning("run=%s %s=%s", run_id, capture_error, type(exc).__name__)

        async def knowledge_failure(code):
            nonlocal transport_error
            transport_error = code
            data = '{"response":{"error":{"message":"knowledge lookup failed"}}}'
            await capture([StreamEvent(0, "response.failed", data)])
            return f"event: response.failed\ndata: {data}\n\n".encode()

        try:
            while True:
                async for chunk in resp.aiter_bytes():
                    if decoder:
                        await capture(decoder.feed(chunk))
                    else:
                        body_text = body_decoder.decode(chunk)
                        if body_text:
                            await capture([StreamEvent(0, "response.body", body_text)])
                    yield chunk

                if decoder:
                    await capture(decoder.finish())
                elif body_decoder:
                    body_text = body_decoder.decode(b"", final=True)
                    if body_text:
                        await capture([StreamEvent(0, "response.body", body_text)])

                if not search_available:
                    break
                search_available = False
                response_data = terminal_response if isinstance(terminal_response, dict) else {}
                calls = [item for item in response_data.get("output", [])
                         if isinstance(item, dict) and item.get("type") == "function_call"
                         and item.get("name") == "search_department_knowledge"]
                if len(calls) != 1:
                    break
                try:
                    call = calls[0]
                    args = json.loads(call.get("arguments", "{}"))
                    if set(args) != {"query"} or not isinstance(args["query"], str):
                        raise ValueError("invalid knowledge tool arguments")
                    result = await knowledge_search(args["query"])
                    knowledge_sources = result.get("sources", [])
                    await capture([StreamEvent(0, "maximus.knowledge_result", json.dumps({
                        "call_id": call["call_id"], "output": result["output"],
                        "sources": knowledge_sources,
                    }, ensure_ascii=False))])
                    next_payload = dict(payload)
                    next_payload["input"] = [*payload.get("input", []),
                                              *response_data.get("output", []),
                                              {"type": "function_call_output", "call_id": call["call_id"],
                                               "output": result["output"]}]
                    next_payload["tools"] = [tool for tool in payload.get("tools", [])
                                              if tool.get("name") != "search_department_knowledge"]
                    next_payload.pop("tool_choice", None)
                    await resp.aclose()
                    next_request = client.build_request("POST", f"{CODEX_BACKEND}/{path}",
                                                        content=json.dumps(next_payload).encode(), headers=headers)
                    resp = await client.send(next_request, stream=True)
                    if resp.status_code >= 400:
                        yield await knowledge_failure("knowledge_upstream_error")
                        break
                    terminal_outcome = None
                    terminal_response = None
                    decoder = EventStreamDecoder()
                    body_decoder = None
                except Exception as exc:
                    audit_log.warning("run=%s department knowledge lookup failed: %s", run_id, type(exc).__name__)
                    yield await knowledge_failure("knowledge_tool_error")
                    break
            completed_transport = True
        except httpx.HTTPError as exc:
            terminal_outcome = "failed"
            transport_error = "upstream_stream_error"
            completed_transport = True
            audit_log.warning("run=%s upstream_stream_error=%s", run_id, type(exc).__name__)
            raise
        except Exception as exc:
            audit_log.warning(
                "run=%s cred=%s path=%s stream_error=%s",
                run_id, credential.credential_id, path, type(exc).__name__,
            )
            raise
        finally:
            heartbeat_task.cancel()
            with anyio.CancelScope(shield=True):
                with suppress(asyncio.CancelledError):
                    await heartbeat_task
            outcome = "interrupted"
            if completed_transport:
                outcome = terminal_outcome or ("incomplete" if decoder else "completed")
                if resp.status_code >= 400:
                    outcome = "failed"
                if capture_error:
                    outcome = "incomplete"
            try:
                with anyio.move_on_after(5, shield=True):
                    await finish_transport(
                        run_id,
                        resp.status_code,
                        outcome,
                        capture_error or transport_error,
                    )
            except Exception as exc:
                audit_log.error("run=%s finalization_error=%s", run_id, type(exc).__name__)
            finally:
                with anyio.CancelScope(shield=True):
                    try:
                        if path.startswith("responses"):
                            try:
                                from backend.chat import materialize_artifact_request, save_knowledge_sources
                                if knowledge_sources:
                                    await save_knowledge_sources(run_id, knowledge_sources)
                                await materialize_artifact_request(run_id)
                            except Exception as exc:
                                audit_log.warning("run=%s artifact_generation_error=%s", run_id, type(exc).__name__)
                        await resp.aclose()
                    finally:
                        await client.aclose()

    response_headers = {
        key: value
        for key, value in resp.headers.items()
        if key.lower() not in ("content-length", "transfer-encoding", "content-encoding")
        and (not browser_session or key.lower() not in ("set-cookie", "access-control-allow-origin", "access-control-allow-credentials"))
    }
    if is_event_stream:
        response_headers["content-type"] = "text/event-stream"
    if artifact_tools_rejected:
        response_headers["X-Maximus-Artifact-Tool"] = "unsupported"
    return StreamingResponse(
        stream(),
        status_code=resp.status_code,
        headers=response_headers,
    )
