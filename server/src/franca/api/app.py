"""The application factory. Routes are grouped in one router per module and mounted under /api/v1."""

import secrets
from typing import Any

from fastapi import APIRouter, FastAPI, Response
from pydantic import BaseModel, ConfigDict
from starlette.middleware.sessions import SessionMiddleware

from franca.api import auth
from franca.platform import Settings, load_settings, make_engine

API_PREFIX = "/api/v1"


class Health(BaseModel):
    # Each response model has an example; the client's mock API answers with it.
    model_config = ConfigDict(json_schema_extra={"examples": [{"status": "ok", "version": "0.1.0"}]})

    status: str
    version: str


def health_router(settings: Settings) -> APIRouter:
    router = APIRouter(tags=["platform"])

    @router.get("/health", operation_id="getHealth", summary="Whether the service is running", response_model=Health)
    def get_health(response: Response) -> Health:
        response.headers["Cache-Control"] = "no-store"
        return Health(status="ok", version=settings.version)

    return router


def create_app(settings: Settings | None = None, *, google_transport: Any = None) -> FastAPI:
    """google_transport is for tests: an HTTP transport that answers in place of Google."""
    settings = settings or load_settings()
    if settings.environment == "production" and settings.google is not None and settings.session_secret is None:
        raise RuntimeError("FRANCA_SESSION_SECRET_FILE is missing or empty; sign-in with Google needs it in production")
    # The version in the contract is the API version, not the release, so the contract file does not change
    # with every release.
    app = FastAPI(title="Franca API", version="1", docs_url=None, redoc_url=None, openapi_url=f"{API_PREFIX}/openapi.json")
    # Holds the state of a sign-in with Google for up to 10 minutes. Without a configured secret, a random one is
    # used, and a sign-in that is in progress when the service restarts has to be started again.
    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.session_secret or secrets.token_urlsafe(32),
        session_cookie="franca_oauth",
        max_age=600,
        same_site="lax",
        https_only=settings.cookies_secure,
    )
    app.include_router(health_router(settings), prefix=API_PREFIX)
    app.include_router(auth.install(app, settings, make_engine(settings.database_path), google_transport), prefix=API_PREFIX)
    return app
