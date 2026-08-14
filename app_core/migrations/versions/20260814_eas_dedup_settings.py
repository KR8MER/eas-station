"""Make the alert-dedup windows and audio-detection confidence floor
configurable instead of hardcoded constants.

app_core/audio/auto_forward.py hardcoded two dedup windows as module
constants: CROSS_SOURCE_DEDUP_WINDOW_MINUTES = 15 (event-code + FIPS-set
match, used when no usable SAME header is available -- the CAP-only
path) and HEADER_KEY_DEDUP_WINDOW_MINUTES = 24 * 60 = 1440 (SAME-header-
key match). Both are user-visible: the 1440 figure specifically shows up
verbatim in forwarding_reason text an operator reads on the Received
Audio Alerts page ("Cross-source duplicate: SVR already broadcast for
the same alert within 1440min").

Also adds min_log_confidence_percent: reviewing that same page turned up
a real, if easily misdiagnosed, pattern -- one configured audio source is
a nationwide EAS relay network (icecast.gwes-eas.network), so it
legitimately decodes real SAME headers for alerts from all over the
country that are correctly filtered as "no FIPS match" for this station's
coverage area. Those are true decodes, not noise, and are unaffected by
this setting. The setting only targets the smaller, genuinely noise-
shaped bucket: detections with NO decoded event code at all, sitting in
the ~50-60% confidence range. Default 0 keeps logging everything
(current behaviour) until an operator opts in.

Revision ID: 20260814_eas_dedup_settings
Revises: 20260814_add_led_graphics
Create Date: 2026-08-14
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260814_eas_dedup_settings"
down_revision = "20260814_add_led_graphics"
branch_labels = None
depends_on = None


def upgrade() -> None:
    from sqlalchemy import inspect

    conn = op.get_bind()
    inspector = inspect(conn)
    existing_cols = {c["name"] for c in inspector.get_columns("eas_settings")}

    if "cross_source_dedup_minutes" not in existing_cols:
        op.add_column(
            "eas_settings",
            sa.Column("cross_source_dedup_minutes", sa.Integer(), nullable=False, server_default="15"),
        )
    if "header_key_dedup_minutes" not in existing_cols:
        op.add_column(
            "eas_settings",
            sa.Column("header_key_dedup_minutes", sa.Integer(), nullable=False, server_default="1440"),
        )
    if "min_log_confidence_percent" not in existing_cols:
        op.add_column(
            "eas_settings",
            sa.Column("min_log_confidence_percent", sa.Float(), nullable=False, server_default="0.0"),
        )


def downgrade() -> None:
    from sqlalchemy import inspect

    conn = op.get_bind()
    inspector = inspect(conn)
    existing_cols = {c["name"] for c in inspector.get_columns("eas_settings")}

    for col in ("min_log_confidence_percent", "header_key_dedup_minutes", "cross_source_dedup_minutes"):
        if col in existing_cols:
            op.drop_column("eas_settings", col)
