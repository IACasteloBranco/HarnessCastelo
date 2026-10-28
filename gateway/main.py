import asyncio
from contextlib import asynccontextmanager
import logging
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

from backend.database import session_factory
from backend.internal_auth import EmployeeInfo
from backend.store import (QuotaExceeded, RequestRecord, UnavailableAssignment,
                           UnknownClientKey, admit, admit_employee)
from gateway.forwarder import forward
from gateway.internal_auth import _check_origin, current_employee, router as internal_auth_router
from gateway.oauth_connection import router as oauth_router
from gateway.chat import router as chat_router, governance_router
from gateway.profile_learning import process_pending_profiles

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)

@asynccontextmanager
async def lifespan(_app: FastAPI):
    async def profile_worker() -> None:
        while True:
            try:
                await process_pending_profiles()
            except Exception:
                logging.getLogger("profile_learning").exception("profile learning poll failed")
            await asyncio.sleep(15)

    task = asyncio.create_task(profile_worker(), name="profile-learning")
    try:
        yield
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


app = FastAPI(lifespan=lifespan)
app.include_router(internal_auth_router)
app.include_router(oauth_router)
app.include_router(chat_router)
app.include_router(governance_router)


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


@app.post("/api/credentials/{credential_id}/v1/responses")
async def employee_proxy(request: Request, credential_id: str,
                         employee: EmployeeInfo = Depends(current_employee)):
    _check_origin(request)
    path = "responses"
    body = await request.body()
    try:
        admitted = await admit_employee(employee.employee_id, credential_id,
                                        RequestRecord(request.method, path, body))
    except UnavailableAssignment:
        raise HTTPException(403, "credential unavailable")
    except QuotaExceeded as exc:
        message = "rate limit exceeded" if exc.kind == "rate" else "daily quota exceeded"
        raise HTTPException(429, message)
    return await forward(request, path, admitted, body, browser_session=True)


@app.get("/healthz")
async def health():
    try:
        async with session_factory()() as session:
            await session.execute(text("SELECT 1"))
    except Exception:
        raise HTTPException(503, "database unavailable")
    return {"ok": True}


app.mount("/", StaticFiles(directory=Path(__file__).resolve().parent.parent / "frontend" / "public", html=True), name="frontend")
