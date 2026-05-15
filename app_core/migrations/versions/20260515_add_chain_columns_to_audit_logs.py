"""Add tamper-evident chain columns to the existing ``audit_logs`` table.

This migration extends the existing security ``audit_logs`` table (created by
``20251105_add_rbac_and_mfa``) with three nullable columns that turn it into a
cryptographically chained ledger:

* ``prev_hash``  -- hex SHA-256 of the previous row's ``entry_hash``
* ``entry_hash`` -- hex SHA-256 over the canonical-JSON of the row's content
                    fields plus ``prev_hash`` (Merkle-style chain)
* ``signature``  -- Ed25519 signature over ``entry_hash``, hex-encoded

We deliberately reuse the existing table instead of creating a parallel
"audit ledger" table, because the existing ``AuditLog`` model already has the
right shape (timestamp + user + action + resource + details JSON), already
has a viewer page at ``/admin/audit-logs``, and already has retention plumbing
via ``AuditLogger.cleanup_old_logs``.  A second table would just clutter the
admin menu without adding information.

All three columns are nullable so:

* pre-migration rows stay valid (the chain effectively starts at the first
  new row after upgrade),
* a deployment that hasn't yet provisioned a signing key can still write
  audit rows -- the chain integrity check will simply report those rows as
  unsigned until a key is configured.

Revision ID: 20260515_add_chain_columns_to_audit_logs
Revises: 20260513_add_bias_t_enabled_to_radio_receivers
Create Date: 2026-05-15
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "20260515_add_chain_columns_to_audit_logs"
down_revision = "20260513_add_bias_t_enabled_to_radio_receivers"
branch_labels = None
depends_on = None


TABLE_NAME = "audit_logs"
NEW_COLUMNS = ("prev_hash", "entry_hash", "signature")


def _table_exists(bind, table_name: str) -> bool:
    inspector = inspect(bind)
    return table_name in inspector.get_table_names()


def _existing_columns(bind, table_name: str) -> set[str]:
    inspector = inspect(bind)
    return {column["name"] for column in inspector.get_columns(table_name)}


def upgrade() -> None:
    bind = op.get_bind()
    if not _table_exists(bind, TABLE_NAME):
        # The base RBAC/MFA migration hasn't run yet; nothing to extend.
        return

    existing = _existing_columns(bind, TABLE_NAME)

    if "prev_hash" not in existing:
        # 64 hex chars for SHA-256; allow NULL so the very first row in the
        # chain (and pre-migration rows) doesn't need a synthetic predecessor.
        op.add_column(
            TABLE_NAME,
            sa.Column("prev_hash", sa.String(length=64), nullable=True),
        )

    if "entry_hash" not in existing:
        op.add_column(
            TABLE_NAME,
            sa.Column("entry_hash", sa.String(length=64), nullable=True),
        )
        op.create_index(
            "ix_audit_logs_entry_hash",
            TABLE_NAME,
            ["entry_hash"],
            unique=False,
        )

    if "signature" not in existing:
        # Ed25519 signature is 64 bytes; hex-encoded that is 128 chars.  We
        # size to 256 for headroom in case we later add a key-id prefix
        # ("ed25519:<keyid>:<hex>") without needing another migration.
        op.add_column(
            TABLE_NAME,
            sa.Column("signature", sa.String(length=256), nullable=True),
        )


def downgrade() -> None:
    bind = op.get_bind()
    if not _table_exists(bind, TABLE_NAME):
        return

    existing = _existing_columns(bind, TABLE_NAME)

    if "signature" in existing:
        op.drop_column(TABLE_NAME, "signature")

    if "entry_hash" in existing:
        try:
            op.drop_index("ix_audit_logs_entry_hash", table_name=TABLE_NAME)
        except Exception:
            # Index may not exist if a prior partial downgrade ran; safe to
            # ignore -- the column drop below is the authoritative cleanup.
            pass
        op.drop_column(TABLE_NAME, "entry_hash")

    if "prev_hash" in existing:
        op.drop_column(TABLE_NAME, "prev_hash")
