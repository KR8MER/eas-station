#!/usr/bin/env python3
"""
Flask Integration for Alpha Premier LED Signs
Integrates LED sign functionality with the existing NOAA CAP alert system
"""

import json
import os
import logging
from datetime import datetime, timedelta
from flask import request, jsonify, render_template
from threading import Thread
import time

# Import the LED sign module
from alpha_led_integration import LEDSignManager, DEFAULT_LED_CONFIG


class LEDSignService:
    """Service class for managing LED signs within the Flask application"""

    def __init__(self, app=None, config_file='led_config.json'):
        self.app = app
        self.config_file = config_file
        self.led_manager = None
        self.logger = logging.getLogger(__name__)
        self.monitoring_thread = None
        self.running = False

        if app:
            self.init_app(app)

    def init_app(self, app):
        """Initialize the LED sign service with Flask app"""
        self.app = app
        self.load_config()
        self.setup_routes()

        # Start LED manager
        if self.led_manager:
            self.start_service()

    def load_config(self):
        """Load LED sign configuration"""
        try:
            config_path = os.path.join(os.path.dirname(__file__), self.config_file)

            if os.path.exists(config_path):
                with open(config_path, 'r') as f:
                    config = json.load(f)
                self.logger.info(f"Loaded LED sign config from {config_path}")
            else:
                # Create default config file
                config = DEFAULT_LED_CONFIG
                with open(config_path, 'w') as f:
                    json.dump(config, f, indent=2)
                self.logger.info(f"Created default LED sign config at {config_path}")

            # Initialize LED manager
            self.led_manager = LEDSignManager(config)

        except Exception as e:
            self.logger.error(f"Error loading LED sign config: {e}")
            self.led_manager = LEDSignManager(DEFAULT_LED_CONFIG)

    def start_service(self):
        """Start the LED sign service"""
        if self.led_manager:
            try:
                self.led_manager.start_all_signs()
                self.running = True

                # Start monitoring thread
                self.monitoring_thread = Thread(target=self._monitoring_loop, daemon=True)
                self.monitoring_thread.start()

                self.logger.info("LED sign service started successfully")
            except Exception as e:
                self.logger.error(f"Error starting LED sign service: {e}")

    def stop_service(self):
        """Stop the LED sign service"""
        self.running = False
        if self.led_manager:
            try:
                self.led_manager.stop_all_signs()
                self.logger.info("LED sign service stopped")
            except Exception as e:
                self.logger.error(f"Error stopping LED sign service: {e}")

    def _monitoring_loop(self):
        """Monitor LED signs and check for expired alerts"""
        while self.running:
            try:
                # This could include health checks, reconnection attempts, etc.
                time.sleep(60)  # Check every minute
            except Exception as e:
                self.logger.error(f"Error in LED monitoring loop: {e}")

    def send_cap_alert(self, alert_data):
        """Send CAP alert to LED signs"""
        if not self.led_manager:
            return False

        try:
            # Convert alert data to LED format
            led_alert = {
                'event': alert_data.get('event', 'Emergency Alert'),
                'severity': alert_data.get('severity', 'Unknown'),
                'headline': alert_data.get('headline', ''),
                'area_desc': alert_data.get('area_desc', ''),
                'expires': alert_data.get('expires', ''),
                'identifier': alert_data.get('identifier', ''),
                'sent': alert_data.get('sent', ''),
                'urgency': alert_data.get('urgency', ''),
                'certainty': alert_data.get('certainty', '')
            }

            self.led_manager.broadcast_alert(led_alert)

            # Log the alert send
            self.logger.info(f"Sent CAP alert to LED signs: {led_alert['event']}")
            return True

        except Exception as e:
            self.logger.error(f"Error sending CAP alert to LED signs: {e}")
            return False

    def send_test_message(self, message=None):
        """Send test message to LED signs"""
        if not self.led_manager:
            return False

        try:
            self.led_manager.broadcast_test(message)
            self.logger.info("Sent test message to LED signs")
            return True
        except Exception as e:
            self.logger.error(f"Error sending test message to LED signs: {e}")
            return False

    def clear_alerts(self):
        """Clear alerts on LED signs"""
        if not self.led_manager:
            return False

        try:
            self.led_manager.clear_all_alerts()
            self.logger.info("Cleared alerts on LED signs")
            return True
        except Exception as e:
            self.logger.error(f"Error clearing LED sign alerts: {e}")
            return False

    def get_status(self):
        """Get status of all LED signs"""
        if not self.led_manager:
            return {'error': 'LED manager not initialized'}

        try:
            return self.led_manager.get_sign_status()
        except Exception as e:
            self.logger.error(f"Error getting LED sign status: {e}")
            return {'error': str(e)}

    def setup_routes(self):
        """Setup Flask routes for LED sign management"""

        @self.app.route('/api/led_signs/status')
        def led_status():
            """Get LED sign status"""
            try:
                status = self.get_status()
                return jsonify({
                    'status': 'success',
                    'signs': status,
                    'service_running': self.running,
                    'timestamp': datetime.now().isoformat()
                })
            except Exception as e:
                return jsonify({'error': str(e)}), 500

        @self.app.route('/api/led_signs/test', methods=['POST'])
        def led_test():
            """Send test message to LED signs"""
            try:
                data = request.get_json() or {}
                message = data.get('message', 'TEST MESSAGE FROM KR8MER CAP SYSTEM')

                success = self.send_test_message(message)

                return jsonify({
                    'success': success,
                    'message': 'Test message sent' if success else 'Failed to send test message',
                    'timestamp': datetime.now().isoformat()
                })
            except Exception as e:
                return jsonify({'error': str(e)}), 500

        @self.app.route('/api/led_signs/clear', methods=['POST'])
        def led_clear():
            """Clear alerts on LED signs"""
            try:
                success = self.clear_alerts()

                return jsonify({
                    'success': success,
                    'message': 'Alerts cleared' if success else 'Failed to clear alerts',
                    'timestamp': datetime.now().isoformat()
                })
            except Exception as e:
                return jsonify({'error': str(e)}), 500

        @self.app.route('/api/led_signs/alert', methods=['POST'])
        def led_alert():
            """Send manual alert to LED signs"""
            try:
                data = request.get_json() or {}

                # Validate required fields
                if not data.get('event'):
                    return jsonify({'error': 'Event field is required'}), 400

                alert_data = {
                    'event': data.get('event', 'Manual Alert'),
                    'severity': data.get('severity', 'Moderate'),
                    'headline': data.get('headline', ''),
                    'area_desc': data.get('area_desc', 'Putnam County, OH'),
                    'expires': data.get('expires', ''),
                    'identifier': f"manual_{int(time.time())}",
                    'sent': datetime.now().isoformat(),
                    'urgency': data.get('urgency', 'Immediate'),
                    'certainty': data.get('certainty', 'Observed')
                }

                success = self.send_cap_alert(alert_data)

                return jsonify({
                    'success': success,
                    'message': 'Alert sent to LED signs' if success else 'Failed to send alert',
                    'alert_data': alert_data,
                    'timestamp': datetime.now().isoformat()
                })
            except Exception as e:
                return jsonify({'error': str(e)}), 500

        @self.app.route('/admin/led_signs')
        def led_admin():
            """LED sign administration page"""
            try:
                status = self.get_status()
                return render_template('led_admin.html',
                                       signs_status=status,
                                       service_running=self.running)
            except Exception as e:
                self.logger.error(f"Error loading LED admin page: {e}")
                return f"Error loading LED administration: {str(e)}", 500


