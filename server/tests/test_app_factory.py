"""Checks made when the service starts."""

from pathlib import Path

import pytest

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
