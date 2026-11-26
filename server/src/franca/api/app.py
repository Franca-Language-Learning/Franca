"""The application factory. Routes are grouped in one router per module and mounted under /api/v1."""

from fastapi import APIRouter, FastAPI, Response
from pydantic import BaseModel

from franca.platform import Settings, load_settings

API_PREFIX = "/api/v1"


class Health(BaseModel):
    status: str
    version: str


def health_router(settings: Settings) -> APIRouter:
    router = APIRouter(tags=["platform"])

    @router.get("/health", operation_id="getHealth", summary="Whether the service is running", response_model=Health)
    def get_health(response: Response) -> Health:
        response.headers["Cache-Control"] = "no-store"
        return Health(status="ok", version=settings.version)

    return router


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or load_settings()
    # The version in the contract is the API version, not the release, so the contract file does not change
    # with every release.
    app = FastAPI(title="Franca API", version="1", docs_url=None, redoc_url=None, openapi_url=f"{API_PREFIX}/openapi.json")
    app.include_router(health_router(settings), prefix=API_PREFIX)
    return app
