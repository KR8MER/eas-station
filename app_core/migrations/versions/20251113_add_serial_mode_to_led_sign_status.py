"""Add serial communication mode tracking to LED sign status.

Revision ID: 20251113_add_serial_mode_to_led_sign_status
Revises: 20251111_add_received_eas_alerts
Create Date: 2025-11-13
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "20251113_add_serial_mode_to_led_sign_status"
down_revision = "20251111_add_received_eas_alerts"
branch_labels = None
depends_on = None


LED_STATUS_TABLE = "led_sign_status"
SERIAL_MODE_COLUMN = "serial_mode"
DEFAULT_SERIAL_MODE = "RS232"


def upgrade() -> None:
    """Add the serial_mode column to LED sign status if it is missing."""
    bind = op.get_bind()
    inspector = inspect(bind)

    if LED_STATUS_TABLE not in inspector.get_table_names():
        # Table has not been created yet; nothing to do.
        return

    columns = {column["name"] for column in inspector.get_columns(LED_STATUS_TABLE)}

    if SERIAL_MODE_COLUMN not in columns:
        op.add_column(
            LED_STATUS_TABLE,
            sa.Column(
                SERIAL_MODE_COLUMN,
                sa.String(length=10),
                nullable=True,
                server_default=DEFAULT_SERIAL_MODE,
            ),
        )

        # Populate any existing rows with the default value and then enforce non-null.
        op.execute(
            sa.text(
                f"UPDATE {LED_STATUS_TABLE} SET {SERIAL_MODE_COLUMN} = :default"
                f" WHERE {SERIAL_MODE_COLUMN} IS NULL"
            ),
            {"default": DEFAULT_SERIAL_MODE},
        )

        op.alter_column(
            LED_STATUS_TABLE,
            SERIAL_MODE_COLUMN,
            existing_type=sa.String(length=10),
            nullable=False,
            server_default=None,
        )


def downgrade() -> None:
    """Drop the serial_mode column from LED sign status if it exists."""
    bind = op.get_bind()
    inspector = inspect(bind)

    if LED_STATUS_TABLE not in inspector.get_table_names():
        return

    columns = {column["name"] for column in inspector.get_columns(LED_STATUS_TABLE)}

    if SERIAL_MODE_COLUMN in columns:
        op.drop_column(LED_STATUS_TABLE, SERIAL_MODE_COLUMN)
