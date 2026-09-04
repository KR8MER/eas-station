"""Add map_tile_settings table for the alert share-card basemap provider.

Lets an operator switch the share-card map inset from plain OpenStreetMap
raster tiles (the zero-config default) to CARTO's Dark Matter style, which
is authored dark and minimal from the start rather than a light OSM tile
force-darkened in post -- see app_utils/image_export/map_style.py's
tone_basemap(). Requires a free CARTO API key (carto_api_key, encrypted
at rest like every other stored credential in this project).

Revision ID: 20260904_map_tile_settings
Revises: 20260902_tickstem_service_heartbeats
Create Date: 2026-09-04
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260904_map_tile_settings"
down_revision = "20260902_tickstem_service_heartbeats"
branch_labels = None
depends_on = None


def upgrade() -> None:
    from sqlalchemy import inspect

    conn = op.get_bind()
    inspector = inspect(conn)

    if "map_tile_settings" not in inspector.get_table_names():
        op.create_table(
            "map_tile_settings",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("provider", sa.String(length=50), nullable=False, server_default="osm"),
            sa.Column("carto_api_key", sa.Text(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
        )


def downgrade() -> None:
    from sqlalchemy import inspect

    conn = op.get_bind()
    inspector = inspect(conn)
    if "map_tile_settings" in inspector.get_table_names():
        op.drop_table("map_tile_settings")
