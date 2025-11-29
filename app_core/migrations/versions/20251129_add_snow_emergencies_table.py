"""Add snow_emergencies table for local snow emergency tracking.

Revision ID: 20251129_add_snow_emergencies_table
Revises: 20251127_add_eas_forwarding_tracking
Create Date: 2025-11-29

This migration adds the snow_emergencies table to track current snow emergency
levels for Putnam County and adjoining counties in Ohio. Simple one-row-per-county
tracking with history in JSONB.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect
from sqlalchemy.dialects.postgresql import JSONB


revision = "20251129_add_snow_emergencies_table"
down_revision = "20251127_add_eas_forwarding_tracking"
branch_labels = None
depends_on = None


SNOW_EMERGENCIES_TABLE = "snow_emergencies"

# Counties to initialize (Putnam and adjoining counties in Ohio)
INITIAL_COUNTIES = [
    ("039137", "Putnam", "OH"),
    ("039003", "Allen", "OH"),
    ("039011", "Auglaize", "OH"),
    ("039039", "Defiance", "OH"),
    ("039063", "Hancock", "OH"),
    ("039069", "Henry", "OH"),
    ("039125", "Paulding", "OH"),
    ("039161", "Van Wert", "OH"),
]


def _table_exists(table_name: str) -> bool:
    """Check if a table exists in the database."""
    conn = op.get_bind()
    inspector = inspect(conn)
    try:
        return table_name in inspector.get_table_names()
    except Exception:
        return False


def upgrade() -> None:
    """Create snow_emergencies table for local snow emergency tracking."""
    if _table_exists(SNOW_EMERGENCIES_TABLE):
        return  # Table already exists, skip creation

    op.create_table(
        SNOW_EMERGENCIES_TABLE,
        # Primary key
        sa.Column("id", sa.Integer(), nullable=False),
        
        # County identification (unique per county)
        sa.Column("county_fips", sa.String(length=6), nullable=False, unique=True),
        sa.Column("county_name", sa.String(length=128), nullable=False),
        sa.Column("state_code", sa.String(length=2), nullable=False, server_default="OH"),
        
        # Current snow emergency level (0 = none, 1-3 = emergency levels)
        sa.Column("level", sa.Integer(), nullable=False, server_default="0"),
        
        # When the current level was set
        sa.Column(
            "level_set_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        
        # Who set the current level (username)
        sa.Column("level_set_by", sa.String(length=128), nullable=True),
        
        # Audit fields
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        
        # History tracking
        sa.Column("history", JSONB, nullable=True, server_default="[]"),
        
        # Primary key constraint
        sa.PrimaryKeyConstraint("id"),
    )

    # Create index on county_fips
    op.create_index(
        "ix_snow_emergencies_county_fips",
        SNOW_EMERGENCIES_TABLE,
        ["county_fips"],
        unique=True,
    )

    # Initialize with all counties at level 0
    # Using SQLAlchemy table construct to avoid any SQL injection concerns
    snow_table = sa.table(
        SNOW_EMERGENCIES_TABLE,
        sa.column("county_fips", sa.String),
        sa.column("county_name", sa.String),
        sa.column("state_code", sa.String),
        sa.column("level", sa.Integer),
        sa.column("level_set_by", sa.String),
    )
    
    conn = op.get_bind()
    for county_fips, county_name, state_code in INITIAL_COUNTIES:
        # Check if already exists before inserting
        result = conn.execute(
            sa.select(snow_table.c.county_fips).where(
                snow_table.c.county_fips == county_fips
            )
        ).fetchone()
        
        if not result:
            conn.execute(
                snow_table.insert().values(
                    county_fips=county_fips,
                    county_name=county_name,
                    state_code=state_code,
                    level=0,
                    level_set_by="System",
                )
            )


def downgrade() -> None:
    """Drop snow_emergencies table."""
    if _table_exists(SNOW_EMERGENCIES_TABLE):
        op.drop_index("ix_snow_emergencies_county_fips", table_name=SNOW_EMERGENCIES_TABLE)
        op.drop_table(SNOW_EMERGENCIES_TABLE)
