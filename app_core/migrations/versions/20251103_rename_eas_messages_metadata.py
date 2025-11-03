"""Rename eas_messages.metadata column to metadata_payload

This migration renames the 'metadata' column in the eas_messages table to
'metadata_payload' to avoid conflicts with SQLAlchemy's reserved 'metadata'
attribute when using the Declarative API.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20251103_rename_eas_messages_metadata"
down_revision = "20241210_add_nws_zone_catalog"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Rename metadata column to metadata_payload in eas_messages table."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # Check if the table exists
    if "eas_messages" in inspector.get_table_names():
        columns = [col["name"] for col in inspector.get_columns("eas_messages")]

        # Only rename if the old column exists and the new one doesn't
        if "metadata" in columns and "metadata_payload" not in columns:
            op.alter_column(
                "eas_messages",
                "metadata",
                new_column_name="metadata_payload"
            )


def downgrade() -> None:
    """Revert metadata_payload column back to metadata."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # Check if the table exists
    if "eas_messages" in inspector.get_table_names():
        columns = [col["name"] for col in inspector.get_columns("eas_messages")]

        # Only rename if the new column exists and the old one doesn't
        if "metadata_payload" in columns and "metadata" not in columns:
            op.alter_column(
                "eas_messages",
                "metadata_payload",
                new_column_name="metadata"
            )
