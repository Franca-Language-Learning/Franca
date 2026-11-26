"""Alembic environment. The engine is given by franca.platform.db (or by pytest-alembic in the tests)."""

from alembic import context
from sqlalchemy import Engine

config = context.config
engine = config.attributes.get("engine") or config.attributes.get("connection")
if engine is None:
    raise RuntimeError("Run migrations with franca.platform.db.upgrade. The engine is passed to Alembic there.")

if isinstance(engine, Engine):
    with engine.connect() as connection:
        context.configure(connection=connection, render_as_batch=True)
        with context.begin_transaction():
            context.run_migrations()
else:
    context.configure(connection=engine, render_as_batch=True)
    with context.begin_transaction():
        context.run_migrations()
