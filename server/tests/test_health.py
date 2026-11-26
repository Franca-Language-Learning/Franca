"""The health endpoint, which Gatus and the updater call to see whether the service is running."""

from conftest import FrancaTestClient
from franca.api import create_app


def test_health_reports_ok_and_the_version() -> None:
    client = FrancaTestClient(create_app())
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["version"]


def test_health_response_is_not_cached() -> None:
    client = FrancaTestClient(create_app())
    response = client.get("/api/v1/health")
    assert response.headers["cache-control"] == "no-store"


def test_unknown_api_path_returns_404_as_json() -> None:
    client = FrancaTestClient(create_app())
    response = client.get("/api/v1/no-such-thing")
    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/json")
