"""Shared test fixtures: a migrated database in a temporary folder."""

from collections.abc import Iterator
from pathlib import Path

import pytest
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
