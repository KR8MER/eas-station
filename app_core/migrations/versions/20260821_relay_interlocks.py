"""Add relay_interlock_groups and relay_interlock_members tables.

Mutual-exclusion groups of GPIO relay pins: enforcement guarantees no more
than one pin in a group is ever energized at once (e.g. two PTT relay lines
that must never key simultaneous transmitters).

Revision ID: 20260821_relay_interlocks
Revises: 20260820_widen_alembic_version
Create Date: 2026-08-21

Note: kept short (<=32 chars) deliberately -- CI's fresh-database step runs
`alembic stamp head`, which creates the `alembic_version` table from
Alembic's own default VARCHAR(32) schema and inserts the head revision
directly (it never replays `20260820_widen_alembic_version`'s ALTER COLUMN,
since stamp doesn't run migration bodies). Only the *current head's* ID needs
to fit that default width for a fresh CI database to succeed.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260821_relay_interlocks"
down_revision = "20260820_widen_alembic_version"
branch_labels = None
depends_on = None

_GROUPS_TABLE = "relay_interlock_groups"
_MEMBERS_TABLE = "relay_interlock_members"


def upgrade() -> None:
    from sqlalchemy import inspect

    conn = op.get_bind()
    inspector = inspect(conn)
    existing = inspector.get_table_names()

    if _GROUPS_TABLE not in existing:
        op.create_table(
            _GROUPS_TABLE,
            sa.Column("id", sa.Integer(), nullable=False, primary_key=True),
            sa.Column("name", sa.String(length=100), nullable=False),
            sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
            sa.Column(
                "force_deactivate_conflict",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("false"),
            ),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
            sa.UniqueConstraint("name", name="uq_relay_interlock_groups_name"),
        )

    if _MEMBERS_TABLE not in existing:
        op.create_table(
            _MEMBERS_TABLE,
            sa.Column("id", sa.Integer(), nullable=False, primary_key=True),
            sa.Column(
                "group_id",
                sa.Integer(),
                sa.ForeignKey(f"{_GROUPS_TABLE}.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("pin", sa.Integer(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.UniqueConstraint(
                "group_id", "pin", name="uq_relay_interlock_member_group_pin"
            ),
        )
        op.create_index(
            "ix_relay_interlock_members_group_id", _MEMBERS_TABLE, ["group_id"]
        )
        op.create_index(
            "ix_relay_interlock_members_pin", _MEMBERS_TABLE, ["pin"]
        )


def downgrade() -> None:
    from sqlalchemy import inspect

    conn = op.get_bind()
    inspector = inspect(conn)
    existing = inspector.get_table_names()

    if _MEMBERS_TABLE in existing:
        op.drop_table(_MEMBERS_TABLE)
    if _GROUPS_TABLE in existing:
        op.drop_table(_GROUPS_TABLE)
