"""Database helpers for ensuring optional PostgreSQL/PostGIS features."""

from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app_core.extensions import db


def ensure_postgis_extension(logger: Any) -> bool:
    """Ensure the PostGIS extensions are available when using PostgreSQL."""

    engine = db.engine
    if engine.dialect.name != "postgresql":
        logger.debug(
            "Skipping PostGIS extension check for non-PostgreSQL database (%s)",
            engine.dialect.name,
        )
        return True

    try:
        with engine.connect() as connection:
            connection = connection.execution_options(isolation_level="AUTOCOMMIT")

            postgis_installed = connection.execute(
                text("SELECT 1 FROM pg_extension WHERE extname = 'postgis'")
            ).scalar()

            if not postgis_installed:
                logger.info("Enabling PostGIS extension for spatial operations")
                connection.execute(text("CREATE EXTENSION IF NOT EXISTS postgis"))
            else:
                logger.debug("PostGIS extension already enabled")

            try:
                topology_installed = connection.execute(
                    text("SELECT 1 FROM pg_extension WHERE extname = 'postgis_topology'")
                ).scalar()
                if not topology_installed:
                    connection.execute(
                        text("CREATE EXTENSION IF NOT EXISTS postgis_topology")
                    )
            except SQLAlchemyError as exc:
                logger.debug(
                    "PostGIS topology extension could not be enabled automatically: %s",
                    exc,
                )

        return True
    except SQLAlchemyError as exc:
        logger.error("Failed to ensure PostGIS extension: %s", exc)
        return False


__all__ = ["ensure_postgis_extension"]
