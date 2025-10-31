"""Alembic environment configuration integrating with the Flask app."""

from __future__ import annotations

import logging
import os
from logging.config import fileConfig
from typing import Any

from alembic import context
from sqlalchemy import engine_from_config, pool

from app import create_app
from app_core.extensions import db


config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

logger = logging.getLogger("alembic.env")


def _get_configured_url() -> str:
    url = config.get_main_option("sqlalchemy.url", "")
    if url:
        return url

    # Skip database initialization during migrations to prevent chicken-and-egg issues
    # where migrations need to add columns that the initialization code tries to query
    os.environ["SKIP_DB_INIT"] = "1"

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

