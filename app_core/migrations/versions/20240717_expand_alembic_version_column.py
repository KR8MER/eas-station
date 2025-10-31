"""Expand alembic_version.version_num column to support longer migration names."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20240717_expand_alembic_version"
down_revision = "20240510_eas_audio_decodes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Expand the alembic_version.version_num column from VARCHAR(32) to VARCHAR(255)
    # This is needed because some migration names exceed 32 characters
    op.alter_column(
        "alembic_version",
        "version_num",
        existing_type=sa.String(length=32),
        type_=sa.String(length=255),
        existing_nullable=False,
    )


def downgrade() -> None:
    # Revert back to VARCHAR(32)
    # Note: This may fail if there are version strings longer than 32 characters
    op.alter_column(
        "alembic_version",
        "version_num",
        existing_type=sa.String(length=255),
        type_=sa.String(length=32),
        existing_nullable=False,
    )
