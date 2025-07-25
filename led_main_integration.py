#!/usr/bin/env python3
"""
Main LED Integration Script for NOAA CAP Alert System
This script integrates Alpha Premier LED signs with your existing system
"""

import os
import sys
import json
import logging
from datetime import datetime

# Add the project directory to Python path
project_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, project_dir)

# Import our existing app and LED modules
from app import app, db, CAPAlert, SystemLog
from alpha_led_integration import LEDSignManager, DEFAULT_LED_CONFIG
from led_flask_integration import LEDSignService

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(os.path.join(project_dir, 'logs', 'led_integration.log'))
    ]
)

logger = logging.getLogger(__name__)


class NOAACAPLEDIntegration:
    """Main integration class for NOAA CAP alerts and LED signs"""

    def __init__(self):
        self.led_service = None
        self.app = app
        self.logger = logger

    def initialize(self):
        """Initialize the LED integration"""
        try:
            # Create LED service
            self.led_service = LEDSignService(self.app, 'led_config.json')

            # Add LED routes to existing Flask app
            self.setup_additional_routes()

            # Patch the existing CAP poller to include LED functionality
            self.patch_cap_poller()

            self.logger.info("LED integration initialized successfully")
            return True

        except Exception as e:
            self.logger.error(f"Failed to initialize LED integration: {e}")
            return False

    def setup_additional_routes(self):
        """Add LED-specific routes to the existing Flask app"""

        @self.app.route('/admin/led_manual_alert', methods=['POST'])
        def manual_led_alert():
            """Send manual alert to LED signs from admin panel"""
            try:
                from flask import request, jsonify

                data = request.get_json() or {}

                # Create alert data structure
                alert_data = {
                    'event': data.get('event', 'Manual Alert'),
                    'severity': data.get('severity', 'Moderate'),
                    'headline': data.get('headline', ''),
                    'area_desc': data.get('area_desc', 'Putnam County, OH'),
                    'urgency': data.get('urgency', 'Immediate'),
                    'certainty': data.get('certainty', 'Observed'),
                    'identifier': f"manual_led_{int(datetime.now().timestamp())}",
                    'sent': datetime.now().isoformat()
                }

                # Send to LED signs
                if self.led_service:
                    success = self.led_service.send_cap_alert(alert_data)

                    if success:
                        # Log the manual alert
                        log_entry = SystemLog(
                            level='INFO',
                            message=f'Manual LED alert sent: {alert_data["event"]}',
                            module='led_integration',
                            details=alert_data
                        )
                        db.session.add(log_entry)
                        db.session.commit()

                        return jsonify({
                            'success': True,
                            'message': 'Manual alert sent to LED signs',
                            'alert_data': alert_data
                        })
                    else:
                        return jsonify({
                            'success': False,
                            'message': 'Failed to send alert to LED signs'
                        }), 500
                else:
                    return jsonify({
                        'success': False,
                        'message': 'LED service not available'
                    }), 503

            except Exception as e:
                self.logger.error(f"Error in manual LED alert: {e}")
                return jsonify({'error': str(e)}), 500

        @self.app.route('/admin/led_health_check')
        def led_health_check():
            """Get detailed health check of LED signs"""
            try:
                from flask import jsonify

                if not self.led_service:
                    return jsonify({'error': 'LED service not available'}), 503

                status = self.led_service.get_status()

                # Enhanced health information
                health_data = {
                    'timestamp': datetime.now().isoformat(),
                    'service_running': self.led_service.running,
                    'signs': status,
                    'total_signs': len(status),
                    'online_signs': sum(1 for s in status.values() if s.get('connected', False)),
                    'offline_signs': sum(1 for s in status.values() if not s.get('connected', False)),
                    'alerting_signs': sum(1 for s in status.values() if s.get('current_alert', False))
                }

                return jsonify(health_data)

            except Exception as e:
                self.logger.error(f"Error in LED health check: {e}")
                return jsonify({'error': str(e)}), 500

    def patch_cap_poller(self):
        """Patch the existing CAP poller to send alerts to LED signs"""

        # Import the existing CAP poller
        try:
            from poller.cap_poller import CAPPoller

            # Store the original save_cap_alert method
            original_save_method = CAPPoller.save_cap_alert

            def enhanced_save_cap_alert(self, alert_data):
                """Enhanced save method that also sends to LED signs"""
                try:
                    # Call the original save method
                    is_new, alert = original_save_method(self, alert_data)

                    # Send to LED signs if it's a new alert and meets criteria
                    if is_new and alert and self.should_send_to_led(alert):
                        self.send_to_led_signs(alert)

                    return is_new, alert

                except Exception as e:
                    self.logger.error(f"Error in enhanced save_cap_alert: {e}")
                    # Don't let LED errors break the original functionality
                    return original_save_method(self, alert_data)

            def should_send_to_led(self, alert):
                """Determine if alert should be sent to LED signs"""

                # Don't send expired alerts
                if alert.expires and alert.expires < datetime.now():
                    return False

                # Don't send test alerts
                if alert.status and 'test' in alert.status.lower():
                    return False

                # High priority events
                high_priority_events = [
                    'tornado warning',
                    'severe thunderstorm warning',
                    'flash flood warning',
                    'winter storm warning',
                    'blizzard warning',
                    'ice storm warning',
                    'high wind warning',
                    'special weather statement'
                ]

                if alert.event and alert.event.lower() in high_priority_events:
                    return True

                # High severity alerts
                if alert.severity and alert.severity.lower() in ['extreme', 'severe']:
                    return True

                return False

            def send_to_led_signs(self, alert):
                """Send alert to LED signs"""
                try:
                    if not app.led_service:
                        return False

                    led_alert_data = {
                        'event': alert.event,
                        'severity': alert.severity,
                        'headline': alert.headline,
                        'area_desc': alert.area_desc,
                        'expires': alert.expires.isoformat() if alert.expires else None,
                        'identifier': alert.identifier,
                        'sent': alert.sent.isoformat() if alert.sent else None,
                        'urgency': alert.urgency,
                        'certainty': alert.certainty
                    }

                    success = app.led_service.send_cap_alert(led_alert_data)

                    if success:
                        self.logger.info(f"Sent CAP alert to LED signs: {alert.event}")

                        # Log the LED send
                        log_entry = SystemLog(
                            level='INFO',
                            message=f'CAP alert sent to LED signs: {alert.event}',
                            module='led_integration',
                            details={
                                'alert_id': alert.id,
                                'alert_identifier': alert.identifier,
                                'event': alert.event,
                                'severity': alert.severity
                            }
                        )
                        db.session.add(log_entry)
                        db.session.commit()
                    else:
                        self.logger.warning(f"Failed to send CAP alert to LED signs: {alert.event}")

                    return success

                except Exception as e:
                    self.logger.error(f"Error sending alert to LED signs: {e}")
                    return False

            # Monkey patch the methods
            CAPPoller.save_cap_alert = enhanced_save_cap_alert
            CAPPoller.should_send_to_led = should_send_to_led
            CAPPoller.send_to_led_signs = send_to_led_signs

            # Store LED service reference in app for access from poller
            app.led_service = self.led_service

            self.logger.info("Successfully patched CAP poller with LED functionality")

        except ImportError as e:
            self.logger.warning(f"Could not patch CAP poller - module not found: {e}")
        except Exception as e:
            self.logger.error(f"Error patching CAP poller: {e}")

    def add_admin_panel_integration(self):
        """Add LED controls to the existing admin panel"""

        # This would modify the admin.html template to include LED controls
        admin_template_path = os.path.join(project_dir, 'templates', 'admin.html')

        if os.path.exists(admin_template_path):
            try:
                with open(admin_template_path, 'r') as f:
                    content = f.read()

                # Add LED section to admin panel
                led_section = '''
                    <!-- LED Sign Controls -->
                    <div class="card mt-4">
                        <div class="card-header">
                            <h5><i class="fas fa-tv"></i> LED Sign Controls</h5>
                        </div>
                        <div class="card-body">
                            <div class="row">
                                <div class="col-md-8">
                                    <div class="d-flex gap-2 flex-wrap">
                                        <button onclick="ledTest()" class="btn btn-warning btn-sm">
                                            <i class="fas fa-vial"></i> Test LED Signs
                                        </button>
                                        <button onclick="ledClear()" class="btn btn-danger btn-sm">
                                            <i class="fas fa-times"></i> Clear LED Alerts
                                        </button>
                                        <a href="/admin/led_signs" class="btn btn-info btn-sm">
                                            <i class="fas fa-cog"></i> LED Administration
                                        </a>
                                    </div>
                                </div>
                                <div class="col-md-4">
                                    <div id="led-status" class="text-end">
                                        <span class="badge bg-secondary">Loading...</span>
                                    </div>
                                </div>
                            </div>
                        </div>
                    </div>

                    <script>
                    async function ledTest() {
                        try {
                            const response = await fetch('/api/led_signs/test', { method: 'POST' });
                            const data = await response.json();
                            showOperationStatus(data.success ? 'LED test sent' : 'LED test failed', 
                                              data.success ? 'success' : 'error');
                        } catch (error) {
                            showOperationStatus('LED test error: ' + error.message, 'error');
                        }
                    }

                    async function ledClear() {
                        if (confirm('Clear all LED sign alerts?')) {
                            try {
                                const response = await fetch('/api/led_signs/clear', { method: 'POST' });
                                const data = await response.json();
                                showOperationStatus(data.success ? 'LED alerts cleared' : 'LED clear failed',
                                                  data.success ? 'success' : 'error');
                            } catch (error) {
                                showOperationStatus('LED clear error: ' + error.message, 'error');
                            }
                        }
                    }

                    // Update LED status
                    async function updateLEDStatus() {
                        try {
                            const response = await fetch('/api/led_signs/status');
                            const data = await response.json();
                            const statusEl = document.getElementById('led-status');

                            if (data.status === 'success') {
                                const online = Object.values(data.signs).filter(s => s.connected).length;
                                const total = Object.keys(data.signs).length;
                                statusEl.innerHTML = `<span class="badge bg-${online === total ? 'success' : 'warning'}">${online}/${total} Online</span>`;
                            } else {
                                statusEl.innerHTML = '<span class="badge bg-danger">Error</span>';
                            }
                        } catch (error) {
                            document.getElementById('led-status').innerHTML = '<span class="badge bg-danger">Offline</span>';
                        }
                    }

                    // Update status on page load and every 30 seconds
                    document.addEventListener('DOMContentLoaded', updateLEDStatus);
                    setInterval(updateLEDStatus, 30000);
                    </script>
                '''

                # Insert before the closing div of the admin panel
                if '<!-- End of Admin Content -->' in content:
                    content = content.replace('<!-- End of Admin Content -->',
                                              led_section + '<!-- End of Admin Content -->')
                else:
                    # Insert before the last closing div
                    content = content.replace('</div>\n</div>\n</body>', led_section + '</div>\n</div>\n</body>')

                # Backup original and write modified version
                backup_path = admin_template_path + '.backup'
                if not os.path.exists(backup_path):
                    with open(backup_path, 'w') as f:
                        f.write(content.replace(led_section, ''))  # Original content

                with open(admin_template_path, 'w') as f:
                    f.write(content)

                self.logger.info("Added LED controls to admin panel")

            except Exception as e:
                self.logger.error(f"Error modifying admin template: {e}")


