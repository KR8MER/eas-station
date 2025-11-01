from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20241210_add_nws_zone_catalog"
down_revision = "20241205_add_location_fips_codes"
branch_labels = None
depends_on = None
TABLE_NAME = "nws_zones"
INDEX_DEFINITIONS = {
    "ix_nws_zones_state_code": ["state_code"],
    "ix_nws_zones_cwa": ["cwa"],
    "ix_nws_zones_state_zone": ["state_zone"],
}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if TABLE_NAME not in inspector.get_table_names():
        op.create_table(
            TABLE_NAME,
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
        inspector = sa.inspect(bind)

    if TABLE_NAME in inspector.get_table_names():
        existing_indexes = {index["name"] for index in inspector.get_indexes(TABLE_NAME)}
        for index_name, columns in INDEX_DEFINITIONS.items():
            if index_name not in existing_indexes:
                op.create_index(index_name, TABLE_NAME, columns)

        op.alter_column(TABLE_NAME, "zone_type", server_default=None)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if TABLE_NAME in inspector.get_table_names():
        existing_indexes = {index["name"] for index in inspector.get_indexes(TABLE_NAME)}
        for index_name in INDEX_DEFINITIONS:
            if index_name in existing_indexes:
                op.drop_index(index_name, table_name=TABLE_NAME)

        op.drop_table(TABLE_NAME)
