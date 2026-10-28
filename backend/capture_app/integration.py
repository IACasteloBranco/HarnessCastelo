"""Mount the existing capture endpoints inside the Harness server."""

from fastapi import FastAPI
from fastapi.routing import APIRoute

from .db import clean_expired, initialize
from .settings import get_settings

CAPTURE_PATHS = {
    "/v1/admin/analytics/summary",
    "/v1/admin/analytics/interactions",
    "/v1/admin/machines/assignment-requests",
    "/v1/admin/machines/{installation_id}/assignment-request/approve",
    "/v1/admin/machines/{installation_id}/assignment-request/reject",
    "/v1/artifact-metadata",
    "/v1/artifact-metadata/recent",
    "/v1/interactions",
    "/v1/interactions/{interaction_id}",
    "/v1/interactions/{interaction_id}/response",
    "/v1/machines",
    "/v1/machines/{installation_id}",
    "/v1/machines/{installation_id}/assignment-request",
    "/v1/stream-captures",
    "/v1/stream-captures/recent",
}


def capture_app() -> FastAPI:
    from .main import app as legacy_app

    embedded = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    embedded.router.routes.extend(
        route for route in legacy_app.router.routes if isinstance(route, APIRoute)
        and route.path in CAPTURE_PATHS
    )
    embedded.exception_handlers.update(legacy_app.exception_handlers)
    return embedded


def initialize_capture_store() -> None:
    settings = get_settings()
    initialize(settings)
    clean_expired(settings)


def clean_capture_store() -> int:
    return clean_expired(get_settings())