def create_led_config():
    """Create LED configuration file if it doesn't exist"""
    config_path = os.path.join(project_dir, 'led_config.json')

    if not os.path.exists(config_path):
        try:
            # Create a sample config with placeholder IP
            sample_config = {
                "signs": {
                    "main_sign": {
                        "ip_address": "192.168.1.100",  # CHANGE THIS
                        "port": 10001,
                        "sign_id": "00",
                        "description": "Main Emergency Alert LED Sign"
                    }
                },
                "alert_settings": {
                    "alert_duration_minutes": 30,
                    "test_message": "KR8MER CAP ALERT SYSTEM TEST - THIS IS ONLY A TEST",
                    "default_message": "KR8MER CAP ALERT SYSTEM - NO ACTIVE ALERTS"
                }
            }

            with open(config_path, 'w') as f:
                json.dump(sample_config, f, indent=2)

            print(f"✅ Created LED configuration file: {config_path}")
            print("📝 IMPORTANT: Edit led_config.json and set the correct IP address for your LED sign!")
            return True

        except Exception as e:
            print(f"❌ Error creating config file: {e}")
            return False
    else:
        print(f"📋 LED configuration file already exists: {config_path}")
        return True


def setup_integration():
    """Main setup function"""
    print("🚀 Setting up LED Integration for NOAA CAP Alert System")
    print("=" * 60)

    # Create config file
    if not create_led_config():
        print("❌ Failed to create configuration file")
        return False

    # Create logs directory
    logs_dir = os.path.join(project_dir, 'logs')
    os.makedirs(logs_dir, exist_ok=True)

    # Initialize integration
    integration = NOAACAPLEDIntegration()

    if integration.initialize():
        print("✅ LED integration initialized successfully")

        # Add admin panel integration
        integration.add_admin_panel_integration()

        print("\n📋 LED Integration Setup Complete!")
        print("=" * 40)
        print("🔧 Next Steps:")
        print("1. Edit led_config.json with your LED sign IP address")
        print("2. Test connection: python3 alpha_led_integration.py --ip YOUR_LED_IP --test")
        print("3. Restart your Flask application")
        print("4. Visit /admin/led_signs to manage LED signs")
        print("5. The system will now automatically send alerts to LED signs")

        print("\n🎯 LED Signs will display:")
        print("- Tornado Warnings")
        print("- Severe Thunderstorm Warnings")
        print("- Flash Flood Warnings")
        print("- Winter Storm Warnings")
        print("- Special Weather Statements")
        print("- Any alert with Extreme or Severe severity")

        return True
    else:
        print("❌ Failed to initialize LED integration")
        return False


