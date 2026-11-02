"""Run extension authentication and capture without starting Maximus workers."""

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from backend.capture_app.integration import capture_app, initialize_capture_store
from backend.database import session_factory
from gateway.internal_auth import EXTENSION_ORIGIN, router as internal_auth_router


@asynccontextmanager
async def lifespan(_app: FastAPI):
    await asyncio.to_thread(initialize_capture_store)
    yield


app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
app.include_router(internal_auth_router)
app.mount("/api/capture", capture_app())
app.add_middleware(
    CORSMiddleware,
    allow_origins=[EXTENSION_ORIGIN],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type", "X-Machine-Id", "X-Machine-Timestamp",
                   "X-Machine-Nonce", "X-Machine-Signature"],
)


@app.get("/healthz")
async def health():
    try:
        async with session_factory()() as session:
            await session.execute(text("SELECT 1"))
    except Exception as exc:
        raise HTTPException(503, "database unavailable") from exc
    return {"ok": True}
