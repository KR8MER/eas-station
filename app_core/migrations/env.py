"""Alembic environment configuration integrating with the Flask app."""

from __future__ import annotations

import logging
import os
from logging.config import fileConfig
from typing import Any

from alembic import context
from sqlalchemy import engine_from_config, pool

# MUST be set before `from app import create_app` below. Importing app.py runs
# its module-level startup, which reads SKIP_DB_INIT to decide whether to launch
# the background workers (RWT scheduler, retention, auto-purge, metrics
# sampler). Those workers query tables immediately, so during a migration run
# against a database whose schema is mid-flight they raise UndefinedTable and
# bury the real migration output in tracebacks. This assignment used to live
# inside _get_configured_url(), which runs long after the import has already
# started the workers, so the guard never took effect.
os.environ["SKIP_DB_INIT"] = "1"

from app import create_app  # noqa: E402  (import intentionally after the flag)
from app_core.extensions import db  # noqa: E402


config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

logger = logging.getLogger("alembic.env")


def _get_configured_url() -> str:
    url = config.get_main_option("sqlalchemy.url", "")
    if url:
        return url

    # SKIP_DB_INIT is set at module import time above — it has to be, because
    # the guard is read while `app` is being imported, which happens before
    # this function ever runs.
    app = create_app()
    with app.app_context():
        database_uri = app.config.get("SQLALCHEMY_DATABASE_URI", "")
    if not database_uri:
        raise RuntimeError("Database URL is not configured for migrations")

    config.set_main_option("sqlalchemy.url", database_uri)
    return database_uri


target_metadata = db.metadata


def run_migrations_offline() -> None:
    """Run migrations without establishing a DBAPI connection."""

    url = _get_configured_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        compare_type=True,
        compare_server_default=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in online mode with an engine connection."""

    _get_configured_url()
    connectable = engine_from_config(
        config.get_section(config.config_ini_section) or {},
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            compare_server_default=True,
        )

        with context.begin_transaction():
            context.run_migrations()


def run_migrations() -> None:
    if context.is_offline_mode():
        run_migrations_offline()
    else:
        run_migrations_online()


run_migrations()

