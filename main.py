import logging

from fastapi import FastAPI, HTTPException, Request
from sqlalchemy import text

from database import session_factory
from forwarder import forward
from store import QuotaExceeded, RequestRecord, UnknownClientKey, admit

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)

app = FastAPI()


@app.api_route("/v1/{path:path}", methods=["GET", "POST", "PUT", "DELETE"])
async def proxy(request: Request, path: str):
    key = request.headers.get("Authorization", "").removeprefix("Bearer ").strip()
    if not key:
        raise HTTPException(401, "missing client key")

    body = await request.body()
    try:
        admitted = await admit(key, RequestRecord(request.method, path, body))
    except UnknownClientKey:
        raise HTTPException(401, "invalid client key")
    except QuotaExceeded as exc:
        message = "rate limit exceeded" if exc.kind == "rate" else "daily quota exceeded"
        raise HTTPException(429, message)

    return await forward(request, path, admitted, body)


@app.get("/healthz")
async def health():
    try:
        async with session_factory()() as session:
            await session.execute(text("SELECT 1"))
    except Exception:
        raise HTTPException(503, "database unavailable")
    return {"ok": True}
