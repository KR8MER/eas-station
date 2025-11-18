"""Add RWT schedule configuration table

Revision ID: 20251118_add_rwt_schedule_config
Revises: 20251107_add_tone_and_narration
Create Date: 2025-11-18

This migration adds the rwt_schedule_config table to store automatic
Required Weekly Test (RWT) scheduling configuration. Administrators can
configure automatic RWT broadcasts on specific days of the week and time
windows.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect
from sqlalchemy.dialects.postgresql import JSONB


# revision identifiers, used by Alembic.
revision = '20251118_add_rwt_schedule_config'
down_revision = '20251107_add_tone_and_narration'
branch_labels = None
depends_on = None


def _table_exists(table_name: str) -> bool:
    """Check if a table exists in the database.

    Args:
        table_name: Name of the table to check

    Returns:
        True if the table exists, False otherwise
    """
    conn = op.get_bind()
    inspector = inspect(conn)
    try:
        return table_name in inspector.get_table_names()
    except Exception:  # pragma: no cover - reflection failure
        return False


def upgrade():
    """Create rwt_schedule_config table."""
    if _table_exists("rwt_schedule_config"):
        return  # Table already exists, skip creation

    op.create_table(
        "rwt_schedule_config",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default='true'),
        sa.Column("days_of_week", JSONB, nullable=False, server_default='[]'),
        sa.Column("start_hour", sa.Integer(), nullable=False, server_default='8'),
        sa.Column("start_minute", sa.Integer(), nullable=False, server_default='0'),
        sa.Column("end_hour", sa.Integer(), nullable=False, server_default='16'),
        sa.Column("end_minute", sa.Integer(), nullable=False, server_default='0'),
        sa.Column("same_codes", JSONB, nullable=False, server_default='[]'),
        sa.Column("originator", sa.String(length=3), nullable=False, server_default='WXR'),
        sa.Column("station_id", sa.String(length=8), nullable=False, server_default='EASNODES'),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_run_status", sa.String(length=20), nullable=True),
        sa.Column("last_run_details", JSONB, nullable=True),
        sa.PrimaryKeyConstraint("id")
    )


def downgrade():
    """Drop rwt_schedule_config table."""
    if _table_exists("rwt_schedule_config"):
        op.drop_table("rwt_schedule_config")
