"""Create tables for radio receivers and status tracking."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20240229_radio"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "radio_receivers",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("identifier", sa.String(length=64), nullable=False),
        sa.Column("display_name", sa.String(length=128), nullable=False),
        sa.Column("driver", sa.String(length=64), nullable=False),
        sa.Column("frequency_hz", sa.Float(), nullable=False),
        sa.Column("sample_rate", sa.Integer(), nullable=False),
        sa.Column("gain", sa.Float(), nullable=True),
        sa.Column("channel", sa.Integer(), nullable=True),
        sa.Column("auto_start", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index(
        "idx_radio_receivers_identifier",
        "radio_receivers",
        ["identifier"],
        unique=True,
    )

    op.create_table(
        "radio_receiver_status",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("receiver_id", sa.Integer(), nullable=False),
        sa.Column("reported_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("locked", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("signal_strength", sa.Float(), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("capture_mode", sa.String(length=16), nullable=True),
        sa.Column("capture_path", sa.String(length=255), nullable=True),
        sa.ForeignKeyConstraint(["receiver_id"], ["radio_receivers.id"], ondelete="CASCADE"),
    )
    op.create_index(
        "idx_radio_receiver_status_receiver_id",
        "radio_receiver_status",
        ["receiver_id"],
    )
    op.create_index(
        "idx_radio_receiver_status_reported_at",
        "radio_receiver_status",
        ["reported_at"],
    )


def downgrade() -> None:
    op.drop_index("idx_radio_receiver_status_reported_at", table_name="radio_receiver_status")
    op.drop_index("idx_radio_receiver_status_receiver_id", table_name="radio_receiver_status")
    op.drop_table("radio_receiver_status")
    op.drop_index("idx_radio_receivers_identifier", table_name="radio_receivers")
    op.drop_table("radio_receivers")