def test_led_connection():
    """Test LED sign connection"""
    import argparse

    parser = argparse.ArgumentParser(description='Test LED Sign Connection')
    parser.add_argument('--ip', required=True, help='LED sign IP address')
    parser.add_argument('--port', type=int, default=10001, help='LED sign port')

    args = parser.parse_args()

    print(f"🧪 Testing connection to LED sign at {args.ip}:{args.port}")

    try:
        from alpha_led_integration import AlphaPremierLEDSign

        sign = AlphaPremierLEDSign(args.ip, args.port)

        if sign.connect():
            print("✅ Connection successful!")

            # Test basic commands
            if sign.clear_memory():
                print("✅ Clear memory command successful")

            if sign.display_text("KR8MER CAP TEST MESSAGE"):
                print("✅ Test message sent successfully")

            sign.disconnect()
            print("🔌 Disconnected from LED sign")
            return True
        else:
            print("❌ Connection failed!")
            return False

    except Exception as e:
        print(f"❌ Test failed: {e}")
        return False


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='NOAA CAP LED Integration Setup')
    parser.add_argument('--setup', action='store_true', help='Setup LED integration')
    parser.add_argument('--test-connection', action='store_true', help='Test LED connection')
    parser.add_argument('--ip', help='LED sign IP address for testing')
    parser.add_argument('--create-config', action='store_true', help='Create configuration file')

    args = parser.parse_args()

    if args.setup:
        setup_integration()
    elif args.test_connection:
        if not args.ip:
            print("❌ --ip required for connection test")
            sys.exit(1)
        test_led_connection()
    elif args.create_config:
        create_led_config()
    else:
        print("NOAA CAP Alert System - LED Integration")
        print("Usage:")
        print("  python3 led_main_integration.py --setup")
        print("  python3 led_main_integration.py --test-connection --ip 192.168.1.100")
        print("  python3 led_main_integration.py --create-config")
        print("\nFor complete setup instructions, run with --setup")


