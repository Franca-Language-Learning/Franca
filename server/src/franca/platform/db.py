"""Database access: SQLite through SQLAlchemy, with the schema built and upgraded by Alembic migrations.

The schema contract is contracts/db/schema.sql. The migrations in migrations/versions are applied in order to reach
it, and tests/test_database.py checks that together they build exactly the contract schema.
"""

from pathlib import Path
from typing import Any

from alembic import command
from alembic.config import Config
from sqlalchemy import Connection, Engine, create_engine, event


def _sqlite_settings(dbapi_connection: Any, _record: Any) -> None:
    # The Python sqlite3 driver starts a transaction only before INSERT, UPDATE or DELETE, so DDL in a migration would
    # not be undone after an error. Its own transaction handling is switched off here, and SQLAlchemy sends BEGIN
    # itself (_begin below), so a failed migration leaves the database as it was.
    dbapi_connection.isolation_level = None
    # Foreign keys are off by default in SQLite and cannot be changed inside a transaction, so they are switched on
    # for each connection. With WAL, readers and the writer can work at the same time. Litestream also needs WAL.
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys = ON")
    cursor.execute("PRAGMA journal_mode = WAL")
    cursor.execute("PRAGMA busy_timeout = 5000")
    cursor.execute("PRAGMA synchronous = NORMAL")
    cursor.close()


def _begin(connection: Connection) -> None:
    # IMMEDIATE takes the write lock at the start, so two requests that read and then write wait for each other
    # (up to the busy timeout) instead of one failing with "database is locked". With a few learners the wait is short.
    connection.exec_driver_sql("BEGIN IMMEDIATE")


def make_engine(path: Path | str) -> Engine:
    engine = create_engine(f"sqlite:///{path}")
    event.listen(engine, "connect", _sqlite_settings)
    event.listen(engine, "begin", _begin)
    return engine


def alembic_config(engine: Engine | None = None) -> Config:
    config = Config()
    config.set_main_option("script_location", "franca.platform:migrations")
    if engine is not None:
        config.attributes["engine"] = engine
    return config


def upgrade(path: Path | str, revision: str = "head") -> None:
    engine = make_engine(path)
    try:
        command.upgrade(alembic_config(engine), revision)
    finally:
        engine.dispose()


def downgrade(path: Path | str, revision: str) -> None:
    engine = make_engine(path)
    try:
        command.downgrade(alembic_config(engine), revision)
    finally:
        engine.dispose()
