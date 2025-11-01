from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20241210_add_nws_zone_catalog"
down_revision = "20241205_add_location_fips_codes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "nws_zones",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("zone_code", sa.String(length=6), nullable=False, unique=True),
        sa.Column("state_code", sa.String(length=2), nullable=False),
        sa.Column("zone_number", sa.String(length=3), nullable=False),
        sa.Column("zone_type", sa.String(length=1), nullable=False, server_default="Z"),
        sa.Column("cwa", sa.String(length=9), nullable=False),
        sa.Column("time_zone", sa.String(length=2)),
        sa.Column("fe_area", sa.String(length=4)),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("short_name", sa.String(length=64)),
        sa.Column("state_zone", sa.String(length=5), nullable=False),
        sa.Column("longitude", sa.Float),
        sa.Column("latitude", sa.Float),
    )
    op.create_index("ix_nws_zones_state_code", "nws_zones", ["state_code"])
    op.create_index("ix_nws_zones_cwa", "nws_zones", ["cwa"])
    op.create_index("ix_nws_zones_state_zone", "nws_zones", ["state_zone"])
    op.alter_column("nws_zones", "zone_type", server_default=None)


def downgrade() -> None:
    op.drop_index("ix_nws_zones_state_zone", table_name="nws_zones")
    op.drop_index("ix_nws_zones_cwa", table_name="nws_zones")
    op.drop_index("ix_nws_zones_state_code", table_name="nws_zones")
    op.drop_table("nws_zones")
