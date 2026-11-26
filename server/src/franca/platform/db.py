"""Database access: SQLite through SQLAlchemy, with the schema built and upgraded by Alembic migrations.

The schema contract is contracts/db/schema.sql. Each migration in migrations/versions brings the database one step
closer to it; tests/test_database.py checks that the migrations together build exactly the contract schema.
"""

from pathlib import Path
from typing import Any

from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, event


def _sqlite_settings(dbapi_connection: Any, _record: Any) -> None:
    # Foreign keys are off by default in SQLite and cannot be changed inside a transaction, so they are switched on
    # for each connection. WAL lets readers and the writer work at the same time; Litestream needs it too.
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys = ON")
    cursor.execute("PRAGMA journal_mode = WAL")
    cursor.execute("PRAGMA busy_timeout = 5000")
    cursor.execute("PRAGMA synchronous = NORMAL")
    cursor.close()


def make_engine(path: Path | str) -> Engine:
    engine = create_engine(f"sqlite:///{path}")
    event.listen(engine, "connect", _sqlite_settings)
    return engine


def alembic_config(path: Path | str | None = None) -> Config:
    config = Config()
    config.set_main_option("script_location", "franca.platform:migrations")
    if path is not None:
        config.attributes["engine"] = make_engine(path)
    return config


def upgrade(path: Path | str, revision: str = "head") -> None:
    command.upgrade(alembic_config(path), revision)


def downgrade(path: Path | str, revision: str) -> None:
    command.downgrade(alembic_config(path), revision)