# Integration with systemd service
def create_systemd_service():
    """Create systemd service for LED integration monitoring"""

    service_content = '''[Unit]
Description=KR8MER CAP LED Integration Service
After=network.target postgresql.service
Requires=postgresql.service
StartLimitInterval=0

[Service]
Type=simple
User=pi
Group=pi
WorkingDirectory=/home/pi/noaa_alerts_system
Environment=PYTHONPATH=/home/pi/noaa_alerts_system
ExecStart=/usr/bin/python3 /home/pi/noaa_alerts_system/led_monitor.py
Restart=always
RestartSec=30
StandardOutput=journal
StandardError=journal

# Resource limits
MemoryMax=256M
CPUQuota=25%

[Install]
WantedBy=multi-user.target
'''

    try:
        with open('/tmp/kr8mer-led-integration.service', 'w') as f:
            f.write(service_content)

        print("📄 Created systemd service file at /tmp/kr8mer-led-integration.service")
        print("📋 To install:")
        print("  sudo cp /tmp/kr8mer-led-integration.service /etc/systemd/system/")
        print("  sudo systemctl daemon-reload")
        print("  sudo systemctl enable kr8mer-led-integration")
        print("  sudo systemctl start kr8mer-led-integration")

        return True
    except Exception as e:
        print(f"❌ Error creating systemd service: {e}")
        return False


