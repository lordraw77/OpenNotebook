"""Alembic environment. Uses the synchronous psycopg driver with the application's database URL."""

from __future__ import annotations

from alembic import context
from sqlalchemy import create_engine, pool

from opennotebook import models  # noqa: F401 - registers tables on Base.metadata
from opennotebook.config import get_settings
from opennotebook.db import Base

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(url=get_settings().database_url, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_engine(get_settings().database_url, poolclass=pool.NullPool)
    with engine.connect() as connection:
        # Serialize concurrent `migrate` runs (e.g. several replicas starting at once).
        connection.exec_driver_sql("SELECT pg_advisory_lock(727274)")
        context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()
        connection.exec_driver_sql("SELECT pg_advisory_unlock(727274)")
        connection.commit()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
