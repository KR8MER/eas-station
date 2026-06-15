"""Merge the parallel migration heads prior to the traffic-analytics tables.

Several in-flight feature branches each added a migration off a different
parent, leaving the revision graph with multiple heads. Alembic ``upgrade head``
(singular) requires exactly one head, so this empty merge migration unifies them
before the web-traffic analytics tables are added on top.

Revision ID: 20260615_merge_heads_for_traffic
Create Date: 2026-06-15
"""

from __future__ import annotations

revision = "20260615_merge_heads_for_traffic"
down_revision = (
    "20260512_add_external_lna_db_to_radio_receivers",
    "20260506_add_signal_audio_to_activations",
    "20260615_cap_alert_cancelled_at",
    "20260509_add_gps_source_columns",
    "20260505_add_mdc1200_target_unit_id_to_eas_settings",
)
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Merge migrations have empty bodies."""
    pass


def downgrade() -> None:
    """Merge migrations have empty bodies."""
    pass