# LED monitoring service
def create_led_monitor():
    """Create LED monitoring service script"""

    monitor_script = '''#!/usr/bin/env python3
"""
LED Sign Monitoring Service
Monitors LED signs and ensures they stay connected
"""

import time
import logging
import json
import os
import sys
from datetime import datetime, timedelta

# Add project path
sys.path.insert(0, '/home/pi/noaa_alerts_system')

from alpha_led_integration import LEDSignManager
from app import app, db, SystemLog

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('/home/pi/noaa_alerts_system/logs/led_monitor.log'),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger(__name__)

class LEDMonitorService:
    """LED monitoring service"""

    def __init__(self):
        self.config_file = '/home/pi/noaa_alerts_system/led_config.json'
        self.led_manager = None
        self.running = False
        self.last_health_check = None

    def load_config(self):
        """Load LED configuration"""
        try:
            if os.path.exists(self.config_file):
                with open(self.config_file, 'r') as f:
                    config = json.load(f)
                self.led_manager = LEDSignManager(config)
                return True
            else:
                logger.error(f"Config file not found: {self.config_file}")
                return False
        except Exception as e:
            logger.error(f"Error loading config: {e}")
            return False

    def start_monitoring(self):
        """Start the monitoring service"""
        logger.info("Starting LED monitoring service")

        if not self.load_config():
            logger.error("Failed to load configuration")
            return False

        try:
            self.led_manager.start_all_signs()
            self.running = True

            # Log startup
            with app.app_context():
                log_entry = SystemLog(
                    level='INFO',
                    message='LED monitoring service started',
                    module='led_monitor',
                    details={'signs_count': len(self.led_manager.signs)}
                )
                db.session.add(log_entry)
                db.session.commit()

            # Main monitoring loop
            while self.running:
                try:
                    self.health_check()
                    time.sleep(60)  # Check every minute
                except KeyboardInterrupt:
                    logger.info("Received interrupt signal")
                    break
                except Exception as e:
                    logger.error(f"Error in monitoring loop: {e}")
                    time.sleep(30)

            return True

        except Exception as e:
            logger.error(f"Error starting monitoring: {e}")
            return False
        finally:
            self.stop_monitoring()

    def health_check(self):
        """Perform health check on LED signs"""
        try:
            status = self.led_manager.get_sign_status()
            now = datetime.now()

            # Check if we should log health status
            if (not self.last_health_check or 
                now - self.last_health_check > timedelta(minutes=15)):

                online_signs = sum(1 for s in status.values() if s.get('connected', False))
                total_signs = len(status)

                logger.info(f"Health check: {online_signs}/{total_signs} signs online")

                # Log to database every 15 minutes
                with app.app_context():
                    log_entry = SystemLog(
                        level='INFO',
                        message=f'LED health check: {online_signs}/{total_signs} signs online',
                        module='led_monitor',
                        details=status
                    )
                    db.session.add(log_entry)
                    db.session.commit()

                self.last_health_check = now

            # Check for disconnected signs
            for sign_name, sign_status in status.items():
                if not sign_status.get('connected', False):
                    logger.warning(f"Sign {sign_name} is disconnected")
                    # Could attempt reconnection here

        except Exception as e:
            logger.error(f"Error in health check: {e}")

    def stop_monitoring(self):
        """Stop the monitoring service"""
        logger.info("Stopping LED monitoring service")
        self.running = False

        if self.led_manager:
            try:
                self.led_manager.stop_all_signs()

                # Log shutdown
                with app.app_context():
                    log_entry = SystemLog(
                        level='INFO',
                        message='LED monitoring service stopped',
                        module='led_monitor'
                    )
                    db.session.add(log_entry)
                    db.session.commit()

            except Exception as e:
                logger.error(f"Error stopping LED manager: {e}")

def main():
    """Main function"""
    monitor = LEDMonitorService()

    try:
        monitor.start_monitoring()
    except KeyboardInterrupt:
        logger.info("Monitoring stopped by user")
    except Exception as e:
        logger.error(f"Monitoring failed: {e}")
    finally:
        monitor.stop_monitoring()

if __name__ == '__main__':
    main()
'''

    try:
        monitor_path = os.path.join(project_dir, 'led_monitor.py')
        with open(monitor_path, 'w') as f:
            f.write(monitor_script)

        # Make executable
        os.chmod(monitor_path, 0o755)

        print(f"📄 Created LED monitor service: {monitor_path}")
        return True

    except Exception as e:
        print(f"❌ Error creating monitor service: {e}")
        return False


