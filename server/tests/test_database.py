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


def _normalised_sql(sql: str | None) -> str:
    lines = [line.split("--", 1)[0] for line in (sql or "").splitlines()]
    return " ".join(" ".join(lines).split())


def schema_of(connection: sqlite3.Connection) -> dict[str, object]:
    """The schema as structure: columns, keys and indexes for tables, and the SQL text for views, triggers and index
    conditions. Table SQL text is not compared, because ALTER TABLE ADD COLUMN writes it differently from CREATE TABLE."""
    objects = connection.execute(
        "SELECT type, name, tbl_name, sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' AND name != 'alembic_version'"
    ).fetchall()
    schema: dict[str, object] = {
        "user_version": connection.execute("PRAGMA user_version").fetchone()[0],
        "application_id": connection.execute("PRAGMA application_id").fetchone()[0],
    }
    for kind, name, table, sql in objects:
        if kind == "table":
            schema[f"table {name}"] = {
                "options": connection.execute("SELECT strict, wr FROM pragma_table_list WHERE name = ?", (name,)).fetchall(),
                "columns": connection.execute(f"PRAGMA table_xinfo('{name}')").fetchall(),
                "foreign_keys": connection.execute(f"PRAGMA foreign_key_list('{name}')").fetchall(),
                "checks": _normalised_sql(sql).count("CHECK"),
            }
        elif kind == "index":
            schema[f"index {name}"] = {
                "table": table,
                "columns": connection.execute(f"PRAGMA index_xinfo('{name}')").fetchall(),
                "sql": _normalised_sql(sql),
            }
        else:
            schema[f"{kind} {name}"] = _normalised_sql(sql)
    return schema


def test_connections_use_the_agreed_sqlite_settings(tmp_path: Path) -> None:
    engine = db.make_engine(tmp_path / "franca.db")
    with engine.connect() as connection:
        assert connection.execute(text("PRAGMA foreign_keys")).scalar() == 1
        assert connection.execute(text("PRAGMA journal_mode")).scalar() == "wal"
        assert connection.execute(text("PRAGMA busy_timeout")).scalar() == 5000
        assert connection.execute(text("PRAGMA synchronous")).scalar() == 1  # NORMAL


def test_a_failed_change_is_undone_in_full(tmp_path: Path) -> None:
    # A migration that fails halfway must not leave half a schema behind (the driver does not do this by itself).
    engine = db.make_engine(tmp_path / "franca.db")
    with pytest.raises(RuntimeError), engine.begin() as connection:
        connection.exec_driver_sql("CREATE TABLE first (id INTEGER PRIMARY KEY) STRICT")
        raise RuntimeError("the second statement failed")
    with engine.connect() as connection:
        assert connection.exec_driver_sql("SELECT count(*) FROM sqlite_master").scalar() == 0
    engine.dispose()


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


def test_a_column_added_by_alter_table_compares_equal_to_the_same_column_in_create_table() -> None:
    altered = sqlite3.connect(":memory:")
    altered.executescript("CREATE TABLE t (a INTEGER PRIMARY KEY, b TEXT -- note\n) STRICT; ALTER TABLE t ADD COLUMN c TEXT;")
    created = sqlite3.connect(":memory:")
    created.executescript("CREATE TABLE t (a INTEGER PRIMARY KEY, b TEXT, c TEXT) STRICT;")
    assert schema_of(altered) == schema_of(created)


def test_a_missing_column_is_found() -> None:
    one = sqlite3.connect(":memory:")
    one.executescript("CREATE TABLE t (a INTEGER PRIMARY KEY, b TEXT) STRICT;")
    two = sqlite3.connect(":memory:")
    two.executescript("CREATE TABLE t (a INTEGER PRIMARY KEY) STRICT;")
    assert schema_of(one) != schema_of(two)


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


def test_the_statement_splitter_refuses_an_incomplete_last_statement() -> None:
    import importlib.util

    path = Path(db.__file__).parent / "migrations" / "versions" / "0001_baseline.py"
    spec = importlib.util.spec_from_file_location("baseline", path)
    assert spec and spec.loader
    baseline = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(baseline)
    sql = "-- header\nCREATE TABLE a (x INTEGER);\nCREATE TRIGGER t AFTER INSERT ON a BEGIN SELECT 1; END;\nCREATE TABLE b (y)"
    statements = baseline._statements(sql)
    assert next(statements).startswith("-- header\nCREATE TABLE a")
    assert next(statements).startswith("CREATE TRIGGER t")
    with pytest.raises(ValueError, match="incomplete statement"):
        next(statements)
