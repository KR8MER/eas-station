"""Add attention tone and narration audio segments to decoded audio

Revision ID: 20251107_add_tone_and_narration
Revises: 20251106_remove_stream_support_from_receivers
Create Date: 2025-11-07

This migration adds proper segment separation for EAS audio analysis:
- attention_tone_audio_data: EBS two-tone or NWS 1050Hz tone
- narration_audio_data: Voice narration segment

The old 'message_audio_data' column is kept for backward compatibility
but is now deprecated in favor of separated narration and tone segments.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision = '20251107_add_tone_and_narration'
down_revision = '20251106_remove_stream_support_from_receivers'
branch_labels = None
depends_on = None


def _existing_columns(table_name: str) -> set[str]:
    """Return the existing column names for ``table_name``.

    A helper is used so both upgrade and downgrade paths can share the
    reflection logic while keeping the migration idempotent when it is
    re-run after a partial deployment.
    """

    conn = op.get_bind()
    inspector = inspect(conn)
    try:
        return {col["name"] for col in inspector.get_columns(table_name)}
    except Exception:  # pragma: no cover - reflection failure surfaces original error
        return set()


def upgrade():
    """Add attention_tone_audio_data and narration_audio_data columns."""
    existing = _existing_columns("eas_decoded_audio")

    if "attention_tone_audio_data" not in existing:
        # Add new columns for proper segment separation
        op.add_column(
            "eas_decoded_audio",
            sa.Column("attention_tone_audio_data", sa.LargeBinary(), nullable=True),
        )

    if "narration_audio_data" not in existing:
        op.add_column(
            "eas_decoded_audio",
            sa.Column("narration_audio_data", sa.LargeBinary(), nullable=True),
        )

    # Note: message_audio_data column is kept for backward compatibility
    # but new decodes will use attention_tone_audio_data and narration_audio_data instead


def downgrade():
    """Remove attention_tone_audio_data and narration_audio_data columns."""
    existing = _existing_columns("eas_decoded_audio")

    if "narration_audio_data" in existing:
        op.drop_column("eas_decoded_audio", "narration_audio_data")

    if "attention_tone_audio_data" in existing:
        op.drop_column("eas_decoded_audio", "attention_tone_audio_data")
