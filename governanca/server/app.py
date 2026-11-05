"""Standalone HTTP service for the browser extension's governance API."""

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from governanca.server.capture_app.integration import (
    capture_app,
    clean_capture_store,
    initialize_capture_store,
)
from governanca.server.auth_api import EXTENSION_ORIGIN, router as auth_router
from governanca.server.investigations_api import router as investigations_router
from governanca.server.inspection import protect_stored_text


@asynccontextmanager
async def lifespan(application: FastAPI):
    application.state.capture_store_ready = False

    async def initialize_store():
        while not application.state.capture_store_ready:
            try:
                await asyncio.to_thread(initialize_capture_store)
                application.state.capture_store_ready = True
            except Exception:
                logging.getLogger("governance_capture").exception(
                    "capture store initialization failed; capture routes will return 503"
                )
                await asyncio.sleep(60)

    async def retain_capture_data():
        while True:
            await asyncio.sleep(24 * 60 * 60)
            if not application.state.capture_store_ready:
                continue
            try:
                await asyncio.to_thread(clean_capture_store)
            except Exception:
                logging.getLogger("governance_capture").exception("capture retention failed")

    workers = (
        asyncio.create_task(initialize_store(), name="governance-capture-initialization"),
        asyncio.create_task(retain_capture_data(), name="governance-capture-retention"),
    )
    try:
        yield
    finally:
        for worker in workers:
            worker.cancel()
            try:
                await worker
            except asyncio.CancelledError:
                pass


app = FastAPI(lifespan=lifespan)
app.state.capture_store_ready = False
app.include_router(auth_router)
app.include_router(investigations_router)
app.mount("/api/capture", capture_app(protect_content=protect_stored_text), name="governance-capture")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[EXTENSION_ORIGIN],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type", "X-Machine-Id", "X-Machine-Timestamp",
                   "X-Machine-Nonce", "X-Machine-Signature"],
)


@app.middleware("http")
async def require_capture_store(request: Request, call_next):
    if request.url.path.startswith("/api/capture/") and not app.state.capture_store_ready:
        return JSONResponse(status_code=503, content={"detail": "Capture store unavailable"})
    return await call_next(request)


@app.get("/healthz")
async def health():
    return {"ok": True}


_portal = Path(__file__).resolve().parent / "public"

@app.get("/change-password")
async def change_password_page():
    return FileResponse(_portal / "index.html")

app.mount("/", StaticFiles(directory=_portal, html=True), name="governance-portal")


if __name__ == "__main__":
    import asyncio
    import sys
    import uvicorn

    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    uvicorn.run("governanca.server.app:app", host="127.0.0.1", port=18081, loop="none")
