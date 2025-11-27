#!/usr/bin/env python3
"""
EAS Station - Emergency Alert System
Copyright (c) 2025 Timothy Kramer (KR8MER)

This file is part of EAS Station.

EAS Station is dual-licensed software:
- GNU Affero General Public License v3 (AGPL-3.0) for open-source use
- Commercial License for proprietary use

You should have received a copy of both licenses with this software.
For more information, see LICENSE and LICENSE-COMMERCIAL files.

IMPORTANT: This software cannot be rebranded or have attribution removed.
See NOTICE file for complete terms.

Repository: https://github.com/KR8MER/eas-station
"""

"""
Dedicated Hardware Service

This service handles GPIO, displays, and Zigbee hardware:
- GPIO pin control (relays, transmitter keying)
- OLED/LED/VFD display management
- Screen rotation and rendering
- Zigbee coordinator (if configured)
- Hardware status monitoring

Architecture Benefits:
- Fault isolation - display/GPIO issues don't affect SDR
- Independent restart - can restart hardware service without affecting audio
- Clean separation - one service per hardware type
- Better debugging - clear responsibility boundaries

The web UI communicates with this service via HTTP API for hardware control.
"""

import os
import sys
import time
import signal
import logging
import json
import redis
import subprocess
import threading
from typing import Optional
from datetime import datetime, timezone
from dotenv import load_dotenv
from flask import Flask, jsonify, request

# Configure logging early
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] [%(name)s] %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)

logger = logging.getLogger(__name__)

# Load environment variables from persistent config volume
# This must happen before initializing hardware controllers
_config_path = os.environ.get('CONFIG_PATH')
if _config_path:
    if os.path.exists(_config_path):
        load_dotenv(_config_path, override=True)
        logger.info(f"✅ Loaded environment from: {_config_path}")
    else:
        logger.warning(f"⚠️  CONFIG_PATH set but file not found: {_config_path}")
        load_dotenv(override=True)  # Fall back to default .env
else:
    load_dotenv(override=True)  # Use default .env location

# Global state
_running = True
_redis_client: Optional[redis.Redis] = None
_screen_manager = None
_gpio_controller = None


def signal_handler(signum, frame):
    """Handle shutdown signals gracefully."""
    global _running
    logger.info(f"Received signal {signum}, initiating graceful shutdown...")
    _running = False


def get_redis_client() -> redis.Redis:
    """Get or create Redis client with retry logic."""
    global _redis_client

    from app_core.redis_client import get_redis_client as get_robust_client

    try:
        _redis_client = get_robust_client(
            max_retries=5,
            initial_backoff=1.0,
            max_backoff=30.0
        )
        return _redis_client
    except Exception as e:
        logger.error(f"❌ Failed to connect to Redis: {e}")
        raise


def initialize_database():
    """Initialize database connection for hardware configuration."""
    from app_core.extensions import db
    from flask import Flask

    # Create minimal Flask app for database access
    app = Flask(__name__)

    # Database configuration
    postgres_host = os.getenv("POSTGRES_HOST", "localhost")
    postgres_port = os.getenv("POSTGRES_PORT", "5432")
    postgres_db = os.getenv("POSTGRES_DB", "alerts")
    postgres_user = os.getenv("POSTGRES_USER", "postgres")
    postgres_password = os.getenv("POSTGRES_PASSWORD", "postgres")

    app.config["SQLALCHEMY_DATABASE_URI"] = (
        f"postgresql://{postgres_user}:{postgres_password}@"
        f"{postgres_host}:{postgres_port}/{postgres_db}"
    )
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
        "pool_pre_ping": True,
        "pool_recycle": 300,
    }

    db.init_app(app)
    return app, db


def initialize_led_controller():
    """Initialize LED sign controller."""
    try:
        from app_core.led import initialise_led_controller, ensure_led_tables, LED_AVAILABLE

        if not LED_AVAILABLE:
            controller = initialise_led_controller(logger)
            if controller:
                logger.info("✅ LED controller initialized")
                # Ensure database tables exist
                try:
                    ensure_led_tables()
                except Exception as e:
                    logger.warning(f"⚠️  Failed to ensure LED tables: {e}")
            else:
                logger.info("LED controller disabled or unavailable")
        else:
            logger.info("LED controller already initialized")

    except Exception as e:
        logger.warning(f"⚠️  LED controller not available: {e}")
        logger.info("Continuing without LED support")


