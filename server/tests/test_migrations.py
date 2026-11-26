"""Checks from pytest-alembic: one head revision, and the migration history upgrades from empty."""

from pathlib import Path

import pytest
from alembic.config import Config
from pytest_alembic.tests import test_single_head_revision, test_upgrade  # noqa: F401
from sqlalchemy import Engine

from franca.platform import db


@pytest.fixture
def alembic_config() -> Config:
    return db.alembic_config()


@pytest.fixture
def alembic_engine(tmp_path: Path) -> Engine:
    return db.make_engine(tmp_path / "pytest-alembic.db")


def test_the_latest_migration_can_be_undone_and_done_again(tmp_path: Path) -> None:
    path = tmp_path / "franca.db"
    db.upgrade(path)
    db.downgrade(path, "0001")
    db.upgrade(path)