# Integration with existing CAP Alert system
def integrate_led_with_cap_poller(led_service):
    """
    Integrate LED signs with the existing CAP poller
    This function should be called when a new alert is processed
    """

    def send_alert_to_led(alert):
        """Send alert to LED signs - to be called from CAP poller"""
        try:
            if not led_service or not led_service.running:
                return False

            # Check if alert is relevant for LED display
            if not should_display_on_led(alert):
                return False

            # Convert CAPAlert object to LED format
            alert_data = {
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

            return led_service.send_cap_alert(alert_data)

        except Exception as e:
            logging.getLogger(__name__).error(f"Error sending alert to LED: {e}")
            return False

    return send_alert_to_led


def should_display_on_led(alert):
    """
    Determine if an alert should be displayed on LED signs
    Customize this function based on your requirements
    """

    # Don't display expired alerts
    if alert.expires and alert.expires < datetime.now():
        return False

    # Don't display test alerts (optional)
    if alert.status and 'test' in alert.status.lower():
        return False

    # Only display high-priority alerts
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

    # Display based on severity
    high_severity = ['extreme', 'severe']
    if alert.severity and alert.severity.lower() in high_severity:
        return True

    return False


# Modified CAP Poller integration
def enhanced_cap_poller_with_led():
    """
    Enhanced version of the CAP poller that includes LED sign integration
    Add this to your existing cap_poller.py
    """

    additional_code = '''
# Add this to your cap_poller.py imports
from alpha_led_integration import LEDSignManager, DEFAULT_LED_CONFIG
from led_flask_integration import integrate_led_with_cap_poller

class EnhancedCAPPoller(CAPPoller):
    """Enhanced CAP Poller with LED sign integration"""

    def __init__(self, database_url=None, led_config=None):
        super().__init__(database_url)

        # Initialize LED manager
        self.led_config = led_config or DEFAULT_LED_CONFIG
        self.led_manager = None
        self.led_enabled = False

        try:
            self.led_manager = LEDSignManager(self.led_config)
            self.led_manager.start_all_signs()
            self.led_enabled = True
            self.logger.info("LED sign integration enabled")
        except Exception as e:
            self.logger.error(f"Failed to initialize LED signs: {e}")
            self.led_enabled = False

    def save_cap_alert(self, alert_data):
        """Enhanced save method that also sends to LED signs"""
        try:
            # Call original save method
            is_new, alert = super().save_cap_alert(alert_data)

            # Send to LED signs if enabled and alert is new or updated
            if self.led_enabled and self.led_manager and alert:
                if should_display_on_led(alert):
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

                    try:
                        self.led_manager.broadcast_alert(led_alert_data)
                        self.logger.info(f"Sent alert to LED signs: {alert.event}")
                    except Exception as e:
                        self.logger.error(f"Failed to send alert to LED signs: {e}")

            return is_new, alert

        except Exception as e:
            self.logger.error(f"Error in enhanced save_cap_alert: {e}")
            raise

    def close(self):
        """Enhanced close method that also stops LED signs"""
        try:
            if self.led_enabled and self.led_manager:
                self.led_manager.stop_all_signs()
                self.logger.info("Stopped LED sign service")
        except Exception as e:
            self.logger.error(f"Error stopping LED signs: {e}")

        super().close()
'''

    return additional_code


# Configuration file template
LED_CONFIG_TEMPLATE = {
    "signs": {
        "main_entrance": {
            "ip_address": "192.168.1.100",
            "port": 10001,
            "sign_id": "00",
            "description": "Main Entrance Emergency Alert Sign",
            "location": "Building Main Entrance"
        },
        "emergency_services": {
            "ip_address": "192.168.1.101",
            "port": 10001,
            "sign_id": "01",
            "description": "Emergency Services Building Sign",
            "location": "Emergency Services Building"
        }
    },
    "alert_settings": {
        "alert_duration_minutes": 30,
        "test_message": "KR8MER CAP ALERT SYSTEM TEST - THIS IS ONLY A TEST",
        "default_message": "KR8MER CAP ALERT SYSTEM - NO ACTIVE ALERTS",
        "auto_clear_expired": True,
        "display_criteria": {
            "min_severity": "moderate",
            "required_events": [
                "tornado warning",
                "severe thunderstorm warning",
                "flash flood warning",
                "winter storm warning",
                "blizzard warning",
                "ice storm warning",
                "high wind warning",
                "special weather statement"
            ]
        }
    },
    "display_settings": {
        "max_line_length": 125,
        "max_lines": 4,
        "scroll_speed": "normal",
        "brightness": "auto"
    }
}


def create_led_config_file(filename='led_config.json'):
    """Create LED configuration file"""
    import json

    try:
        with open(filename, 'w') as f:
            json.dump(LED_CONFIG_TEMPLATE, f, indent=2)
        print(f"✅ Created LED configuration file: {filename}")
        print("📝 Please edit the IP addresses and settings as needed")
        return True
    except Exception as e:
        print(f"❌ Error creating config file: {e}")
        return False


# Setup instructions
SETUP_INSTRUCTIONS = """
LED Sign Integration Setup Instructions:

1. HARDWARE SETUP:
   - Connect your Alpha Premier 9120C LED sign to your network
   - Note the IP address assigned to the ethernet adapter
   - Test connectivity: ping <LED_sign_IP>

2. CONFIGURATION:
   - Run: python3 led_flask_integration.py --create-config
   - Edit led_config.json with your LED sign IP addresses
   - Adjust alert criteria and display settings as needed

3. TESTING:
   - Test connection: python3 alpha_led_integration.py --ip <LED_IP> --test
   - Test from web interface: /admin/led_signs

4. INTEGRATION:
   - Add LED service to your Flask app initialization
   - The system will automatically send high-priority alerts to LED signs

5. MONITOR:
   - Check LED sign status: /api/led_signs/status
   - View admin panel: /admin/led_signs
   - Monitor logs for LED-related messages

ALERT DISPLAY CRITERIA:
- Severity: Moderate, Severe, or Extreme
- Events: Tornado, Severe Weather, Flash Flood, Winter Storm warnings
- Special Weather Statements for local area
- Alerts are displayed for 30 minutes or until expiration

MANUAL CONTROLS:
- Send test message: POST /api/led_signs/test
- Clear current alerts: POST /api/led_signs/clear  
- Send manual alert: POST /api/led_signs/alert
"""

if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='LED Sign Integration Setup')
    parser.add_argument('--create-config', action='store_true',
                        help='Create default LED configuration file')
    parser.add_argument('--show-setup', action='store_true',
                        help='Show setup instructions')

    args = parser.parse_args()

    if args.create_config:
        create_led_config_file()

    if args.show_setup:
        print(SETUP_INSTRUCTIONS)

    if not args.create_config and not args.show_setup:
        print("LED Sign Integration Module")
        print("Use --help for options")
        print("Use --show-setup for setup instructions")