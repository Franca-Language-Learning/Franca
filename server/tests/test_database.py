"""The database layer (franca.platform): SQLite settings and the Alembic migrations.

The schema contract is contracts/db/schema.sql. The migrations have to build exactly that schema, so a change to
tables.sql without a new migration fails test_migrations_build_the_contract_schema.
"""

import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import text

from franca.platform import db

CONTRACT_SCHEMA = Path(__file__).resolve().parents[2] / "contracts" / "db" / "schema.sql"


def schema_of(connection: sqlite3.Connection) -> list[tuple[str, str, str]]:
    rows = connection.execute(
        "SELECT type, name, sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' AND name != 'alembic_version' ORDER BY type, name"
    ).fetchall()
    return [(kind, name, " ".join((sql or "").split())) for kind, name, sql in rows]


def test_connections_use_the_agreed_sqlite_settings(tmp_path: Path) -> None:
    engine = db.make_engine(tmp_path / "franca.db")
    with engine.connect() as connection:
        assert connection.execute(text("PRAGMA foreign_keys")).scalar() == 1
        assert connection.execute(text("PRAGMA journal_mode")).scalar() == "wal"
        assert connection.execute(text("PRAGMA busy_timeout")).scalar() == 5000
        assert connection.execute(text("PRAGMA synchronous")).scalar() == 1  # NORMAL


def test_migrations_build_the_contract_schema(tmp_path: Path) -> None:
    migrated = tmp_path / "migrated.db"
    db.upgrade(migrated)
    expected = sqlite3.connect(":memory:")
    expected.executescript(CONTRACT_SCHEMA.read_text(encoding="utf-8"))
    actual = sqlite3.connect(migrated)
    assert schema_of(actual) == schema_of(expected)


def test_upgrading_twice_changes_nothing(tmp_path: Path) -> None:
    path = tmp_path / "franca.db"
    db.upgrade(path)
    first = schema_of(sqlite3.connect(path))
    db.upgrade(path)
    assert schema_of(sqlite3.connect(path)) == first


def test_the_migration_command_upgrades_the_configured_database(tmp_path: Path) -> None:
    path = tmp_path / "from-command.db"
    env = {"FRANCA_DATABASE_PATH": str(path), "PATH": "/usr/bin:/bin"}
    src = Path(__file__).resolve().parents[1] / "src"
    result = subprocess.run(
        [sys.executable, "-m", "franca.platform.migrate"], env={**env, "PYTHONPATH": str(src)}, capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr
    tables = {row[0] for row in sqlite3.connect(path).execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert "identity_learner" in tables


def test_the_baseline_migration_cannot_be_undone(tmp_path: Path) -> None:
    path = tmp_path / "franca.db"
    db.upgrade(path)
    with pytest.raises(NotImplementedError):
        db.downgrade(path, "base")


def test_the_baseline_sql_is_not_edited() -> None:
    # Schema changes are new migrations. Editing the baseline would leave existing databases behind.
    import hashlib

    baseline = Path(db.__file__).parent / "migrations" / "versions" / "0001_baseline.sql"
    assert hashlib.sha256(baseline.read_bytes()).hexdigest() == "d894df59ec348dc0f32cef65ff4d2ec24fc991494c39e57581b6b8e7f3f95799"
