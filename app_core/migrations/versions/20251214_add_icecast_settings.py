"""Add icecast_settings table

Revision ID: 20251214_add_icecast_settings
Revises: 20251214_add_hardware_settings
Create Date: 2025-12-14

"""
from alembic import op
import sqlalchemy as sa
import os


# revision identifiers, used by Alembic.
revision = '20251214_add_icecast_settings'
down_revision = '20251214_add_hardware_settings'
branch_labels = None
depends_on = None


def _parse_bool(value, default=False):
    """Parse boolean from environment variable."""
    if not value:
        return default
    return str(value).lower() in ('true', '1', 'yes', 'on', 'enabled')


def _parse_int(value, default=0):
    """Parse integer from environment variable."""
    if not value:
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def upgrade():
    # Check if table already exists (idempotent migration)
    connection = op.get_bind()
    inspector = sa.inspect(connection)
    
    if 'icecast_settings' in inspector.get_table_names():
        print("icecast_settings table already exists, skipping creation")
        return
    
    # Create icecast_settings table
    op.create_table(
        'icecast_settings',
        sa.Column('id', sa.Integer(), nullable=False),

        # Connection Settings
        sa.Column('enabled', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('server', sa.String(length=255), nullable=False, server_default='localhost'),
        sa.Column('port', sa.Integer(), nullable=False, server_default='8000'),
        sa.Column('external_port', sa.Integer(), nullable=True),
        sa.Column('public_hostname', sa.String(length=255), nullable=True),

        # Authentication
        sa.Column('source_password', sa.String(length=255), nullable=False, server_default=''),
        sa.Column('admin_user', sa.String(length=255), nullable=True),
        sa.Column('admin_password', sa.String(length=255), nullable=True),

        # Stream Settings
        sa.Column('default_mount', sa.String(length=255), nullable=False, server_default='monitor.mp3'),
        sa.Column('stream_name', sa.String(length=255), nullable=False, server_default='EAS Station Audio'),
        sa.Column('stream_description', sa.String(length=500), nullable=False, server_default='Emergency Alert System Audio Monitor'),
        sa.Column('stream_genre', sa.String(length=100), nullable=False, server_default='Emergency'),
        sa.Column('stream_bitrate', sa.Integer(), nullable=False, server_default='128'),
        sa.Column('stream_format', sa.String(length=10), nullable=False, server_default='mp3'),
        sa.Column('stream_public', sa.Boolean(), nullable=False, server_default='false'),

        # Metadata
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),

        sa.PrimaryKeyConstraint('id')
    )

    # Populate from environment variables
    connection = op.get_bind()

    # Read current environment variables
    enabled = _parse_bool(os.getenv('ICECAST_ENABLED'), True)
    server = os.getenv('ICECAST_SERVER', 'localhost')
    port = _parse_int(os.getenv('ICECAST_PORT'), 8000)
    external_port = _parse_int(os.getenv('ICECAST_EXTERNAL_PORT')) if os.getenv('ICECAST_EXTERNAL_PORT') else None
    public_hostname = os.getenv('ICECAST_PUBLIC_HOSTNAME') or os.getenv('PUBLIC_HOSTNAME')

    # Authentication
    source_password = os.getenv('ICECAST_SOURCE_PASSWORD', '')
    admin_user = os.getenv('ICECAST_ADMIN_USER')
    admin_password = os.getenv('ICECAST_ADMIN_PASSWORD')

    # Stream settings
    default_mount = os.getenv('ICECAST_DEFAULT_MOUNT', 'monitor.mp3')
    stream_name = os.getenv('ICECAST_STREAM_NAME', 'EAS Station Audio')
    stream_description = os.getenv('ICECAST_STREAM_DESCRIPTION', 'Emergency Alert System Audio Monitor')
    stream_genre = os.getenv('ICECAST_STREAM_GENRE', 'Emergency')
    stream_bitrate = _parse_int(os.getenv('ICECAST_STREAM_BITRATE'), 128)
    stream_format = os.getenv('ICECAST_STREAM_FORMAT', 'mp3')
    stream_public = _parse_bool(os.getenv('ICECAST_STREAM_PUBLIC'), False)

    # Insert single settings row with id=1
    connection.execute(
        sa.text("""
            INSERT INTO icecast_settings (
                id,
                enabled, server, port, external_port, public_hostname,
                source_password, admin_user, admin_password,
                default_mount, stream_name, stream_description, stream_genre,
                stream_bitrate, stream_format, stream_public
            ) VALUES (
                1,
                :enabled, :server, :port, :external_port, :public_hostname,
                :source_password, :admin_user, :admin_password,
                :default_mount, :stream_name, :stream_description, :stream_genre,
                :stream_bitrate, :stream_format, :stream_public
            )
        """),
        {
            'enabled': enabled,
            'server': server,
            'port': port,
            'external_port': external_port,
            'public_hostname': public_hostname,
            'source_password': source_password,
            'admin_user': admin_user,
            'admin_password': admin_password,
            'default_mount': default_mount,
            'stream_name': stream_name,
            'stream_description': stream_description,
            'stream_genre': stream_genre,
            'stream_bitrate': stream_bitrate,
            'stream_format': stream_format,
            'stream_public': stream_public,
        }
    )


def downgrade():
    op.drop_table('icecast_settings')
