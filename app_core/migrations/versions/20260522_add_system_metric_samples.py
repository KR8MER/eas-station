"""Add system_metric_samples table for persistent dashboard trends.

Revision ID: 20260522_add_system_metric_samples
Revises: 20260522_add_backup_dir_to_application_settings
Create Date: 2026-05-22

Persists high-frequency system-health samples (CPU, memory, load, storage,
temperature, network counters) so the system-info dashboard's Performance
Trends chart and sparklines can show meaningful history even when the page
was not open while metrics were being collected.

The table is intentionally narrow and indexed only by ``recorded_at`` for
range scans by the history API.  A background sampler retains roughly the
last 30 days of samples; downsampling is performed at read time.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "20260522_add_system_metric_samples"
down_revision = "20260522_add_backup_dir_to_application_settings"
branch_labels = None
depends_on = None


def _table_exists(table_name: str) -> bool:
    conn = op.get_bind()
    inspector = inspect(conn)
    try:
        return table_name in inspector.get_table_names()
    except Exception:
        return False


def upgrade():
    if _table_exists("system_metric_samples"):
        return

    op.create_table(
        "system_metric_samples",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("cpu_percent", sa.Float(), nullable=True),
        sa.Column("memory_percent", sa.Float(), nullable=True),
        sa.Column("swap_percent", sa.Float(), nullable=True),
        sa.Column("load_1m", sa.Float(), nullable=True),
        sa.Column("load_5m", sa.Float(), nullable=True),
        sa.Column("load_15m", sa.Float(), nullable=True),
        sa.Column("storage_percent", sa.Float(), nullable=True),
        sa.Column("temperature_c", sa.Float(), nullable=True),
        sa.Column("net_rx_bytes", sa.BigInteger(), nullable=True),
        sa.Column("net_tx_bytes", sa.BigInteger(), nullable=True),
    )
    op.create_index(
        "ix_system_metric_samples_recorded_at",
        "system_metric_samples",
        ["recorded_at"],
    )


def downgrade():
    if not _table_exists("system_metric_samples"):
        return
    op.drop_index(
        "ix_system_metric_samples_recorded_at",
        table_name="system_metric_samples",
    )
    op.drop_table("system_metric_samples")