# Installation wizard
def installation_wizard():
    """Interactive installation wizard"""
    print("🎯 KR8MER CAP LED Integration Installation Wizard")
    print("=" * 60)

    # Step 1: Check dependencies
    print("📋 Step 1: Checking dependencies...")

    missing_deps = []
    try:
        import requests
        print("  ✅ requests module available")
    except ImportError:
        missing_deps.append("requests")

    try:
        import flask
        print("  ✅ Flask available")
    except ImportError:
        missing_deps.append("flask")

    if missing_deps:
        print(f"  ❌ Missing dependencies: {', '.join(missing_deps)}")
        print(f"  📦 Install with: pip3 install {' '.join(missing_deps)}")
        return False

    # Step 2: Get LED sign information
    print("\n📋 Step 2: LED Sign Configuration")

    led_ip = input("🔌 Enter LED sign IP address (e.g., 192.168.1.100): ").strip()
    if not led_ip:
        print("❌ IP address is required")
        return False

    led_port = input("🔌 Enter LED sign port [10001]: ").strip()
    if not led_port:
        led_port = "10001"

    sign_id = input("🔢 Enter sign ID [00]: ").strip()
    if not sign_id:
        sign_id = "00"

    sign_name = input("📝 Enter sign name [main_sign]: ").strip()
    if not sign_name:
        sign_name = "main_sign"

    # Step 3: Test connection
    print(f"\n📋 Step 3: Testing connection to {led_ip}:{led_port}...")

    try:
        from alpha_led_integration import AlphaPremierLEDSign

        test_sign = AlphaPremierLEDSign(led_ip, int(led_port), sign_id)

        if test_sign.connect():
            print("  ✅ Connection successful!")

            # Send test message
            if test_sign.display_text("KR8MER CAP SETUP TEST"):
                print("  ✅ Test message sent successfully!")

            test_sign.disconnect()
        else:
            print("  ❌ Connection failed!")
            retry = input("Continue anyway? (y/N): ").lower()
            if retry != 'y':
                return False

    except Exception as e:
        print(f"  ❌ Connection test failed: {e}")
        retry = input("Continue anyway? (y/N): ").lower()
        if retry != 'y':
            return False

    # Step 4: Create configuration
    print("\n📋 Step 4: Creating configuration...")

    config = {
        "signs": {
            sign_name: {
                "ip_address": led_ip,
                "port": int(led_port),
                "sign_id": sign_id,
                "description": f"Emergency Alert LED Sign at {led_ip}"
            }
        },
        "alert_settings": {
            "alert_duration_minutes": 30,
            "test_message": "KR8MER CAP ALERT SYSTEM TEST - THIS IS ONLY A TEST",
            "default_message": "KR8MER CAP ALERT SYSTEM - NO ACTIVE ALERTS"
        }
    }

    config_path = os.path.join(project_dir, 'led_config.json')
    try:
        with open(config_path, 'w') as f:
            json.dump(config, f, indent=2)
        print(f"  ✅ Configuration saved to {config_path}")
    except Exception as e:
        print(f"  ❌ Error saving configuration: {e}")
        return False

    # Step 5: Initialize integration
    print("\n📋 Step 5: Initializing integration...")

    integration = NOAACAPLEDIntegration()
    if integration.initialize():
        print("  ✅ LED integration initialized")
    else:
        print("  ❌ Integration initialization failed")
        return False

    # Step 6: Create monitoring service
    print("\n📋 Step 6: Setting up monitoring service...")

    if create_led_monitor():
        print("  ✅ LED monitor service created")

    if create_systemd_service():
        print("  ✅ Systemd service created")

    # Step 7: Final setup
    print("\n📋 Step 7: Final setup...")

    integration.add_admin_panel_integration()
    print("  ✅ Admin panel integration added")

    # Success!
    print("\n🎉 Installation Complete!")
    print("=" * 30)
    print("✅ LED integration is now set up and ready to use")
    print("\n🚀 Next Steps:")
    print("1. Restart your Flask application:")
    print("   sudo systemctl restart apache2")
    print("\n2. Start the LED monitoring service:")
    print("   sudo systemctl start kr8mer-led-integration")
    print("\n3. Test the integration:")
    print("   Visit /admin/led_signs in your web browser")
    print("\n4. Monitor the logs:")
    print("   tail -f logs/led_integration.log")
    print("   sudo journalctl -u kr8mer-led-integration -f")

    print("\n📺 Your LED sign will now automatically display:")
    print("• Tornado Warnings")
    print("• Severe Thunderstorm Warnings")
    print("• Flash Flood Warnings")
    print("• Winter Storm Warnings")
    print("• Special Weather Statements")
    print("• Any alert with Extreme or Severe severity")

    return True


