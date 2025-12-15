"""Add hardware_settings table

Revision ID: 20251214_add_hardware_settings
Revises: 20251205_add_audio_sample_rate
Create Date: 2025-12-14

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
import os
import json


# revision identifiers, used by Alembic.
revision = '20251214_add_hardware_settings'
down_revision = '20251205_add_audio_sample_rate'
branch_labels = None
depends_on = None


def _parse_bool(value, default=False):
    """Parse boolean from environment variable."""
    if not value:
        return default
    return str(value).lower() in ('true', '1', 'yes', 'on')


def _parse_int(value, default=0):
    """Parse integer from environment variable."""
    if not value:
        return default
    try:
        # Handle hex values like 0x3C
        if isinstance(value, str) and value.startswith('0x'):
            return int(value, 16)
        return int(value)
    except (TypeError, ValueError):
        return default


def _parse_float(value, default=0.0):
    """Parse float from environment variable."""
    if not value:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _parse_json(value, default=None):
    """Parse JSON from environment variable."""
    if not value or not value.strip():
        return default or {}
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return default or {}


def upgrade():
    # Check if table already exists (idempotent migration)
    connection = op.get_bind()
    inspector = sa.inspect(connection)
    
    if 'hardware_settings' in inspector.get_table_names():
        print("hardware_settings table already exists, skipping creation")
        return
    
    # Create hardware_settings table
    op.create_table(
        'hardware_settings',
        sa.Column('id', sa.Integer(), nullable=False),

        # GPIO Settings
        sa.Column('gpio_enabled', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('gpio_pin_map', postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default='{}'),
        sa.Column('gpio_behavior_matrix', postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default='{}'),

        # OLED Settings
        sa.Column('oled_enabled', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('oled_i2c_bus', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('oled_i2c_address', sa.Integer(), nullable=False, server_default='60'),  # 0x3C = 60
        sa.Column('oled_width', sa.Integer(), nullable=False, server_default='128'),
        sa.Column('oled_height', sa.Integer(), nullable=False, server_default='64'),
        sa.Column('oled_rotate', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('oled_contrast', sa.Integer(), nullable=True),
        sa.Column('oled_font_path', sa.String(length=255), nullable=True),
        sa.Column('oled_default_invert', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('oled_button_gpio', sa.Integer(), nullable=False, server_default='4'),
        sa.Column('oled_button_hold_seconds', sa.Float(), nullable=False, server_default='1.25'),
        sa.Column('oled_button_active_high', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('oled_scroll_effect', sa.String(length=50), nullable=False, server_default='scroll_left'),
        sa.Column('oled_scroll_speed', sa.Integer(), nullable=False, server_default='4'),
        sa.Column('oled_scroll_fps', sa.Integer(), nullable=False, server_default='30'),
        sa.Column('screens_auto_start', sa.Boolean(), nullable=False, server_default='true'),

        # LED Sign Settings
        sa.Column('led_enabled', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('led_connection_type', sa.String(length=20), nullable=False, server_default='network'),
        sa.Column('led_ip_address', sa.String(length=50), nullable=False, server_default='192.168.1.100'),
        sa.Column('led_port', sa.Integer(), nullable=False, server_default='10001'),
        sa.Column('led_serial_port', sa.String(length=100), nullable=False, server_default='/dev/ttyUSB1'),
        sa.Column('led_baudrate', sa.Integer(), nullable=False, server_default='9600'),
        sa.Column('led_serial_mode', sa.String(length=20), nullable=False, server_default='RS232'),
        sa.Column('led_default_text', sa.Text(), nullable=True),

        # VFD Settings
        sa.Column('vfd_enabled', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('vfd_port', sa.String(length=100), nullable=False, server_default='/dev/ttyUSB0'),
        sa.Column('vfd_baudrate', sa.Integer(), nullable=False, server_default='38400'),

        # Metadata
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),

        sa.PrimaryKeyConstraint('id')
    )

    # Populate from environment variables
    connection = op.get_bind()

    # Read current environment variables
    gpio_enabled = _parse_bool(os.getenv('GPIO_ENABLED'))
    gpio_pin_map = _parse_json(os.getenv('GPIO_PIN_MAP'))
    gpio_behavior_matrix = _parse_json(os.getenv('GPIO_BEHAVIOR_MATRIX'))

    oled_enabled = _parse_bool(os.getenv('OLED_ENABLED'))
    oled_i2c_bus = _parse_int(os.getenv('OLED_I2C_BUS'), 1)
    oled_i2c_address = _parse_int(os.getenv('OLED_I2C_ADDRESS', '0x3C'), 0x3C)
    oled_width = _parse_int(os.getenv('OLED_WIDTH'), 128)
    oled_height = _parse_int(os.getenv('OLED_HEIGHT'), 64)
    oled_rotate = _parse_int(os.getenv('OLED_ROTATE'), 0)
    oled_contrast = _parse_int(os.getenv('OLED_CONTRAST')) if os.getenv('OLED_CONTRAST') else None
    oled_font_path = os.getenv('OLED_FONT_PATH')
    oled_default_invert = _parse_bool(os.getenv('OLED_DEFAULT_INVERT'))
    oled_button_gpio = _parse_int(os.getenv('OLED_BUTTON_GPIO'), 4)
    oled_button_hold_seconds = _parse_float(os.getenv('OLED_BUTTON_HOLD_SECONDS'), 1.25)
    oled_button_active_high = _parse_bool(os.getenv('OLED_BUTTON_ACTIVE_HIGH'))
    oled_scroll_effect = os.getenv('OLED_SCROLL_EFFECT', 'scroll_left')
    oled_scroll_speed = _parse_int(os.getenv('OLED_SCROLL_SPEED'), 4)
    oled_scroll_fps = _parse_int(os.getenv('OLED_SCROLL_FPS'), 30)
    screens_auto_start = _parse_bool(os.getenv('SCREENS_AUTO_START'), True)

    led_enabled = _parse_bool(os.getenv('LED_SIGN_ENABLED'))
    led_ip_address = os.getenv('LED_SIGN_IP', '192.168.1.100')
    led_port = _parse_int(os.getenv('LED_SIGN_PORT'), 10001)
    led_serial_port = os.getenv('LED_PORT', '/dev/ttyUSB1')
    led_baudrate = _parse_int(os.getenv('LED_BAUDRATE'), 9600)
    led_serial_mode = os.getenv('LED_SERIAL_MODE', 'RS232')
    led_default_text = os.getenv('LED_DEFAULT_TEXT')

    # Determine LED connection type based on which env vars are set
    if led_ip_address and led_ip_address != '192.168.1.100':
        led_connection_type = 'network'
    elif led_serial_port and led_serial_port != '/dev/ttyUSB1':
        led_connection_type = 'serial'
    else:
        led_connection_type = 'network'  # default

    # VFD settings - check if VFD_PORT is set and not empty
    vfd_port = os.getenv('VFD_PORT', '/dev/ttyUSB0')
    vfd_baudrate = _parse_int(os.getenv('VFD_BAUDRATE'), 38400)
    vfd_enabled = bool(vfd_port and vfd_port.strip())

    # Insert single settings row with id=1
    connection.execute(
        sa.text("""
            INSERT INTO hardware_settings (
                id,
                gpio_enabled, gpio_pin_map, gpio_behavior_matrix,
                oled_enabled, oled_i2c_bus, oled_i2c_address, oled_width, oled_height,
                oled_rotate, oled_contrast, oled_font_path, oled_default_invert,
                oled_button_gpio, oled_button_hold_seconds, oled_button_active_high,
                oled_scroll_effect, oled_scroll_speed, oled_scroll_fps, screens_auto_start,
                led_enabled, led_connection_type, led_ip_address, led_port,
                led_serial_port, led_baudrate, led_serial_mode, led_default_text,
                vfd_enabled, vfd_port, vfd_baudrate
            ) VALUES (
                1,
                :gpio_enabled, :gpio_pin_map, :gpio_behavior_matrix,
                :oled_enabled, :oled_i2c_bus, :oled_i2c_address, :oled_width, :oled_height,
                :oled_rotate, :oled_contrast, :oled_font_path, :oled_default_invert,
                :oled_button_gpio, :oled_button_hold_seconds, :oled_button_active_high,
                :oled_scroll_effect, :oled_scroll_speed, :oled_scroll_fps, :screens_auto_start,
                :led_enabled, :led_connection_type, :led_ip_address, :led_port,
                :led_serial_port, :led_baudrate, :led_serial_mode, :led_default_text,
                :vfd_enabled, :vfd_port, :vfd_baudrate
            )
        """),
        {
            'gpio_enabled': gpio_enabled,
            'gpio_pin_map': json.dumps(gpio_pin_map),
            'gpio_behavior_matrix': json.dumps(gpio_behavior_matrix),
            'oled_enabled': oled_enabled,
            'oled_i2c_bus': oled_i2c_bus,
            'oled_i2c_address': oled_i2c_address,
            'oled_width': oled_width,
            'oled_height': oled_height,
            'oled_rotate': oled_rotate,
            'oled_contrast': oled_contrast,
            'oled_font_path': oled_font_path,
            'oled_default_invert': oled_default_invert,
            'oled_button_gpio': oled_button_gpio,
            'oled_button_hold_seconds': oled_button_hold_seconds,
            'oled_button_active_high': oled_button_active_high,
            'oled_scroll_effect': oled_scroll_effect,
            'oled_scroll_speed': oled_scroll_speed,
            'oled_scroll_fps': oled_scroll_fps,
            'screens_auto_start': screens_auto_start,
            'led_enabled': led_enabled,
            'led_connection_type': led_connection_type,
            'led_ip_address': led_ip_address,
            'led_port': led_port,
            'led_serial_port': led_serial_port,
            'led_baudrate': led_baudrate,
            'led_serial_mode': led_serial_mode,
            'led_default_text': led_default_text,
            'vfd_enabled': vfd_enabled,
            'vfd_port': vfd_port,
            'vfd_baudrate': vfd_baudrate,
        }
    )


def downgrade():
    op.drop_table('hardware_settings')
