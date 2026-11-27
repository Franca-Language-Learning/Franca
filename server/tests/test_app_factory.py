"""Checks made when the service starts."""

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from franca.api import create_app
from franca.platform import load_settings


def test_production_needs_a_session_secret(tmp_path: Path) -> None:
    # Sign-in with Google and with passkeys keeps its state in a cookie signed with this secret.
    settings = load_settings({"FRANCA_ENVIRONMENT": "production", "FRANCA_DATABASE_PATH": str(tmp_path / "f.db")})
    with pytest.raises(RuntimeError, match="FRANCA_SESSION_SECRET_FILE"):
        create_app(settings)


def test_production_starts_with_a_session_secret(tmp_path: Path) -> None:
    settings = load_settings(
        {"FRANCA_ENVIRONMENT": "production", "FRANCA_DATABASE_PATH": str(tmp_path / "f.db"), "FRANCA_SESSION_SECRET": "s" * 32}
    )
    assert create_app(settings).title == "Franca API"


def test_production_needs_a_long_session_secret(tmp_path: Path) -> None:
    settings = load_settings(
        {"FRANCA_ENVIRONMENT": "production", "FRANCA_DATABASE_PATH": str(tmp_path / "f.db"), "FRANCA_SESSION_SECRET": "short"}
    )
    with pytest.raises(RuntimeError, match="at least 32"):
        create_app(settings)


def test_production_needs_https_except_on_this_computer(tmp_path: Path) -> None:
    base = {"FRANCA_ENVIRONMENT": "production", "FRANCA_DATABASE_PATH": str(tmp_path / "f.db"), "FRANCA_SESSION_SECRET": "s" * 32}
    with pytest.raises(RuntimeError, match="https"):
        create_app(load_settings({**base, "FRANCA_PUBLIC_URL": "http://franca.example.ts.net"}))
    create_app(load_settings({**base, "FRANCA_PUBLIC_URL": "http://localhost:8080"}))
    create_app(load_settings({**base, "FRANCA_PUBLIC_URL": "https://franca.example.ts.net"}))


def test_a_database_that_is_locked_gives_a_503_with_a_time_to_try_again(tmp_path: Path) -> None:
    client = TestClient(failing_app(tmp_path, "database is locked"), raise_server_exceptions=False)

    response = client.get("/api/v1/fails")

    assert response.status_code == 503
    assert response.headers["Retry-After"] == "2"


def test_another_database_error_is_not_answered_as_busy(tmp_path: Path) -> None:
    # A full disk or a missing table is not solved by trying again, so the answer is a server error.
    client = TestClient(failing_app(tmp_path, "disk I/O error"), raise_server_exceptions=False)

    response = client.get("/api/v1/fails")

    assert response.status_code == 500
    assert "busy" not in response.text


def failing_app(tmp_path: Path, message: str) -> FastAPI:
    """The app with one more route, which fails with a database error that has this message."""
    app = create_app(load_settings({"FRANCA_DATABASE_PATH": str(tmp_path / "f.db")}))

    @app.get("/api/v1/fails")
    def fails() -> None:
        raise OperationalError("SELECT 1", {}, Exception(message))

    return app
