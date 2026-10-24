import codecs
import json
import logging
import time

import anyio
import httpx
from fastapi import Request, Response
from fastapi.responses import StreamingResponse

from backend.store import AdmittedRun, StreamEvent, append_events, finish_transport
from gateway.auth_store import get_valid_token
from gateway.config import CODEX_BACKEND, UPSTREAM_TIMEOUT, UPSTREAM_CONNECT_TIMEOUT
from gateway.stream_capture import EventStreamDecoder

audit_log = logging.getLogger("audit")


async def forward(request: Request, path: str, admitted: AdmittedRun, body: bytes,
                  browser_session: bool = False, access_token: str | None = None) -> Response:
    credential = admitted.credential
    run_id = admitted.run_id
    t0 = time.time()
    try:
        token = access_token if access_token is not None else await get_valid_token(credential)
    except Exception as exc:
        await finish_transport(run_id, None, "failed", "oauth_token_error")
        audit_log.warning("run=%s cred=%s OAuth token lookup failed: %s", run_id, credential.credential_id, exc)
        return Response(
            content=b'{"error":"credential unavailable"}',
            status_code=502,
            media_type="application/json",
        )

    if path.startswith("responses") and body:
        try:
            payload = json.loads(body)
            if isinstance(payload, dict):
                payload.setdefault("store", False)
                body = json.dumps(payload).encode()
        except json.JSONDecodeError:
            pass

    headers = {
        key: value for key, value in request.headers.items()
        if (key.lower() in ("accept", "content-type") if browser_session else
            key.lower() not in ("host", "authorization", "content-length"))
    }
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
            credential.credential_id, credential.user_id, credential.type, path, exc,
        )
        return Response(
            content=b'{"error":"upstream error"}',
            status_code=502,
            media_type="application/json",
        )

    audit_log.info(
        "cred=%s user=%s type=%s path=%s status=%d latency=%.1fs",
        credential.credential_id, credential.user_id, credential.type, path,
        resp.status_code, time.time() - t0,
    )

    is_event_stream = "text/event-stream" in resp.headers.get("content-type", "").lower()

    async def stream():
        decoder = EventStreamDecoder() if is_event_stream else None
        body_decoder = None if decoder else codecs.getincrementaldecoder("utf-8")("replace")
        body_ordinal = 0
        completed_transport = False
        capture_error = None

        async def capture(events):
            nonlocal capture_error
            if not events or capture_error:
                return
            try:
                await append_events(run_id, events, resp.status_code)
            except Exception as exc:
                capture_error = "capture_error"
                audit_log.warning("run=%s capture_error=%s", run_id, exc)

        try:
            async for chunk in resp.aiter_bytes():
                if decoder:
                    await capture(decoder.feed(chunk))
                else:
                    body_text = body_decoder.decode(chunk)
                    if body_text:
                        await capture([StreamEvent(ordinal=body_ordinal, event_type="response.body", data=body_text)])
                        body_ordinal += 1
                yield chunk

            if decoder:
                await capture(decoder.finish())
            elif body_decoder:
                body_text = body_decoder.decode(b"", final=True)
                if body_text:
                    await capture([StreamEvent(ordinal=body_ordinal, event_type="response.body", data=body_text)])
            completed_transport = True
        except Exception as exc:
            audit_log.warning(
                "run=%s cred=%s path=%s stream_error=%s",
                run_id, credential.credential_id, path, exc,
            )
            raise
        finally:
            outcome = "interrupted"
            if completed_transport:
                outcome = "incomplete" if decoder or capture_error else "completed"
                if resp.status_code >= 400:
                    outcome = "failed"
            try:
                with anyio.move_on_after(5, shield=True):
                    await finish_transport(
                        run_id,
                        resp.status_code,
                        outcome,
                        capture_error,
                    )
            except Exception as exc:
                audit_log.error("run=%s finalization_error=%s", run_id, exc)
            finally:
                with anyio.CancelScope(shield=True):
                    try:
                        await resp.aclose()
                    finally:
                        await client.aclose()

    return StreamingResponse(
        stream(),
        status_code=resp.status_code,
        headers={
            key: value
            for key, value in resp.headers.items()
            if key.lower() not in ("content-length", "transfer-encoding", "content-encoding")
            and (not browser_session or key.lower() not in ("set-cookie", "access-control-allow-origin", "access-control-allow-credentials"))
        },
    )
