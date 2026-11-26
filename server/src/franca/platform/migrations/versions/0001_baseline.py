"""The first schema: contracts/db/schema.sql as it was on 26 November 2026.

Revision ID: 0001
Revises:
Created: 2026-11-26

The SQL is kept beside this file (0001_baseline.sql) and is not changed afterwards. Later schema changes are new
migrations, written from the change to contracts/db/tables.sql.
"""

import sqlite3
from collections.abc import Iterator
from pathlib import Path

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def _statements(sql: str) -> Iterator[str]:
    """Splits a script into statements. Triggers have semicolons inside BEGIN ... END, so lines are joined until
    SQLite says the statement is complete."""
    buffer = ""
    for line in sql.splitlines(keepends=True):
        buffer += line
        if sqlite3.complete_statement(buffer):
            statement = buffer.strip()
            buffer = ""
            if statement and not all(part.startswith("--") for part in statement.splitlines() if part.strip()):
                yield statement


def upgrade() -> None:
    sql = (Path(__file__).with_name("0001_baseline.sql")).read_text(encoding="utf-8")
    for statement in _statements(sql):
        op.execute(statement)


def downgrade() -> None:
    raise NotImplementedError("The first schema cannot be undone; restore a backup instead")
