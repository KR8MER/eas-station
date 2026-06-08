"""Add rich-email rendering / media columns to notification_settings.

Adds operator controls for the upgraded EAS alert emails:

  - email_html            BOOLEAN NOT NULL DEFAULT TRUE
        Send a multipart/alternative message with a styled HTML body
        (the existing plain-text body is retained as a fallback).
  - email_include_map     BOOLEAN NOT NULL DEFAULT TRUE
        Render a static coverage-map image of the affected area and
        embed it inline in the HTML body.
  - email_audio_link      BOOLEAN NOT NULL DEFAULT TRUE
        Include a "listen / download" link to the broadcast audio in
        the email body (requires public_base_url).
  - email_compress_audio  BOOLEAN NOT NULL DEFAULT FALSE
        Transcode the attached composite audio from WAV to MP3 to
        shrink the attachment (falls back to WAV if encoding is
        unavailable).
  - public_base_url       VARCHAR(255) NOT NULL DEFAULT ''
        Externally reachable base URL of this station (e.g.
        https://eas.example.com) used to build links in notifications.

Revision ID: 20260608_add_email_rendering_media
Revises: 20260605_add_endec_feeds_to_eas_settings
Create Date: 2026-06-08
"""

from __future__ import annotations

from alembic import op


revision = "20260608_add_email_rendering_media"
down_revision = "20260605_add_endec_feeds_to_eas_settings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE notification_settings"
        " ADD COLUMN IF NOT EXISTS email_html BOOLEAN NOT NULL DEFAULT TRUE"
    )
    op.execute(
        "ALTER TABLE notification_settings"
        " ADD COLUMN IF NOT EXISTS email_include_map BOOLEAN NOT NULL DEFAULT TRUE"
    )
    op.execute(
        "ALTER TABLE notification_settings"
        " ADD COLUMN IF NOT EXISTS email_audio_link BOOLEAN NOT NULL DEFAULT TRUE"
    )
    op.execute(
        "ALTER TABLE notification_settings"
        " ADD COLUMN IF NOT EXISTS email_compress_audio BOOLEAN NOT NULL DEFAULT FALSE"
    )
    op.execute(
        "ALTER TABLE notification_settings"
        " ADD COLUMN IF NOT EXISTS public_base_url VARCHAR(255) NOT NULL DEFAULT ''"
    )


def downgrade() -> None:
    op.drop_column("notification_settings", "public_base_url")
    op.drop_column("notification_settings", "email_compress_audio")
    op.drop_column("notification_settings", "email_audio_link")
    op.drop_column("notification_settings", "email_include_map")
    op.drop_column("notification_settings", "email_html")
