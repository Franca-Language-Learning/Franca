"""Shared test fixtures: a migrated database in a temporary folder."""

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Connection, Engine

from franca.platform import db


@pytest.fixture
def database_path(tmp_path: Path) -> Path:
    path = tmp_path / "franca.db"
    db.upgrade(path)
    return path


@pytest.fixture
def engine(database_path: Path) -> Iterator[Engine]:
    engine = db.make_engine(database_path)
    yield engine
    engine.dispose()


@pytest.fixture
def connection(engine: Engine) -> Iterator[Connection]:
    with engine.begin() as connection:
        yield connection


class FrancaTestClient(TestClient):
    """A test client that acts as Franca's own pages do: before a request that changes something, it makes sure the
    browser has the anti-forgery cookie and sends its token in the X-CSRF-Token header (story E02-003)."""

    def request(self, method: str, url: Any, **kwargs: Any) -> Any:  # type: ignore[override]
        if method.upper() not in {"GET", "HEAD", "OPTIONS"}:
            if "franca_csrf" not in self.cookies:
                super().request("GET", "/api/v1/health")
            headers = dict(kwargs.pop("headers", None) or {})
            headers.setdefault("X-CSRF-Token", self.cookies.get("franca_csrf", ""))
            kwargs["headers"] = headers
        return super().request(method, url, **kwargs)