def initialize_vfd_controller():
    """Initialize VFD display controller."""
    try:
        from app_core.vfd import initialise_vfd_controller, ensure_vfd_tables, VFD_AVAILABLE

        if not VFD_AVAILABLE:
            controller = initialise_vfd_controller(logger)
            if controller:
                logger.info("✅ VFD controller initialized")
                # Ensure database tables exist
                try:
                    ensure_vfd_tables()
                except Exception as e:
                    logger.warning(f"⚠️  Failed to ensure VFD tables: {e}")
            else:
                logger.info("VFD controller disabled or unavailable")
        else:
            logger.info("VFD controller already initialized")

    except Exception as e:
        logger.warning(f"⚠️  VFD controller not available: {e}")
        logger.info("Continuing without VFD support")


def initialize_oled_display():
    """Initialize OLED display."""
    try:
        from app_core.oled import initialise_oled_display, ensure_oled_button, OLED_AVAILABLE

        if not OLED_AVAILABLE:
            controller = initialise_oled_display(logger)
            if controller:
                logger.info("✅ OLED display initialized")

                # Initialize OLED button (GPIO pin 4)
                button = ensure_oled_button(logger)
                if button:
                    logger.info("✅ OLED button initialized on GPIO 4")
                else:
                    logger.info("OLED button disabled or unavailable")
            else:
                logger.info("OLED display disabled or unavailable")
        else:
            logger.info("OLED display already initialized")

    except Exception as e:
        logger.warning(f"⚠️  OLED display not available: {e}")
        logger.info("Continuing without OLED support")


def initialize_screen_manager(app):
    """Initialize screen manager for OLED/LED/VFD displays."""
    global _screen_manager

    try:
        from scripts.screen_manager import screen_manager

        with app.app_context():
            screen_manager.init_app(app)

            # Start screen rotation if enabled
            auto_start = os.getenv("SCREENS_AUTO_START", "true").lower() in ("true", "1", "yes")
            if auto_start:
                screen_manager.start()
                logger.info("✅ Screen manager started with automatic rotation")
            else:
                logger.info("Screen manager initialized (auto-start disabled)")

    except Exception as e:
        logger.warning(f"⚠️  Screen manager not available: {e}")
        logger.info("Continuing without display support")


def initialize_gpio_controller(db_session=None):
    """Initialize GPIO controller for relay/transmitter control."""
    global _gpio_controller

    try:
        from app_utils.gpio import (
            GPIOController,
            GPIOBehaviorManager,
            load_gpio_pin_configs_from_env,
            load_gpio_behavior_matrix_from_env,
        )

        # Check if GPIO is enabled
        gpio_enabled = os.getenv("GPIO_ENABLED", "false").lower() in ("true", "1", "yes")

        if not gpio_enabled:
            logger.info("GPIO controller disabled (GPIO_ENABLED=false)")
            return

        # Load GPIO pin configurations from environment
        gpio_configs = load_gpio_pin_configs_from_env(logger)
        if not gpio_configs:
            logger.info("No GPIO pins configured (check EAS_GPIO_PIN or GPIO_ADDITIONAL_PINS)")
            return

        # Create GPIO controller with database session for audit logging
        _gpio_controller = GPIOController(
            db_session=db_session,
            logger=logger,
        )

        # Add each configured pin to the controller
        for config in gpio_configs:
            try:
                _gpio_controller.add_pin(config)
            except Exception as e:
                logger.error(f"Failed to add GPIO pin {config.pin}: {e}")

        # Load and configure GPIO behavior matrix
        behavior_matrix = load_gpio_behavior_matrix_from_env(logger)
        if behavior_matrix:
            gpio_behavior_manager = GPIOBehaviorManager(
                controller=_gpio_controller,
                pin_configs=gpio_configs,
                behavior_matrix=behavior_matrix,
                logger=logger,
            )
            _gpio_controller.behavior_manager = gpio_behavior_manager
            logger.info(f"✅ GPIO controller initialized with {len(gpio_configs)} pin(s) and behavior matrix")
        else:
            logger.info(f"✅ GPIO controller initialized with {len(gpio_configs)} pin(s)")

    except Exception as e:
        logger.warning(f"⚠️  GPIO controller not available: {e}")
        logger.info("Continuing without GPIO support")


