"""Add RBAC (roles, permissions) and MFA support.

Revision ID: 20251105_add_rbac_and_mfa
Revises: 20251105_add_gpio_activation_logs
Create Date: 2025-11-05
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect
from sqlalchemy.dialects import postgresql


revision = "20251105_add_rbac_and_mfa"
down_revision = "20251105_add_gpio_activation_logs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add RBAC tables, audit logs, and MFA fields."""
    conn = op.get_bind()
    inspector = inspect(conn)

    # Create roles table
    if "roles" not in inspector.get_table_names():
        op.create_table(
            "roles",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("name", sa.String(length=64), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("name"),
        )
        op.create_index(op.f("ix_roles_name"), "roles", ["name"], unique=False)

    # Create permissions table
    if "permissions" not in inspector.get_table_names():
        op.create_table(
            "permissions",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("name", sa.String(length=128), nullable=False),
            sa.Column("resource", sa.String(length=64), nullable=False),
            sa.Column("action", sa.String(length=64), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("name"),
        )
        op.create_index(op.f("ix_permissions_name"), "permissions", ["name"], unique=False)

    # Create role_permissions association table
    if "role_permissions" not in inspector.get_table_names():
        op.create_table(
            "role_permissions",
            sa.Column("role_id", sa.Integer(), nullable=False),
            sa.Column("permission_id", sa.Integer(), nullable=False),
            sa.ForeignKeyConstraint(["permission_id"], ["permissions.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["role_id"], ["roles.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("role_id", "permission_id"),
        )

    # Create audit_logs table
    if "audit_logs" not in inspector.get_table_names():
        op.create_table(
            "audit_logs",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=True),
            sa.Column("username", sa.String(length=64), nullable=True),
            sa.Column("action", sa.String(length=128), nullable=False),
            sa.Column("resource_type", sa.String(length=64), nullable=True),
            sa.Column("resource_id", sa.String(length=128), nullable=True),
            sa.Column("ip_address", sa.String(length=45), nullable=True),
            sa.Column("user_agent", sa.String(length=512), nullable=True),
            sa.Column("success", sa.Boolean(), nullable=False),
            sa.Column("details", postgresql.JSON(astext_type=sa.Text()), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(op.f("ix_audit_logs_action"), "audit_logs", ["action"], unique=False)
        op.create_index(op.f("ix_audit_logs_resource_type"), "audit_logs", ["resource_type"], unique=False)
        op.create_index(op.f("ix_audit_logs_success"), "audit_logs", ["success"], unique=False)
        op.create_index(op.f("ix_audit_logs_timestamp"), "audit_logs", ["timestamp"], unique=False)
        op.create_index(op.f("ix_audit_logs_user_id"), "audit_logs", ["user_id"], unique=False)
        op.create_index("ix_audit_logs_user_action", "audit_logs", ["user_id", "action"], unique=False)
        op.create_index("ix_audit_logs_timestamp_action", "audit_logs", ["timestamp", "action"], unique=False)

    # Add MFA and role columns to admin_users table
    admin_users_columns = [col["name"] for col in inspector.get_columns("admin_users")]

    if "role_id" not in admin_users_columns:
        op.add_column("admin_users", sa.Column("role_id", sa.Integer(), nullable=True))
        op.create_foreign_key(
            "fk_admin_users_role_id",
            "admin_users",
            "roles",
            ["role_id"],
            ["id"],
            ondelete="SET NULL"
        )

    if "mfa_enabled" not in admin_users_columns:
        op.add_column("admin_users", sa.Column("mfa_enabled", sa.Boolean(), nullable=False, server_default="false"))

    if "mfa_secret" not in admin_users_columns:
        op.add_column("admin_users", sa.Column("mfa_secret", sa.String(length=255), nullable=True))

    if "mfa_backup_codes_hash" not in admin_users_columns:
        op.add_column("admin_users", sa.Column("mfa_backup_codes_hash", sa.Text(), nullable=True))

    if "mfa_enrolled_at" not in admin_users_columns:
        op.add_column("admin_users", sa.Column("mfa_enrolled_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    """Remove RBAC tables, audit logs, and MFA fields."""
    conn = op.get_bind()
    inspector = inspect(conn)

    # Remove columns from admin_users
    admin_users_columns = [col["name"] for col in inspector.get_columns("admin_users")]

    if "mfa_enrolled_at" in admin_users_columns:
        op.drop_column("admin_users", "mfa_enrolled_at")

    if "mfa_backup_codes_hash" in admin_users_columns:
        op.drop_column("admin_users", "mfa_backup_codes_hash")

    if "mfa_secret" in admin_users_columns:
        op.drop_column("admin_users", "mfa_secret")

    if "mfa_enabled" in admin_users_columns:
        op.drop_column("admin_users", "mfa_enabled")

    if "role_id" in admin_users_columns:
        op.drop_constraint("fk_admin_users_role_id", "admin_users", type_="foreignkey")
        op.drop_column("admin_users", "role_id")

    # Drop tables
    if "audit_logs" in inspector.get_table_names():
        op.drop_index("ix_audit_logs_timestamp_action", table_name="audit_logs")
        op.drop_index("ix_audit_logs_user_action", table_name="audit_logs")
        op.drop_index(op.f("ix_audit_logs_user_id"), table_name="audit_logs")
        op.drop_index(op.f("ix_audit_logs_timestamp"), table_name="audit_logs")
        op.drop_index(op.f("ix_audit_logs_success"), table_name="audit_logs")
        op.drop_index(op.f("ix_audit_logs_resource_type"), table_name="audit_logs")
        op.drop_index(op.f("ix_audit_logs_action"), table_name="audit_logs")
        op.drop_table("audit_logs")

    if "role_permissions" in inspector.get_table_names():
        op.drop_table("role_permissions")

    if "permissions" in inspector.get_table_names():
        op.drop_index(op.f("ix_permissions_name"), table_name="permissions")
        op.drop_table("permissions")

    if "roles" in inspector.get_table_names():
        op.drop_index(op.f("ix_roles_name"), table_name="roles")
        op.drop_table("roles")
