"""Add optional pre/post spoken announcement fields to rwt_schedule_config.

Adds pre_announcement_enabled/pre_announcement_text and
post_announcement_enabled/post_announcement_text so the automated weekly
RWT can bracket the SAME header/EOM with station courtesy announcements
(e.g. "This station is conducting a test of the Emergency Alert System" /
"This concludes this test of the Emergency Alert System").

Revision ID: 20260828_rwt_test_announcements
Revises: 20260822_tickstem_settings
Create Date: 2026-08-28
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260828_rwt_test_announcements"
down_revision = "20260822_tickstem_settings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    from sqlalchemy import inspect
    conn = op.get_bind()
    inspector = inspect(conn)

    if "rwt_schedule_config" not in inspector.get_table_names():
        return

    existing_cols = {c["name"] for c in inspector.get_columns("rwt_schedule_config")}

    if "pre_announcement_enabled" not in existing_cols:
        op.add_column(
            "rwt_schedule_config",
            sa.Column(
                "pre_announcement_enabled",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            ),
        )
    if "pre_announcement_text" not in existing_cols:
        op.add_column(
            "rwt_schedule_config",
            sa.Column("pre_announcement_text", sa.Text(), nullable=True),
        )
    if "post_announcement_enabled" not in existing_cols:
        op.add_column(
            "rwt_schedule_config",
            sa.Column(
                "post_announcement_enabled",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            ),
        )
    if "post_announcement_text" not in existing_cols:
        op.add_column(
            "rwt_schedule_config",
            sa.Column("post_announcement_text", sa.Text(), nullable=True),
        )


def downgrade() -> None:
    from sqlalchemy import inspect
    conn = op.get_bind()
    inspector = inspect(conn)

    if "rwt_schedule_config" not in inspector.get_table_names():
        return

    existing_cols = {c["name"] for c in inspector.get_columns("rwt_schedule_config")}

    for col in (
        "post_announcement_text",
        "post_announcement_enabled",
        "pre_announcement_text",
        "pre_announcement_enabled",
    ):
        if col in existing_cols:
            op.drop_column("rwt_schedule_config", col)