def publish_hardware_metrics():
    """Publish hardware status and metrics to Redis."""
    if not _redis_client:
        return

    try:
        metrics = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "screen_manager_running": _screen_manager is not None and getattr(_screen_manager, '_running', False),
            "gpio_controller_available": _gpio_controller is not None,
        }

        # Add screen manager metrics if available
        if _screen_manager:
            try:
                metrics["screens"] = {
                    "oled_active": getattr(_screen_manager, '_oled_rotation', None) is not None,
                    "led_active": getattr(_screen_manager, '_led_rotation', None) is not None,
                    "vfd_active": getattr(_screen_manager, '_vfd_rotation', None) is not None,
                }
            except Exception:
                pass

        # Publish basic metrics to Redis
        _redis_client.setex(
            "hardware:metrics",
            60,  # 60 second TTL
            json.dumps(metrics)
        )

        # Publish detailed display state for preview (separate key for larger data)
        publish_display_state()

    except Exception as e:
        logger.debug(f"Failed to publish hardware metrics: {e}")


def publish_display_state():
    """Publish detailed display state including preview images to Redis."""
    if not _redis_client:
        return

    try:
        state = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "oled": {
                "enabled": False,
                "width": 128,
                "height": 64,
                "current_screen": None,
                "scroll_offset": 0,
                "alert_active": False,
            },
            "vfd": {
                "enabled": False,
                "width": 140,
                "height": 32,
                "current_screen": None,
            },
            "led": {
                "enabled": False,
                "lines": 4,
                "chars_per_line": 20,
                "current_message": None,
                "color": "AMBER",
            },
        }

        # Get OLED state
        try:
            import app_core.oled as oled_module
            if oled_module.oled_controller:
                state["oled"]["enabled"] = True
                state["oled"]["width"] = oled_module.oled_controller.width
                state["oled"]["height"] = oled_module.oled_controller.height

                # Get current screen name if available
                if _screen_manager and hasattr(_screen_manager, '_current_oled_screen'):
                    current_screen = _screen_manager._current_oled_screen
                    if current_screen:
                        state["oled"]["current_screen"] = current_screen.name if hasattr(current_screen, 'name') else str(current_screen)

                # Get current alert state if scrolling
                if _screen_manager:
                    if hasattr(_screen_manager, '_oled_scroll_effect') and _screen_manager._oled_scroll_effect:
                        state["oled"]["alert_active"] = True
                        state["oled"]["scroll_offset"] = getattr(_screen_manager, '_oled_scroll_offset', 0)
                        state["oled"]["alert_text"] = getattr(_screen_manager, '_current_alert_text', "") or ""
                        state["oled"]["scroll_speed"] = getattr(_screen_manager, '_oled_scroll_speed', 4)

                        # Get cached header
                        if hasattr(_screen_manager, '_cached_header_text'):
                            state["oled"]["header_text"] = _screen_manager._cached_header_text

                # Get preview image
                try:
                    preview_image = oled_module.oled_controller.get_preview_image_base64()
                    if preview_image:
                        state["oled"]["preview_image"] = preview_image
                except Exception as e:
                    logger.debug(f"Failed to get OLED preview image: {e}")

        except Exception as e:
            logger.debug(f"Error getting OLED state: {e}")

        # Get VFD state
        try:
            from app_core.vfd import vfd_controller
            if vfd_controller:
                state["vfd"]["enabled"] = True
        except Exception as e:
            logger.debug(f"Error getting VFD state: {e}")

        # Get LED state
        try:
            import app_core.led as led_module
            if led_module.led_controller:
                state["led"]["enabled"] = True
        except Exception as e:
            logger.debug(f"Error getting LED state: {e}")

        # Publish to Redis with short TTL (refreshes every 5 seconds)
        _redis_client.setex(
            "hardware:display_state",
            15,  # 15 second TTL (3x the publish interval for tolerance)
            json.dumps(state)
        )

    except Exception as e:
        logger.debug(f"Failed to publish display state: {e}")


def run_command(cmd, check=True, timeout=30):
    """Execute a shell command and return the result."""
    try:
        result = subprocess.run(
            cmd,
            shell=True,
            capture_output=True,
            text=True,
            check=check,
            timeout=timeout
        )
        return {
            'success': True,
            'stdout': result.stdout.strip(),
            'stderr': result.stderr.strip(),
            'returncode': result.returncode
        }
    except subprocess.TimeoutExpired:
        return {
            'success': False,
            'error': 'Command timeout',
            'returncode': -1
        }
    except subprocess.CalledProcessError as e:
        return {
            'success': False,
            'stdout': e.stdout.strip() if e.stdout else '',
            'stderr': e.stderr.strip() if e.stderr else '',
            'returncode': e.returncode,
            'error': str(e)
        }
    except Exception as e:
        return {
            'success': False,
            'error': str(e),
            'returncode': -1
        }


