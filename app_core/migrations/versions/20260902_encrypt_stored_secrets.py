"""Widen stored-credential columns from VARCHAR to TEXT for at-rest encryption.

These columns now go through app_core.crypto.EncryptedString, which
encrypts on write and decrypts on read. Fernet ciphertext (plus the "enc:v1:"
version prefix) runs noticeably longer than the plaintext it replaces, so a
fixed-length VARCHAR sized for the old plaintext would truncate long keys.
Existing plaintext rows are left as-is -- EncryptedString treats any value
without the version prefix as legacy plaintext and encrypts it automatically
the next time it's saved, so no data migration/backfill is needed here.

Revision ID: 20260902_encrypt_stored_secrets
Revises: 20260831_system_log_retention
Create Date: 2026-09-02
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260902_encrypt_stored_secrets"
down_revision = "20260831_system_log_retention"
branch_labels = None
depends_on = None

# (table, column, old VARCHAR length)
_COLUMNS = [
    ("icecast_settings", "source_password", 255),
    ("icecast_settings", "admin_password", 255),
    ("tts_settings", "azure_openai_key", 500),
    ("notification_settings", "smtp_password", 255),
    ("notification_settings", "sms_auth_token", 255),
    ("notification_settings", "snmp_community", 255),
    ("tailscale_settings", "auth_key", 500),
    ("tickstem_settings", "api_key", 500),
    ("admin_users", "mfa_secret", 255),
]


def upgrade() -> None:
    for table, column, old_length in _COLUMNS:
        op.alter_column(
            table,
            column,
            existing_type=sa.String(length=old_length),
            type_=sa.Text(),
        )


def downgrade() -> None:
    # Postgres raises rather than silently truncating if an existing
    # (encrypted, therefore longer) value doesn't fit back into the old
    # VARCHAR length -- decrypt/re-save affected rows as plaintext first if
    # this downgrade needs to run against a database with encrypted data.
    for table, column, old_length in _COLUMNS:
        op.alter_column(
            table,
            column,
            existing_type=sa.Text(),
            type_=sa.String(length=old_length),
        )
