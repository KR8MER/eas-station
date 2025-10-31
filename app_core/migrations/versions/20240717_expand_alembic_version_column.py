"""Expand alembic_version.version_num column to support longer migration names."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "20240717_expand_alembic_version"
down_revision = "20240510_eas_audio_decodes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Get database connection and inspector
    conn = op.get_bind()
    inspector = inspect(conn)

    # Check the current column type
    columns = inspector.get_columns('alembic_version')
    version_num_col = next((col for col in columns if col['name'] == 'version_num'), None)

    # Only alter if the column exists and is still VARCHAR(32) or smaller
    if version_num_col:
        # Get the current length - check if it needs expansion
        current_type = version_num_col['type']
        # Check if it's a string type with length < 255
        if hasattr(current_type, 'length') and current_type.length and current_type.length < 255:
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