def create_api_app():
    """Create Flask API application for hardware proxy operations."""
    api_app = Flask(__name__)

    @api_app.route('/health', methods=['GET'])
    def health():
        """Health check endpoint."""
        return jsonify({
            'status': 'ok',
            'service': 'hardware-service',
            'timestamp': datetime.now(timezone.utc).isoformat()
        })

    # Network Management Proxy Endpoints

    @api_app.route('/api/network/status', methods=['GET'])
    def get_network_status():
        """Get current network connection status via nmcli."""
        try:
            # Get all connections
            result = run_command('nmcli -t -f NAME,TYPE,DEVICE,STATE connection show', check=False)

            connections = []
            if result['success'] and result['stdout']:
                for line in result['stdout'].split('\n'):
                    if line.strip():
                        parts = line.split(':')
                        if len(parts) >= 4:
                            connections.append({
                                'name': parts[0],
                                'type': parts[1],
                                'device': parts[2],
                                'state': parts[3]
                            })

            # Get active WiFi connection details
            wifi_info = None
            result = run_command('nmcli -t -f GENERAL.CONNECTION,IP4.ADDRESS device show', check=False)
            if result['success']:
                wifi_info = result['stdout']

            return jsonify({
                'success': True,
                'connections': connections,
                'wifi_info': wifi_info
            })

        except Exception as e:
            logger.error(f"Error getting network status: {e}")
            return jsonify({'success': False, 'error': str(e)}), 500

    @api_app.route('/api/network/scan', methods=['POST'])
    def scan_wifi():
        """Scan for available WiFi networks via nmcli."""
        try:
            # Rescan networks
            run_command('nmcli device wifi rescan', check=False)
            time.sleep(2)  # Wait for scan to complete

            # Get list of available networks
            result = run_command('nmcli -t -f SSID,SIGNAL,SECURITY,IN-USE device wifi list', check=False)

            networks = []
            if result['success'] and result['stdout']:
                for line in result['stdout'].split('\n'):
                    if line.strip():
                        parts = line.split(':')
                        if len(parts) >= 4:
                            networks.append({
                                'ssid': parts[0],
                                'signal': int(parts[1]) if parts[1].isdigit() else 0,
                                'security': parts[2],
                                'in_use': parts[3] == '*'
                            })

            return jsonify({
                'success': True,
                'networks': networks
            })

        except Exception as e:
            logger.error(f"Error scanning WiFi: {e}")
            return jsonify({'success': False, 'error': str(e)}), 500

    @api_app.route('/api/network/connect', methods=['POST'])
    def connect_wifi():
        """Connect to a WiFi network via nmcli."""
        try:
            data = request.json
            ssid = data.get('ssid')
            password = data.get('password', '')

            if not ssid:
                return jsonify({'success': False, 'error': 'SSID required'}), 400

            # Build nmcli command
            if password:
                cmd = f'nmcli device wifi connect "{ssid}" password "{password}"'
            else:
                cmd = f'nmcli device wifi connect "{ssid}"'

            result = run_command(cmd, check=False)

            return jsonify({
                'success': result['success'],
                'message': result.get('stdout', result.get('error', ''))
            })

        except Exception as e:
            logger.error(f"Error connecting to WiFi: {e}")
            return jsonify({'success': False, 'error': str(e)}), 500

    @api_app.route('/api/network/disconnect', methods=['POST'])
    def disconnect_network():
        """Disconnect from current network via nmcli."""
        try:
            data = request.json
            connection_name = data.get('connection')

            if not connection_name:
                return jsonify({'success': False, 'error': 'Connection name required'}), 400

            result = run_command(f'nmcli connection down "{connection_name}"', check=False)

            return jsonify({
                'success': result['success'],
                'message': result.get('stdout', result.get('error', ''))
            })

        except Exception as e:
            logger.error(f"Error disconnecting network: {e}")
            return jsonify({'success': False, 'error': str(e)}), 500

    @api_app.route('/api/network/forget', methods=['POST'])
    def forget_network():
        """Forget a saved network connection via nmcli."""
        try:
            data = request.json
            connection_name = data.get('connection')

            if not connection_name:
                return jsonify({'success': False, 'error': 'Connection name required'}), 400

            result = run_command(f'nmcli connection delete "{connection_name}"', check=False)

            return jsonify({
                'success': result['success'],
                'message': result.get('stdout', result.get('error', ''))
            })

        except Exception as e:
            logger.error(f"Error forgetting network: {e}")
            return jsonify({'success': False, 'error': str(e)}), 500

    # Zigbee Serial Port Proxy Endpoints

    @api_app.route('/api/zigbee/ports', methods=['GET'])
    def list_serial_ports():
        """List available serial ports for Zigbee coordinator."""
        try:
            import glob
            ports = glob.glob('/dev/ttyUSB*') + glob.glob('/dev/ttyACM*') + glob.glob('/dev/ttyAMA*')
            return jsonify({
                'success': True,
                'ports': sorted(ports)
            })
        except Exception as e:
            logger.error(f"Error listing serial ports: {e}")
            return jsonify({'success': False, 'error': str(e)}), 500

    @api_app.route('/api/zigbee/test_port', methods=['POST'])
    def test_serial_port():
        """Test if a serial port is accessible."""
        try:
            data = request.json
            port = data.get('port')

            if not port:
                return jsonify({'success': False, 'error': 'Port required'}), 400

            # Check if port exists and is readable
            import os
            if os.path.exists(port):
                # Try to open port briefly
                import serial
                try:
                    ser = serial.Serial(port, 115200, timeout=1)
                    ser.close()
                    return jsonify({'success': True, 'message': 'Port accessible'})
                except serial.SerialException as e:
                    return jsonify({'success': False, 'error': f'Cannot open port: {str(e)}'})
            else:
                return jsonify({'success': False, 'error': 'Port does not exist'})

        except Exception as e:
            logger.error(f"Error testing serial port: {e}")
            return jsonify({'success': False, 'error': str(e)}), 500

    return api_app


