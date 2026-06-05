"""Add ENDEC device-feed columns to eas_settings.

Adds configuration for the Sage-ENDEC-compatible serial/TCP "device
feeds" (Generic Character Generator, News Feed, decoder status, raw EAS
encoder mirror) served by services.endec_feeds:

  - endec_feeds_enabled  BOOLEAN NOT NULL DEFAULT FALSE
  - endec_feeds          JSONB   NOT NULL DEFAULT '[]'

``endec_feeds`` holds a list of feed dicts:
``{"name": str, "format": str, "port": int, "enabled": bool}``.

Revision ID: 20260605_add_endec_feeds_to_eas_settings
Revises: 20260524_add_dashboard_branding_to_application_settings
Create Date: 2026-06-05
"""

from __future__ import annotations

from alembic import op


revision = "20260605_add_endec_feeds_to_eas_settings"
down_revision = "20260524_add_dashboard_branding_to_application_settings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE eas_settings"
        " ADD COLUMN IF NOT EXISTS endec_feeds_enabled BOOLEAN NOT NULL DEFAULT FALSE"
    )
    op.execute(
        "ALTER TABLE eas_settings"
        " ADD COLUMN IF NOT EXISTS endec_feeds JSONB NOT NULL DEFAULT '[]'::jsonb"
    )


def downgrade() -> None:
    op.drop_column("eas_settings", "endec_feeds")
    op.drop_column("eas_settings", "endec_feeds_enabled")