# Command line interface
if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='KR8MER CAP LED Integration Setup')
    parser.add_argument('--wizard', action='store_true', help='Run installation wizard')
    parser.add_argument('--setup', action='store_true', help='Quick setup LED integration')
    parser.add_argument('--test-connection', action='store_true', help='Test LED connection')
    parser.add_argument('--ip', help='LED sign IP address for testing')
    parser.add_argument('--port', type=int, default=10001, help='LED sign port')
    parser.add_argument('--create-config', action='store_true', help='Create configuration file')
    parser.add_argument('--create-service', action='store_true', help='Create systemd service')
    parser.add_argument('--create-monitor', action='store_true', help='Create monitor service')

    args = parser.parse_args()

    if args.wizard:
        installation_wizard()
    elif args.setup:
        setup_integration()
    elif args.test_connection:
        if not args.ip:
            print("❌ --ip required for connection test")
            sys.exit(1)

        print(f"🧪 Testing connection to LED sign at {args.ip}:{args.port}")

        try:
            from alpha_led_integration import AlphaPremierLEDSign

            sign = AlphaPremierLEDSign(args.ip, args.port)

            if sign.connect():
                print("✅ Connection successful!")

                if sign.display_text("KR8MER CAP CONNECTION TEST"):
                    print("✅ Test message sent successfully")

                sign.disconnect()
            else:
                print("❌ Connection failed!")

        except Exception as e:
            print(f"❌ Test failed: {e}")

    elif args.create_config:
        create_led_config()
    elif args.create_service:
        create_systemd_service()
    elif args.create_monitor:
        create_led_monitor()
    else:
        print("🚀 KR8MER CAP Alert System - LED Integration")
        print("=" * 50)
        print("📺 Integrates Alpha Premier 9120C LED signs with NOAA CAP alerts")
        print("\nUsage:")
        print("  python3 led_main_integration.pya --wizard       # Interactive setup")
        print("  python3 led_main_integration.py --setup        # Quick setup")
        print("  python3 led_main_integration.py --test-connection --ip 192.168.1.100")
        print("  python3 led_main_integration.py --create-config")
        print("\n🎯 Recommended: Use --wizard for first-time setup")