def run_api_server():
    """Run Flask API server in background thread."""
    try:
        api_app = create_api_app()
        # Run on port 5001 (app uses 5000)
        api_app.run(host='0.0.0.0', port=5001, debug=False, use_reloader=False)
    except Exception as e:
        logger.error(f"Error running API server: {e}", exc_info=True)


def health_check_loop():
    """Periodic health check and metrics publishing."""
    global _running

    logger.info("📊 Hardware monitoring started")
    last_metrics_publish = 0
    metrics_interval = 5  # Publish metrics every 5 seconds

    while _running:
        try:
            current_time = time.time()

            # Publish metrics periodically
            if current_time - last_metrics_publish >= metrics_interval:
                publish_hardware_metrics()
                last_metrics_publish = current_time

            # Sleep briefly
            time.sleep(1)

        except KeyboardInterrupt:
            break
        except Exception as e:
            logger.error(f"Error in health check loop: {e}", exc_info=True)
            time.sleep(5)


def main():
    """Main entry point for hardware service."""
    global _running

    logger.info("=" * 60)
    logger.info("🔌 EAS Station - Dedicated Hardware Service")
    logger.info("=" * 60)

    # Register signal handlers
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)

    try:
        # Initialize Redis
        logger.info("Connecting to Redis...")
        get_redis_client()
        logger.info("✅ Connected to Redis")

        # Initialize database
        logger.info("Initializing database connection...")
        app, db = initialize_database()
        logger.info("✅ Database connected")

        # Initialize hardware controllers (must be done before screen manager)
        with app.app_context():
            logger.info("Initializing LED controller...")
            initialize_led_controller()

            logger.info("Initializing VFD controller...")
            initialize_vfd_controller()

            logger.info("Initializing OLED display...")
            initialize_oled_display()

        # Initialize screen manager (depends on LED/VFD/OLED controllers)
        logger.info("Initializing screen manager...")
        initialize_screen_manager(app)

        # Initialize GPIO controller (needs db session for audit logging)
        logger.info("Initializing GPIO controller...")
        with app.app_context():
            initialize_gpio_controller(db_session=db.session)

        # Start Flask API server in background thread
        logger.info("Starting hardware proxy API server on port 5001...")
        api_thread = threading.Thread(target=run_api_server, daemon=True)
        api_thread.start()
        logger.info("✅ Hardware proxy API server started")

        # Start health check loop
        health_check_loop()

    except KeyboardInterrupt:
        logger.info("Received interrupt signal")
    except Exception as e:
        logger.error(f"Fatal error in hardware service: {e}", exc_info=True)
        sys.exit(1)
    finally:
        # Cleanup
        logger.info("Shutting down hardware service...")

        if _screen_manager:
            try:
                if hasattr(_screen_manager, 'stop'):
                    _screen_manager.stop()
            except Exception as e:
                logger.error(f"Error stopping screen manager: {e}")

        if _gpio_controller:
            try:
                if hasattr(_gpio_controller, 'cleanup'):
                    _gpio_controller.cleanup()
            except Exception as e:
                logger.error(f"Error cleaning up GPIO: {e}")

        if _redis_client:
            try:
                _redis_client.close()
            except Exception:
                pass

        logger.info("✅ Hardware service stopped cleanly")


if __name__ == "__main__":
    main()
