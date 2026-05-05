"""Merge MDC1200 target unit ID and signal audio branches.

Both 20260505_add_mdc1200_target_unit_id_to_eas_settings and
20260506_add_signal_audio_to_activations branch from
20260506_split_location_settings, creating two independent heads.
This merge migration collapses them back to a single head so that
``alembic upgrade head`` succeeds without ambiguity.

Revision ID: 20260506_merge_mdc1200_target_and_signal_audio
Revises: 20260505_add_mdc1200_target_unit_id_to_eas_settings,
         20260506_add_signal_audio_to_activations
Create Date: 2026-05-06
"""

from alembic import op


revision = "20260506_merge_mdc1200_target_and_signal_audio"
down_revision = (
    "20260505_add_mdc1200_target_unit_id_to_eas_settings",
    "20260506_add_signal_audio_to_activations",
)
branch_labels = None
depends_on = None


def upgrade():
    """Merge migration — no schema changes needed."""
    pass


def downgrade():
    """Merge migration — no schema changes needed."""
    pass
