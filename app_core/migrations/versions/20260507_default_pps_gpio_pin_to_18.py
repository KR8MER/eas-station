"""Switch default GPS PPS GPIO pin from BCM 4 (Adafruit) to BCM 18 (Uputronics).

The Uputronics Raspberry Pi GPS/RTC Expansion Board routes its PPS signal to
BCM 18 and ships with a low-profile stacking header, allowing it to coexist
with I²C OLEDs (BCM 2/3) and fit inside a closed Pi case. The Adafruit
Ultimate GPS HAT (#2324) routes PPS to BCM 4 and uses a tall non-stacking
header, blocking those use cases.

This migration only changes the column ``server_default`` so that *new*
hardware_settings rows seeded after the upgrade pick BCM 18. Existing rows
keep whatever pin the operator already configured — they are not rewritten.

Revision ID: 20260507_default_pps_gpio_pin_to_18
Revises: 20260506_add_signal_audio_to_activations
Create Date: 2026-05-07
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260507_default_pps_gpio_pin_to_18"
down_revision = "20260506_add_signal_audio_to_activations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Update server_default for hardware_settings.gps_pps_gpio_pin to 18."""
    with op.batch_alter_table("hardware_settings") as batch_op:
        batch_op.alter_column(
            "gps_pps_gpio_pin",
            existing_type=sa.Integer(),
            existing_nullable=False,
            server_default="18",
        )


def downgrade() -> None:
    """Restore the previous Adafruit-oriented default of BCM 4."""
    with op.batch_alter_table("hardware_settings") as batch_op:
        batch_op.alter_column(
            "gps_pps_gpio_pin",
            existing_type=sa.Integer(),
            existing_nullable=False,
            server_default="4",
        )
