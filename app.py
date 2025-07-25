#!/usr/bin/env python3
"""
Enhanced Flask application for NOAA CAP Alert System
Complete integration with LED sign control and existing CAP functionality
"""

import os
import sys
import json
import time
import logging
import threading
import subprocess
import psutil
import pytz
import hashlib
import requests
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from flask import Flask, render_template, request, jsonify, flash, redirect, url_for, send_file
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import create_engine, func, or_, text, desc, and_
from sqlalchemy.orm import sessionmaker
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.dialects.postgresql import UUID
from geoalchemy2 import Geometry, functions as geo_func
from geoalchemy2.shape import to_shape
import geoalchemy2
from shapely.geometry import Point, Polygon, MultiPolygon
from shapely import wkt
import folium
from folium import plugins
import requests
import xml.etree.ElementTree as ET

# Import LED sign controller
try:
    from led_sign_controller import LEDSignController, MessagePriority, Color, FontSize, Effect, Speed
    LED_AVAILABLE = True
except ImportError:
    LED_AVAILABLE = False
    print("Warning: LED sign controller not available")

# Configure timezone
UTC_TZ = pytz.UTC
PUTNAM_COUNTY_TZ = pytz.timezone('America/New_York')

def utc_now():
    """Get current UTC time"""
    return datetime.now(UTC_TZ)

def local_now():
    """Get current local time"""
    return datetime.now(PUTNAM_COUNTY_TZ)

def parse_nws_datetime(dt_string):
    """Parse NWS datetime string with timezone handling"""
    if not dt_string:
        return None

    try:
        # Handle different datetime formats from NWS
        for fmt in [
            '%Y-%m-%dT%H:%M:%S%z',
            '%Y-%m-%dT%H:%M:%S.%f%z',
            '%Y-%m-%dT%H:%M:%SZ',
            '%Y-%m-%dT%H:%M:%S.%fZ'
        ]:
            try:
                if dt_string.endswith('Z'):
                    dt_string = dt_string[:-1] + '+00:00'
                dt = datetime.strptime(dt_string, fmt)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=UTC_TZ)
                return dt.astimezone(UTC_TZ)
            except ValueError:
                continue
    except Exception as e:
        logging.warning(f"Could not parse datetime: {dt_string} - {e}")

    return None

def format_local_datetime(dt, include_utc=True):
    """Format datetime in local time"""
    if not dt:
        return "Unknown"
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC_TZ)
    local_dt = dt.astimezone(PUTNAM_COUNTY_TZ)
    local_str = local_dt.strftime('%B %d, %Y at %I:%M %p %Z')
    if include_utc:
        utc_str = dt.astimezone(UTC_TZ).strftime('%H:%M UTC')
        return f"{local_str} ({utc_str})"
    return local_str

def format_local_date(dt):
    """Format date in local time"""
    if not dt:
        return "Unknown"
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC_TZ)
    local_dt = dt.astimezone(PUTNAM_COUNTY_TZ)
    return local_dt.strftime('%B %d, %Y')

def format_local_time(dt):
    """Format time only in local time"""
    if not dt:
        return "Unknown"
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC_TZ)
    local_dt = dt.astimezone(PUTNAM_COUNTY_TZ)
    utc_dt = dt.astimezone(UTC_TZ)
    local_str = local_dt.strftime('%I:%M %p %Z')
    utc_str = utc_dt.strftime('%H:%M UTC')
    return f"{local_str} ({utc_str})"

def is_alert_expired(expires_dt):
    """Check if alert is expired"""
    if not expires_dt:
        return False
    if expires_dt.tzinfo is None:
        expires_dt = expires_dt.replace(tzinfo=UTC_TZ)
    return expires_dt < utc_now()

# Initialize Flask app
app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-key-change-in-production')

# Database configuration
DATABASE_URL = os.environ.get('DATABASE_URL', 'postgresql://noaa_user:rkhkeq@localhost:5432/noaa_alerts')
app.config['SQLALCHEMY_DATABASE_URI'] = DATABASE_URL
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
    'pool_pre_ping': True,
    'pool_recycle': 3600,
    'connect_args': {'connect_timeout': 10}
}

# Initialize database
db = SQLAlchemy(app)

# LED Sign configuration
LED_SIGN_IP = os.environ.get('LED_SIGN_IP', '192.168.1.100')
LED_SIGN_PORT = int(os.environ.get('LED_SIGN_PORT', '10001'))

# Global LED controller
led_controller = None

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('/home/pi/noaa_alerts_system/logs/app.log')
    ]
)
logger = logging.getLogger(__name__)

# Database Models
class Boundary(db.Model):
    __tablename__ = 'boundaries'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False)
    type = db.Column(db.String(50), nullable=False)
    description = db.Column(db.Text)
    geom = db.Column(Geometry('MULTIPOLYGON', srid=4326))
    created_at = db.Column(db.DateTime, default=utc_now)
    updated_at = db.Column(db.DateTime, default=utc_now, onupdate=utc_now)

class CAPAlert(db.Model):
    __tablename__ = 'cap_alerts'

    id = db.Column(db.Integer, primary_key=True)
    identifier = db.Column(db.String(255), unique=True, nullable=False)
    sent = db.Column(db.DateTime, nullable=False)
    expires = db.Column(db.DateTime)
    status = db.Column(db.String(50))
    message_type = db.Column(db.String(50))
    scope = db.Column(db.String(50))
    category = db.Column(db.String(50))
    event = db.Column(db.String(100))
    urgency = db.Column(db.String(50))
    severity = db.Column(db.String(50))
    certainty = db.Column(db.String(50))
    area_desc = db.Column(db.Text)
    headline = db.Column(db.Text)
    description = db.Column(db.Text)
    instruction = db.Column(db.Text)
    geometry = db.Column(Geometry('GEOMETRY'))
    raw_json = db.Column(db.JSON)
    created_at = db.Column(db.DateTime, default=utc_now)
    updated_at = db.Column(db.DateTime, default=utc_now, onupdate=utc_now)

class AlertIntersection(db.Model):
    __tablename__ = 'alert_intersections'

    id = db.Column(db.Integer, primary_key=True)
    alert_id = db.Column(db.Integer, db.ForeignKey('cap_alerts.id'), nullable=False)
    boundary_id = db.Column(db.Integer, db.ForeignKey('boundaries.id'), nullable=False)
    intersection_area = db.Column(db.Float)
    intersection_percentage = db.Column(db.Float)
    created_at = db.Column(db.DateTime, default=utc_now)

    alert = db.relationship('CAPAlert', backref='intersections')
    boundary = db.relationship('Boundary', backref='alert_intersections')

class SystemLog(db.Model):
    __tablename__ = 'system_logs'

    id = db.Column(db.Integer, primary_key=True)
    timestamp = db.Column(db.DateTime, default=utc_now)
    level = db.Column(db.String(20))
    message = db.Column(db.Text)
    module = db.Column(db.String(50))
    details = db.Column(db.JSON)

class PollHistory(db.Model):
    __tablename__ = 'poll_history'

    id = db.Column(db.Integer, primary_key=True)
    timestamp = db.Column(db.DateTime, default=utc_now)
    alerts_fetched = db.Column(db.Integer, default=0)
    alerts_new = db.Column(db.Integer, default=0)
    alerts_updated = db.Column(db.Integer, default=0)
    execution_time_ms = db.Column(db.Integer)
    status = db.Column(db.String(20))
    error_message = db.Column(db.Text)

class LEDMessage(db.Model):
    __tablename__ = 'led_messages'

    id = db.Column(db.Integer, primary_key=True)
    message_type = db.Column(db.String(50))  # 'alert', 'canned', 'custom', 'emergency'
    content = db.Column(db.Text)
    priority = db.Column(db.Integer)
    color = db.Column(db.String(20))
    font_size = db.Column(db.String(20))
    effect = db.Column(db.String(20))
    speed = db.Column(db.String(20))
    display_time = db.Column(db.Integer)
    scheduled_time = db.Column(db.DateTime)
    expires_at = db.Column(db.DateTime)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=utc_now)
    sent_at = db.Column(db.DateTime)
    alert_id = db.Column(db.Integer, db.ForeignKey('cap_alerts.id'), nullable=True)

    alert = db.relationship('CAPAlert', backref='led_messages')

class LEDSignStatus(db.Model):
    __tablename__ = 'led_sign_status'

    id = db.Column(db.Integer, primary_key=True)
    sign_ip = db.Column(db.String(45))
    is_connected = db.Column(db.Boolean, default=False)
    last_message = db.Column(db.Text)
    last_update = db.Column(db.DateTime)
    error_count = db.Column(db.Integer, default=0)
    last_error = db.Column(db.Text)
    firmware_version = db.Column(db.String(50))
    brightness_level = db.Column(db.Integer, default=10)

# Helper functions
def get_active_alerts_query():
    """Get query for active alerts"""
    return CAPAlert.query.filter(
        or_(
            CAPAlert.expires.is_(None),
            CAPAlert.expires > utc_now()
        )
    )

def get_expired_alerts_query():
    """Get query for expired alerts"""
    return CAPAlert.query.filter(
        and_(
            CAPAlert.expires.isnot(None),
            CAPAlert.expires <= utc_now()
        )
    )

def get_active_alerts():
    """Get currently active alerts"""
    return get_active_alerts_query().order_by(
        CAPAlert.severity.desc(),
        CAPAlert.sent.desc()
    ).all()

def ensure_multipolygon(geometry):
    """Convert Polygon to MultiPolygon if needed"""
    if geometry and geometry.get('type') == 'Polygon':
        return {
            'type': 'MultiPolygon',
            'coordinates': [geometry['coordinates']]
        }
    return geometry

def get_system_health():
    """Get comprehensive system health information"""
    try:
        import platform
        uname = platform.uname()
        boot_time = psutil.boot_time()

        # CPU information
        cpu_info = {
            'percent': psutil.cpu_percent(interval=1),
            'count': psutil.cpu_count(),
            'freq': psutil.cpu_freq()._asdict() if psutil.cpu_freq() else None
        }

        # Memory information
        memory = psutil.virtual_memory()
        memory_info = {
            'total': memory.total,
            'available': memory.available,
            'percent': memory.percent,
            'used': memory.used,
            'free': memory.free
        }

        # Disk information
        disk = psutil.disk_usage('/')
        disk_info = {
            'total': disk.total,
            'used': disk.used,
            'free': disk.free,
            'percent': (disk.used / disk.total) * 100
        }

        # Load averages (Linux only)
        load_averages = None
        try:
            load_averages = os.getloadavg()
        except (OSError, AttributeError):
            pass

        # Database status
        db_status = 'unknown'
        db_info = {}
        try:
            result = db.session.execute(text('SELECT version()'))
            db_status = 'connected'
            db_info = {'version': result.scalar()}
        except Exception as e:
            db_status = f'error: {str(e)}'

        # Process information
        processes = []
        for proc in psutil.process_iter(['pid', 'name', 'cpu_percent', 'memory_percent']):
            try:
                proc_info = proc.info
                if proc_info['cpu_percent'] > 1 or proc_info['memory_percent'] > 1:
                    processes.append(proc_info)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass

        processes.sort(key=lambda x: x['cpu_percent'], reverse=True)
        process_info = processes[:10]  # Top 10 processes

        # Network information
        network_info = {}
        try:
            net_io = psutil.net_io_counters()
            network_info = {
                'bytes_sent': net_io.bytes_sent,
                'bytes_recv': net_io.bytes_recv,
                'packets_sent': net_io.packets_sent,
                'packets_recv': net_io.packets_recv
            }
        except:
            pass

        # Service status
        services_status = {}
        services_to_check = ['postgresql', 'apache2', 'nginx']
        for service in services_to_check:
            try:
                result = subprocess.run(['systemctl', 'is-active', service],
                                        capture_output=True, text=True, timeout=5)
                services_status[service] = result.stdout.strip()
            except:
                services_status[service] = 'unknown'

        # Temperature information (if available)
        temperature_info = {}
        try:
            temps = psutil.sensors_temperatures()
            if temps:
                for name, entries in temps.items():
                    temperature_info[name] = []
                    for entry in entries:
                        temperature_info[name].append({
                            'label': entry.label or 'Unknown',
                            'current': entry.current,
                            'high': entry.high,
                            'critical': entry.critical
                        })
        except:
            pass

        return {
            'timestamp': utc_now().isoformat(),
            'local_timestamp': local_now().isoformat(),
            'system': {
                'hostname': uname.node,
                'system': uname.system,
                'release': uname.release,
                'version': uname.version,
                'machine': uname.machine,
                'processor': uname.processor,
                'boot_time': datetime.fromtimestamp(boot_time, UTC_TZ).isoformat(),
                'uptime_seconds': time.time() - boot_time
            },
            'cpu': cpu_info,
            'memory': memory_info,
            'disk': disk_info,
            'network': network_info,
            'processes': process_info,
            'load_averages': load_averages,
            'database': {
                'status': db_status,
                'info': db_info
            },
            'services': services_status,
            'temperature': temperature_info
        }

    except Exception as e:
        logger.error(f"Error getting system health: {str(e)}")
        return {
            'error': str(e),
            'timestamp': utc_now().isoformat(),
            'local_timestamp': local_now().isoformat()
        }

def format_bytes(bytes_value):
    """Format bytes into human readable format"""
    if bytes_value == 0:
        return "0 B"

    size_names = ["B", "KB", "MB", "GB", "TB", "PB"]
    import math
    i = int(math.floor(math.log(bytes_value, 1024)))
    p = math.pow(1024, i)
    s = round(bytes_value / p, 2)
    return f"{s} {size_names[i]}"

def format_uptime(seconds):
    """Format uptime seconds into human readable format"""
    days = int(seconds // 86400)
    hours = int((seconds % 86400) // 3600)
    minutes = int((seconds % 3600) // 60)

    if days > 0:
        return f"{days}d {hours}h {minutes}m"
    elif hours > 0:
        return f"{hours}h {minutes}m"
    else:
        return f"{minutes}m"

# Initialize LED controller
def init_led_controller():
    """Initialize the LED sign controller"""
    global led_controller
    if not LED_AVAILABLE:
        logger.warning("LED controller not available - skipping initialization")
        return

    try:
        led_controller = LEDSignController(LED_SIGN_IP, LED_SIGN_PORT)
        logger.info(f"LED controller initialized for {LED_SIGN_IP}:{LED_SIGN_PORT}")

        # Update database status
        status = LEDSignStatus.query.filter_by(sign_ip=LED_SIGN_IP).first()
        if not status:
            status = LEDSignStatus(sign_ip=LED_SIGN_IP)
            db.session.add(status)

        status.is_connected = led_controller.connected
        status.last_update = utc_now()
        db.session.commit()

    except Exception as e:
        logger.error(f"Failed to initialize LED controller: {e}")
        led_controller = None

def update_led_display():
    """Update LED display with current alerts"""
    if not led_controller:
        return False

    try:
        active_alerts = get_active_alerts()

        if active_alerts:
            # Create LED message record
            alert = active_alerts[0]  # Show most severe alert
            led_message = LEDMessage(
                message_type='alert',
                content=f"{alert.event}: {alert.headline}",
                priority=0 if alert.severity in ['Extreme', 'Severe'] else 1,
                alert_id=alert.id,
                scheduled_time=utc_now(),
                expires_at=alert.expires
            )
            db.session.add(led_message)
            db.session.commit()

            # Send to LED sign
            result = led_controller.display_alerts(active_alerts)
            if result:
                led_message.sent_at = utc_now()
                db.session.commit()

            return result
        else:
            # Show default message
            led_message = LEDMessage(
                message_type='canned',
                content='no_alerts',
                priority=3,
                scheduled_time=utc_now()
            )
            db.session.add(led_message)
            db.session.commit()

            result = led_controller.display_default_message()
            if result:
                led_message.sent_at = utc_now()
                db.session.commit()

            return result

    except Exception as e:
        logger.error(f"Error updating LED display: {e}")
        return False

# Template filters
@app.template_filter('nl2br')
def nl2br_filter(text):
    """Convert newlines to HTML br tags"""
    if not text:
        return ""
    return text.replace('\n', '<br>\n')

@app.template_filter('format_local_datetime')
def format_local_datetime_filter(dt, include_utc=True):
    return format_local_datetime(dt, include_utc)

@app.template_filter('format_local_date')
def format_local_date_filter(dt):
    return format_local_date(dt)

@app.template_filter('format_local_time')
def format_local_time_filter(dt):
    return format_local_time(dt)

@app.template_filter('is_expired')
def is_expired_filter(expires_date):
    return is_alert_expired(expires_date)

@app.template_global()
def current_time():
    """Provide current datetime to templates"""
    return utc_now()

@app.template_global()
def local_current_time():
    """Provide current local datetime to templates"""
    return local_now()

# Routes
@app.route('/')
def index():
    """Main dashboard with map"""
    try:
        return render_template('index.html')
    except Exception as e:
        logger.error(f"Error rendering index: {e}")
        return f"<h1>NOAA CAP Alerts System</h1><p>Map interface loading...</p><p><a href='/stats'>📊 Statistics</a> | <a href='/alerts'>📝 Alerts History</a> | <a href='/admin'>⚙️ Admin</a></p>"

@app.route('/admin')
def admin():
    """Enhanced admin interface"""
    try:
        # Get system stats
        total_boundaries = Boundary.query.count()
        total_alerts = CAPAlert.query.count()
        active_alerts = get_active_alerts_query().count()
        expired_alerts = get_expired_alerts_query().count()

        # Get boundary counts by type
        boundary_stats = db.session.query(
            Boundary.type, func.count(Boundary.id).label('count')
        ).group_by(Boundary.type).all()

        # Get LED status
        led_status = None
        if led_controller:
            led_status = led_controller.get_status()

        # Get recent LED messages
        recent_led_messages = LEDMessage.query.order_by(
            LEDMessage.created_at.desc()
        ).limit(10).all()

        return render_template('admin.html',
                               total_boundaries=total_boundaries,
                               total_alerts=total_alerts,
                               active_alerts=active_alerts,
                               expired_alerts=expired_alerts,
                               boundary_stats=boundary_stats,
                               led_status=led_status,
                               recent_led_messages=recent_led_messages)
    except Exception as e:
        logger.error(f"Error loading admin: {e}")
        return f"<h1>Admin Error</h1><p>{e}</p><p><a href='/'>← Back to Main</a></p>"

@app.route('/stats')
def stats():
    """Comprehensive statistics page"""
    try:
        stats_data = {}

        # Basic alert statistics
        total_alerts = CAPAlert.query.count()
        active_alerts = get_active_alerts_query().count()
        expired_alerts = get_expired_alerts_query().count()

        stats_data.update({
            'total_alerts': total_alerts,
            'active_alerts': active_alerts,
            'expired_alerts': expired_alerts
        })

        # Alert statistics by severity
        severity_stats = db.session.query(
            CAPAlert.severity, func.count(CAPAlert.id).label('count')
        ).group_by(CAPAlert.severity).all()

        stats_data['severity_breakdown'] = {
            severity: count for severity, count in severity_stats
        }

        # Alert statistics by event type
        event_stats = db.session.query(
            CAPAlert.event, func.count(CAPAlert.id).label('count')
        ).group_by(CAPAlert.event).order_by(func.count(CAPAlert.id).desc()).limit(10).all()

        stats_data['top_events'] = event_stats

        # Polling statistics
        try:
            total_polls = PollHistory.query.count()
            if total_polls > 0:
                poll_stats = db.session.query(
                    func.avg(PollHistory.alerts_fetched).label('avg_fetched'),
                    func.max(PollHistory.alerts_fetched).label('max_fetched'),
                    func.avg(PollHistory.execution_time_ms).label('avg_time_ms')
                ).first()

                successful_polls = PollHistory.query.filter_by(status='SUCCESS').count()
                failed_polls = PollHistory.query.filter(PollHistory.status != 'SUCCESS').count()

                stats_data['polling'] = {
                    'total_polls': total_polls,
                    'avg_fetched': round(poll_stats.avg_fetched or 0, 1),
                    'max_fetched': poll_stats.max_fetched or 0,
                    'avg_time_ms': round(poll_stats.avg_time_ms or 0, 1),
                    'successful_polls': successful_polls,
                    'failed_polls': failed_polls,
                    'success_rate': round((successful_polls / total_polls * 100), 1) if total_polls > 0 else 0,
                    'data_source': 'poll_history'
                }
            else:
                stats_data['polling'] = {
                    'total_polls': 0, 'avg_fetched': 0, 'max_fetched': 0,
                    'avg_time_ms': 0, 'successful_polls': 0, 'failed_polls': 0,
                    'success_rate': 0, 'data_source': 'no_data'
                }
        except Exception as e:
            logger.error(f"Error getting polling stats: {str(e)}")
            stats_data['polling'] = {
                'total_polls': 0, 'avg_fetched': 0, 'max_fetched': 0,
                'avg_time_ms': 0, 'successful_polls': 0, 'failed_polls': 0,
                'success_rate': 0, 'data_source': 'error'
            }

        # LED statistics
        try:
            led_messages_total = LEDMessage.query.count()
            led_messages_sent = LEDMessage.query.filter(LEDMessage.sent_at.isnot(None)).count()
            led_last_message = LEDMessage.query.order_by(LEDMessage.created_at.desc()).first()

            stats_data['led_stats'] = {
                'total_messages': led_messages_total,
                'sent_messages': led_messages_sent,
                'success_rate': round((led_messages_sent / led_messages_total * 100), 1) if led_messages_total > 0 else 0,
                'last_message_time': led_last_message.created_at.isoformat() if led_last_message else None,
                'controller_available': led_controller is not None,
                'sign_connected': led_controller.connected if led_controller else False
            }
        except Exception as e:
            logger.error(f"Error getting LED stats: {str(e)}")
            stats_data['led_stats'] = {
                'total_messages': 0, 'sent_messages': 0, 'success_rate': 0,
                'last_message_time': None, 'controller_available': False, 'sign_connected': False
            }

        # Fun statistics
        try:
            longest_headline = db.session.query(
                func.max(func.length(CAPAlert.headline)).label('max_length')
            ).scalar() or 0

            most_common_word = db.session.query(
                CAPAlert.event
            ).group_by(CAPAlert.event).order_by(func.count(CAPAlert.event).desc()).first()

            stats_data['fun_stats'] = {
                'longest_headline': longest_headline,
                'most_common_event': most_common_word[0] if most_common_word else 'None'
            }
        except Exception as e:
            logger.error(f"Error getting fun stats: {str(e)}")
            stats_data['fun_stats'] = {'longest_headline': 0, 'most_common_event': 'None'}

        # Add utility functions to template context
        stats_data['format_bytes'] = format_bytes
        stats_data['format_uptime'] = format_uptime

        return render_template('stats.html', **stats_data)

    except Exception as e:
        logger.error(f"Error loading statistics: {str(e)}")
        return f"<h1>Error loading statistics</h1><p>{str(e)}</p><p><a href='/'>← Back to Main</a></p>"

@app.route('/alerts')
def alerts():
    """Alerts history page with enhanced filtering"""
    try:
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 50, type=int)

        status_filter = request.args.get('status', '')
        severity_filter = request.args.get('severity', '')
        event_filter = request.args.get('event', '')
        search_query = request.args.get('search', '')
        show_expired = request.args.get('show_expired', 'false').lower() == 'true'

        query = CAPAlert.query

        if status_filter:
            query = query.filter(CAPAlert.status == status_filter)

        if severity_filter:
            query = query.filter(CAPAlert.severity == severity_filter)

        if event_filter:
            query = query.filter(CAPAlert.event.ilike(f'%{event_filter}%'))

        if search_query:
            search_term = f'%{search_query}%'
            query = query.filter(
                or_(
                    CAPAlert.headline.ilike(search_term),
                    CAPAlert.description.ilike(search_term),
                    CAPAlert.area_desc.ilike(search_term),
                    CAPAlert.event.ilike(search_term)
                )
            )

        if not show_expired:
            # Use our helper function for consistent active alerts logic
            now = utc_now()
            query = query.filter(
                or_(
                    CAPAlert.expires.is_(None),
                    CAPAlert.expires > now
                )
            )

        # Order by sent date descending
        query = query.order_by(CAPAlert.sent.desc())

        # Paginate results
        alerts_paginated = query.paginate(page=page, per_page=per_page, error_out=False)

        # Get filter options for dropdowns
        available_severities = db.session.query(CAPAlert.severity).distinct().all()
        available_events = db.session.query(CAPAlert.event).distinct().order_by(CAPAlert.event).all()
        available_statuses = db.session.query(CAPAlert.status).distinct().all()

        return render_template('alerts.html',
                               alerts=alerts_paginated,
                               current_filters={
                                   'status': status_filter,
                                   'severity': severity_filter,
                                   'event': event_filter,
                                   'search': search_query,
                                   'show_expired': show_expired
                               },
                               available_severities=[s[0] for s in available_severities if s[0]],
                               available_events=[e[0] for e in available_events if e[0]],
                               available_statuses=[s[0] for s in available_statuses if s[0]])

    except Exception as e:
        logger.error(f"Error loading alerts: {str(e)}")
        return f"<h1>Error loading alerts</h1><p>{str(e)}</p><p><a href='/'>← Back to Main</a></p>"

@app.route('/system_health')
def system_health():
    """System health monitoring page"""
    try:
        health_data = get_system_health()
        return render_template('system_health.html', health=health_data)
    except Exception as e:
        logger.error(f"Error loading system health: {str(e)}")
        return f"<h1>System Health Error</h1><p>{str(e)}</p><p><a href='/'>← Back to Main</a></p>"

# API Routes
@app.route('/api/system_status')
def api_system_status():
    """Get comprehensive system status including LED"""
    try:
        # Get basic stats
        total_alerts = CAPAlert.query.count()
        active_alerts_count = len(get_active_alerts())

        # Get LED status
        led_status = 'disconnected'
        if led_controller and led_controller.connected:
            led_status = 'connected'
        elif led_controller:
            led_status = 'error'

        # Get recent system activity
        recent_logs = SystemLog.query.order_by(
            SystemLog.timestamp.desc()
        ).limit(5).all()

        return jsonify({
            'timestamp': utc_now().isoformat(),
            'local_timestamp': local_now().isoformat(),
            'total_alerts': total_alerts,
            'active_alerts_count': active_alerts_count,
            'led_sign_status': led_status,
            'led_sign_ip': LED_SIGN_IP,
            'database_status': 'connected',
            'recent_activity': [
                {
                    'timestamp': log.timestamp.isoformat(),
                    'level': log.level,
                    'message': log.message,
                    'module': log.module
                }
                for log in recent_logs
            ]
        })

    except Exception as e:
        logger.error(f"Error getting system status: {e}")
        return jsonify({'error': str(e)})

@app.route('/api/alerts')
def api_alerts():
    """Get alerts data for AJAX requests"""
    try:
        active_only = request.args.get('active_only', 'false').lower() == 'true'
        limit = request.args.get('limit', 50, type=int)

        if active_only:
            alerts = get_active_alerts()[:limit]
        else:
            alerts = CAPAlert.query.order_by(CAPAlert.sent.desc()).limit(limit).all()

        return jsonify({
            'alerts': [
                {
                    'id': alert.id,
                    'identifier': alert.identifier,
                    'event': alert.event,
                    'severity': alert.severity,
                    'urgency': alert.urgency,
                    'headline': alert.headline,
                    'description': alert.description,
                    'area_desc': alert.area_desc,
                    'sent': alert.sent.isoformat() if alert.sent else None,
                    'expires': alert.expires.isoformat() if alert.expires else None,
                    'is_expired': is_alert_expired(alert.expires),
                    'created_at': alert.created_at.isoformat(),
                    'geometry': alert.geometry
                }
                for alert in alerts
            ],
            'total_count': len(alerts),
            'timestamp': utc_now().isoformat()
        })

    except Exception as e:
        logger.error(f"Error getting alerts API: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/boundaries')
def api_boundaries():
    """Get boundaries data for map display"""
    try:
        boundary_type = request.args.get('type')

        query = Boundary.query
        if boundary_type:
            query = query.filter(Boundary.type == boundary_type)

        boundaries = query.all()

        return jsonify({
            'boundaries': [
                {
                    'id': boundary.id,
                    'name': boundary.name,
                    'type': boundary.type,
                    'description': boundary.description,
                    'geometry': boundary.geometry
                }
                for boundary in boundaries
            ],
            'total_count': len(boundaries),
            'timestamp': utc_now().isoformat()
        })

    except Exception as e:
        logger.error(f"Error getting boundaries API: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/trigger_poll', methods=['POST'])
def api_trigger_poll():
    """Manually trigger CAP polling and LED update"""
    try:
        # Run the CAP poller script
        poller_script = '/home/pi/noaa_alerts_system/poller/cap_poller.py'
        if os.path.exists(poller_script):
            try:
                result = subprocess.run(
                    ['python3', poller_script, '--log-level', 'INFO'],
                    cwd='/home/pi/noaa_alerts_system',
                    capture_output=True,
                    text=True,
                    timeout=120
                )

                if result.returncode == 0:
                    poll_success = True
                    poll_message = "CAP polling completed successfully"
                else:
                    poll_success = False
                    poll_message = f"CAP polling failed: {result.stderr}"
            except subprocess.TimeoutExpired:
                poll_success = False
                poll_message = "CAP polling timed out"
            except Exception as e:
                poll_success = False
                poll_message = f"CAP polling error: {str(e)}"
        else:
            poll_success = False
            poll_message = "CAP poller script not found"

        # Update LED display with current alerts
        led_updated = update_led_display()

        # Log the manual trigger
        log_entry = SystemLog(
            level='INFO',
            message='Manual CAP poll and LED update triggered',
            module='admin',
            details={
                'triggered_by': 'web_interface',
                'poll_success': poll_success,
                'poll_message': poll_message,
                'led_updated': led_updated,
                'timestamp': utc_now().isoformat()
            }
        )
        db.session.add(log_entry)
        db.session.commit()

        return jsonify({
            'success': poll_success,
            'poll_message': poll_message,
            'led_updated': led_updated,
            'timestamp': utc_now().isoformat()
        })

    except Exception as e:
        logger.error(f"Error triggering poll: {e}")
        return jsonify({'success': False, 'error': str(e)})

# LED Sign API Routes
@app.route('/api/led/send_message', methods=['POST'])
def api_led_send_message():
    """Send custom message to LED sign"""
    try:
        data = request.get_json()

        if not led_controller:
            return jsonify({'success': False, 'error': 'LED controller not available'})

        # Extract parameters with defaults
        text = data.get('text', '')
        if not text:
            return jsonify({'success': False, 'error': 'Message text is required'})

        color_name = data.get('color', 'GREEN')
        font_name = data.get('font', 'MEDIUM')
        effect_name = data.get('effect', 'IMMEDIATE')
        speed_name = data.get('speed', 'MEDIUM')
        hold_time = int(data.get('hold_time', 5))
        priority_value = int(data.get('priority', MessagePriority.NORMAL.value))

        try:
            color = Color[color_name.upper()]
            font = FontSize[font_name.upper()]
            effect = Effect[effect_name.upper()]
            speed = Speed[speed_name.upper()]
            priority = MessagePriority(priority_value)
        except (KeyError, ValueError) as e:
            return jsonify({'success': False, 'error': f'Invalid parameter: {str(e)}'})

        # Create database record
        led_message = LEDMessage(
            message_type='custom',
            content=text,
            priority=priority.value,
            color=color.name,
            font_size=font.name,
            effect=effect.name,
            speed=speed.name,
            display_time=hold_time,
            scheduled_time=utc_now()
        )
        db.session.add(led_message)
        db.session.commit()

        # Send to LED sign
        result = led_controller.send_message(
            text=text,
            color=color,
            font=font,
            effect=effect,
            speed=speed,
            hold_time=hold_time,
            priority=priority
        )

        if result:
            led_message.sent_at = utc_now()
            db.session.commit()

        return jsonify({
            'success': result,
            'message_id': led_message.id,
            'timestamp': utc_now().isoformat()
        })

    except Exception as e:
        logger.error(f"Error sending LED message: {e}")
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/led/send_canned', methods=['POST'])
def api_led_send_canned():
    """Send canned message to LED sign"""
    try:
        data = request.get_json()
        message_name = data.get('message_name')
        parameters = data.get('parameters', {})

        if not message_name:
            return jsonify({'success': False, 'error': 'Message name is required'})

        if not led_controller:
            return jsonify({'success': False, 'error': 'LED controller not available'})

        # Create database record
        led_message = LEDMessage(
            message_type='canned',
            content=message_name,
            priority=2,  # Normal priority for canned messages
            scheduled_time=utc_now()
        )
        db.session.add(led_message)
        db.session.commit()

        # Send to LED sign
        result = led_controller.send_canned_message(message_name, **parameters)

        if result:
            led_message.sent_at = utc_now()
            db.session.commit()

        return jsonify({
            'success': result,
            'message_id': led_message.id,
            'timestamp': utc_now().isoformat()
        })

    except Exception as e:
        logger.error(f"Error sending canned message: {e}")
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/led/clear', methods=['POST'])
def api_led_clear():
    """Clear LED display"""
    try:
        if not led_controller:
            return jsonify({'success': False, 'error': 'LED controller not available'})

        result = led_controller.clear_display()

        if result:
            # Log the clear action
            led_message = LEDMessage(
                message_type='system',
                content='DISPLAY_CLEARED',
                priority=1,
                scheduled_time=utc_now(),
                sent_at=utc_now()
            )
            db.session.add(led_message)
            db.session.commit()

        return jsonify({'success': result, 'timestamp': utc_now().isoformat()})

    except Exception as e:
        logger.error(f"Error clearing LED display: {e}")
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/led/brightness', methods=['POST'])
def api_led_brightness():
    """Set LED display brightness"""
    try:
        data = request.get_json()
        brightness = int(data.get('brightness', 10))

        if not 1 <= brightness <= 16:
            return jsonify({'success': False, 'error': 'Brightness must be between 1 and 16'})

        if not led_controller:
            return jsonify({'success': False, 'error': 'LED controller not available'})

        result = led_controller.set_brightness(brightness)

        if result:
            # Update database status
            status = LEDSignStatus.query.filter_by(sign_ip=LED_SIGN_IP).first()
            if status:
                status.brightness_level = brightness
                status.last_update = utc_now()
                db.session.commit()

        return jsonify({'success': result, 'brightness': brightness})

    except Exception as e:
        logger.error(f"Error setting LED brightness: {e}")
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/led/test', methods=['POST'])
def api_led_test():
    """Run LED sign feature test"""
    try:
        if not led_controller:
            return jsonify({'success': False, 'error': 'LED controller not available'})

        result = led_controller.test_all_features()

        # Log the test
        led_message = LEDMessage(
            message_type='system',
            content='FEATURE_TEST',
            priority=1,
            scheduled_time=utc_now(),
            sent_at=utc_now() if result else None
        )
        db.session.add(led_message)
        db.session.commit()

        return jsonify({'success': result, 'message': 'Test sequence started'})

    except Exception as e:
        logger.error(f"Error running LED test: {e}")
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/led/emergency', methods=['POST'])
def api_led_emergency():
    """Send emergency override message"""
    try:
        data = request.get_json()
        message = data.get('message', 'EMERGENCY ALERT')
        duration = int(data.get('duration', 30))

        if not led_controller:
            return jsonify({'success': False, 'error': 'LED controller not available'})

        # Create database record
        led_message = LEDMessage(
            message_type='emergency',
            content=message,
            priority=0,  # Highest priority
            display_time=duration,
            scheduled_time=utc_now()
        )
        db.session.add(led_message)
        db.session.commit()

        result = led_controller.emergency_override(message, duration)

        if result:
            led_message.sent_at = utc_now()
            db.session.commit()

        return jsonify({
            'success': result,
            'message_id': led_message.id,
            'duration': duration
        })

    except Exception as e:
        logger.error(f"Error sending emergency message: {e}")
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/led/status')
def api_led_status():
    """Get LED sign status"""
    try:
        status = {
            'controller_available': led_controller is not None,
            'sign_ip': LED_SIGN_IP,
            'sign_port': LED_SIGN_PORT,
            'led_library_available': LED_AVAILABLE
        }

        if led_controller:
            status.update(led_controller.get_status())

        # Get database status
        db_status = LEDSignStatus.query.filter_by(sign_ip=LED_SIGN_IP).first()
        if db_status:
            status.update({
                'brightness_level': db_status.brightness_level,
                'error_count': db_status.error_count,
                'last_error': db_status.last_error,
                'last_database_update': db_status.last_update.isoformat() if db_status.last_update else None
            })

        return jsonify(status)

    except Exception as e:
        logger.error(f"Error getting LED status: {e}")
        return jsonify({'error': str(e)})

@app.route('/api/led/messages')
def api_led_messages():
    """Get LED message history"""
    try:
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 20, type=int)

        messages = LEDMessage.query.order_by(
            LEDMessage.created_at.desc()
        ).paginate(page=page, per_page=per_page, error_out=False)

        return jsonify({
            'messages': [
                {
                    'id': msg.id,
                    'type': msg.message_type,
                    'content': msg.content,
                    'priority': msg.priority,
                    'color': msg.color,
                    'font_size': msg.font_size,
                    'effect': msg.effect,
                    'speed': msg.speed,
                    'display_time': msg.display_time,
                    'created_at': msg.created_at.isoformat(),
                    'sent_at': msg.sent_at.isoformat() if msg.sent_at else None,
                    'is_active': msg.is_active,
                    'alert_id': msg.alert_id
                }
                for msg in messages.items
            ],
            'total': messages.total,
            'pages': messages.pages,
            'current_page': page
        })

    except Exception as e:
        logger.error(f"Error getting LED messages: {e}")
        return jsonify({'error': str(e)})

@app.route('/api/led/canned_messages')
def api_led_canned_messages():
    """Get available canned messages"""
    try:
        if not led_controller:
            return jsonify({'canned_messages': []})

        canned_messages = []
        for name, config in led_controller.canned_messages.items():
            canned_messages.append({
                'name': name,
                'text': config['text'],
                'color': config['color'].name,
                'font': config['font'].name,
                'effect': config['effect'].name,
                'priority': config['priority'].name
            })

        return jsonify({'canned_messages': canned_messages})

    except Exception as e:
        logger.error(f"Error getting canned messages: {e}")
        return jsonify({'error': str(e)})

# Background maintenance task
def led_maintenance_task():
    """Background task for LED maintenance"""
    while True:
        try:
            if led_controller:
                # Check connection status
                if not led_controller.connected:
                    logger.warning("LED controller disconnected, attempting reconnect")
                    led_controller.connect()

                # Update display with current alerts every 5 minutes
                update_led_display()

                # Update database status
                status = LEDSignStatus.query.filter_by(sign_ip=LED_SIGN_IP).first()
                if status:
                    status.is_connected = led_controller.connected
                    status.last_update = utc_now()
                    if led_controller.last_message:
                        status.last_message = led_controller.last_message
                    db.session.commit()

            time.sleep(300)  # 5 minutes

        except Exception as e:
            logger.error(f"Error in LED maintenance task: {e}")
            time.sleep(60)  # Wait 1 minute before retry

# Error handlers
@app.errorhandler(404)
def not_found(error):
    return render_template('error.html',
                           error_code=404,
                           error_message="Page not found"), 404

@app.errorhandler(500)
def internal_error(error):
    return render_template('error.html',
                           error_code=500,
                           error_message="Internal server error"), 500

# Initialize the application
def create_app():
    """Application factory"""
    with app.app_context():
        try:
            # Create tables
            db.create_all()
            logger.info("Database tables created/verified")

            # Initialize LED controller
            if LED_AVAILABLE:
                init_led_controller()
            else:
                logger.warning("LED functionality disabled - controller not available")

            # Start background maintenance task
            if led_controller:
                maintenance_thread = threading.Thread(target=led_maintenance_task, daemon=True)
                maintenance_thread.start()
                logger.info("LED maintenance task started")

            logger.info("Application initialized successfully")

        except Exception as e:
            logger.error(f"Error initializing application: {e}")

    return app

if __name__ == '__main__':
    # Create and run app
    app = create_app()
    app.run(debug=False, host='0.0.0.0', port=5000)#!/usr/bin/env python3
"""
Enhanced Flask application for NOAA CAP Alert System
Complete integration with LED sign control and existing CAP functionality
"""

import os
import sys
import json
import time
import logging
import threading
import subprocess
import psutil
import pytz
import hashlib
import requests
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from flask import Flask, render_template, request, jsonify, flash, redirect, url_for, send_file
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import create_engine, func, or_, text, desc, and_
from sqlalchemy.orm import sessionmaker
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.dialects.postgresql import UUID
from geoalchemy2 import Geometry, functions as geo_func
from geoalchemy2.shape import to_shape
import geoalchemy2
from shapely.geometry import Point, Polygon, MultiPolygon
from shapely import wkt
import folium
from folium import plugins
import requests
import xml.etree.ElementTree as ET

# Import LED sign controller
try:
    from led_sign_controller import LEDSignController, MessagePriority, Color, FontSize, Effect, Speed
    LED_AVAILABLE = True
except ImportError:
    LED_AVAILABLE = False
    print("Warning: LED sign controller not available")

# Configure timezone
UTC_TZ = pytz.UTC
PUTNAM_COUNTY_TZ = pytz.timezone('America/New_York')

def utc_now():
    """Get current UTC time"""
    return datetime.now(UTC_TZ)

def local_now():
    """Get current local time"""
    return datetime.now(PUTNAM_COUNTY_TZ)

def parse_nws_datetime(dt_string):
    """Parse NWS datetime string with timezone handling"""
    if not dt_string:
        return None

    try:
        # Handle different datetime formats from NWS
        for fmt in [
            '%Y-%m-%dT%H:%M:%S%z',
            '%Y-%m-%dT%H:%M:%S.%f%z',
            '%Y-%m-%dT%H:%M:%SZ',
            '%Y-%m-%dT%H:%M:%S.%fZ'
        ]:
            try:
                if dt_string.endswith('Z'):
                    dt_string = dt_string[:-1] + '+00:00'
                dt = datetime.strptime(dt_string, fmt)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=UTC_TZ)
                return dt.astimezone(UTC_TZ)
            except ValueError:
                continue
    except Exception as e:
        logging.warning(f"Could not parse datetime: {dt_string} - {e}")

    return None

def format_local_datetime(dt, include_utc=True):
    """Format datetime in local time"""
    if not dt:
        return "Unknown"
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC_TZ)
    local_dt = dt.astimezone(PUTNAM_COUNTY_TZ)
    local_str = local_dt.strftime('%B %d, %Y at %I:%M %p %Z')
    if include_utc:
        utc_str = dt.astimezone(UTC_TZ).strftime('%H:%M UTC')
        return f"{local_str} ({utc_str})"
    return local_str

def format_local_date(dt):
    """Format date in local time"""
    if not dt:
        return "Unknown"
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC_TZ)
    local_dt = dt.astimezone(PUTNAM_COUNTY_TZ)
    return local_dt.strftime('%B %d, %Y')

def format_local_time(dt):
    """Format time only in local time"""
    if not dt:
        return "Unknown"
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC_TZ)
    local_dt = dt.astimezone(PUTNAM_COUNTY_TZ)
    utc_dt = dt.astimezone(UTC_TZ)
    local_str = local_dt.strftime('%I:%M %p %Z')
    utc_str = utc_dt.strftime('%H:%M UTC')
    return f"{local_str} ({utc_str})"

def is_alert_expired(expires_dt):
    """Check if alert is expired"""
    if not expires_dt:
        return False
    if expires_dt.tzinfo is None:
        expires_dt = expires_dt.replace(tzinfo=UTC_TZ)
    return expires_dt < utc_now()

# Initialize Flask app
app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-key-change-in-production')

# Database configuration
DATABASE_URL = os.environ.get('DATABASE_URL', 'postgresql://noaa_user:rkhkeq@localhost:5432/noaa_alerts')
app.config['SQLALCHEMY_DATABASE_URI'] = DATABASE_URL
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
    'pool_pre_ping': True,
    'pool_recycle': 3600,
    'connect_args': {'connect_timeout': 10}
}

# Initialize database
db = SQLAlchemy(app)

# LED Sign configuration
LED_SIGN_IP = os.environ.get('LED_SIGN_IP', '192.168.1.100')
LED_SIGN_PORT = int(os.environ.get('LED_SIGN_PORT', '10001'))

# Global LED controller
led_controller = None

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('/home/pi/noaa_alerts_system/logs/app.log')
    ]
)
logger = logging.getLogger(__name__)

# Database Models
class Boundary(db.Model):
    __tablename__ = 'boundaries'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False)
    type = db.Column(db.String(50), nullable=False)
    description = db.Column(db.Text)
    geom = db.Column(Geometry('MULTIPOLYGON', srid=4326))
    created_at = db.Column(db.DateTime, default=utc_now)
    updated_at = db.Column(db.DateTime, default=utc_now, onupdate=utc_now)

class CAPAlert(db.Model):
    __tablename__ = 'cap_alerts'

    id = db.Column(db.Integer, primary_key=True)
    identifier = db.Column(db.String(255), unique=True, nullable=False)
    sent = db.Column(db.DateTime, nullable=False)
    expires = db.Column(db.DateTime)
    status = db.Column(db.String(50))
    message_type = db.Column(db.String(50))
    scope = db.Column(db.String(50))
    category = db.Column(db.String(50))
    event = db.Column(db.String(100))
    urgency = db.Column(db.String(50))
    severity = db.Column(db.String(50))
    certainty = db.Column(db.String(50))
    area_desc = db.Column(db.Text)
    headline = db.Column(db.Text)
    description = db.Column(db.Text)
    instruction = db.Column(db.Text)
    geometry = db.Column(Geometry('GEOMETRY'))
    raw_json = db.Column(db.JSON)
    created_at = db.Column(db.DateTime, default=utc_now)
    updated_at = db.Column(db.DateTime, default=utc_now, onupdate=utc_now)

class AlertIntersection(db.Model):
    __tablename__ = 'alert_intersections'

    id = db.Column(db.Integer, primary_key=True)
    alert_id = db.Column(db.Integer, db.ForeignKey('cap_alerts.id'), nullable=False)
    boundary_id = db.Column(db.Integer, db.ForeignKey('boundaries.id'), nullable=False)
    intersection_area = db.Column(db.Float)
    intersection_percentage = db.Column(db.Float)
    created_at = db.Column(db.DateTime, default=utc_now)

    alert = db.relationship('CAPAlert', backref='intersections')
    boundary = db.relationship('Boundary', backref='alert_intersections')

class SystemLog(db.Model):
    __tablename__ = 'system_logs'

    id = db.Column(db.Integer, primary_key=True)
    timestamp = db.Column(db.DateTime, default=utc_now)
    level = db.Column(db.String(20))
    message = db.Column(db.Text)
    module = db.Column(db.String(50))
    details = db.Column(db.JSON)

class PollHistory(db.Model):
    __tablename__ = 'poll_history'

    id = db.Column(db.Integer, primary_key=True)
    timestamp = db.Column(db.DateTime, default=utc_now)
    alerts_fetched = db.Column(db.Integer, default=0)
    alerts_new = db.Column(db.Integer, default=0)
    alerts_updated = db.Column(db.Integer, default=0)
    execution_time_ms = db.Column(db.Integer)
    status = db.Column(db.String(20))
    error_message = db.Column(db.Text)

class LEDMessage(db.Model):
    __tablename__ = 'led_messages'

    id = db.Column(db.Integer, primary_key=True)
    message_type = db.Column(db.String(50))  # 'alert', 'canned', 'custom', 'emergency'
    content = db.Column(db.Text)
    priority = db.Column(db.Integer)
    color = db.Column(db.String(20))
    font_size = db.Column(db.String(20))
    effect = db.Column(db.String(20))
    speed = db.Column(db.String(20))
    display_time = db.Column(db.Integer)
    scheduled_time = db.Column(db.DateTime)
    expires_at = db.Column(db.DateTime)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=utc_now)
    sent_at = db.Column(db.DateTime)
    alert_id = db.Column(db.Integer, db.ForeignKey('cap_alerts.id'), nullable=True)

    alert = db.relationship('CAPAlert', backref='led_messages')

class LEDSignStatus(db.Model):
    __tablename__ = 'led_sign_status'

    id = db.Column(db.Integer, primary_key=True)
    sign_ip = db.Column(db.String(45))
    is_connected = db.Column(db.Boolean, default=False)
    last_message = db.Column(db.Text)
    last_update = db.Column(db.DateTime)
    error_count = db.Column(db.Integer, default=0)
    last_error = db.Column(db.Text)
    firmware_version = db.Column(db.String(50))
    brightness_level = db.Column(db.Integer, default=10)

# Helper functions
def get_active_alerts_query():
    """Get query for active alerts"""
    return CAPAlert.query.filter(
        or_(
            CAPAlert.expires.is_(None),
            CAPAlert.expires > utc_now()
        )
    )

def get_expired_alerts_query():
    """Get query for expired alerts"""
    return CAPAlert.query.filter(
        and_(
            CAPAlert.expires.isnot(None),
            CAPAlert.expires <= utc_now()
        )
    )

def get_active_alerts():
    """Get currently active alerts"""
    return get_active_alerts_query().order_by(
        CAPAlert.severity.desc(),
        CAPAlert.sent.desc()
    ).all()

def ensure_multipolygon(geometry):
    """Convert Polygon to MultiPolygon if needed"""
    if geometry and geometry.get('type') == 'Polygon':
        return {
            'type': 'MultiPolygon',
            'coordinates': [geometry['coordinates']]
        }
    return geometry

def get_system_health():
    """Get comprehensive system health information"""
    try:
        import platform
        uname = platform.uname()
        boot_time = psutil.boot_time()

        # CPU information
        cpu_info = {
            'percent': psutil.cpu_percent(interval=1),
            'count': psutil.cpu_count(),
            'freq': psutil.cpu_freq()._asdict() if psutil.cpu_freq() else None
        }

        # Memory information
        memory = psutil.virtual_memory()
        memory_info = {
            'total': memory.total,
            'available': memory.available,
            'percent': memory.percent,
            'used': memory.used,
            'free': memory.free
        }

        # Disk information
        disk = psutil.disk_usage('/')
        disk_info = {
            'total': disk.total,
            'used': disk.used,
            'free': disk.free,
            'percent': (disk.used / disk.total) * 100
        }

        # Load averages (Linux only)
        load_averages = None
        try:
            load_averages = os.getloadavg()
        except (OSError, AttributeError):
            pass

        # Database status
        db_status = 'unknown'
        db_info = {}
        try:
            result = db.session.execute(text('SELECT version()'))
            db_status = 'connected'
            db_info = {'version': result.scalar()}
        except Exception as e:
            db_status = f'error: {str(e)}'

        # Process information
        processes = []
        for proc in psutil.process_iter(['pid', 'name', 'cpu_percent', 'memory_percent']):
            try:
                proc_info = proc.info
                if proc_info['cpu_percent'] > 1 or proc_info['memory_percent'] > 1:
                    processes.append(proc_info)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass

        processes.sort(key=lambda x: x['cpu_percent'], reverse=True)
        process_info = processes[:10]  # Top 10 processes

        # Network information
        network_info = {}
        try:
            net_io = psutil.net_io_counters()
            network_info = {
                'bytes_sent': net_io.bytes_sent,
                'bytes_recv': net_io.bytes_recv,
                'packets_sent': net_io.packets_sent,
                'packets_recv': net_io.packets_recv
            }
        except:
            pass

        # Service status
        services_status = {}
        services_to_check = ['postgresql', 'apache2', 'nginx']
        for service in services_to_check:
            try:
                result = subprocess.run(['systemctl', 'is-active', service],
                                     capture_output=True, text=True, timeout=5)
                services_status[service] = result.stdout.strip()
            except:
                services_status[service] = 'unknown'

        # Temperature information (if available)
        temperature_info = {}
        try:
            temps = psutil.sensors_temperatures()
            if temps:
                for name, entries in temps.items():
                    temperature_info[name] = []
                    for entry in entries:
                        temperature_info[name].append({
                            'label': entry.label or 'Unknown',
                            'current': entry.current,
                            'high': entry.high,
                            'critical': entry.critical
                        })
        except:
            pass

        return {
            'timestamp': utc_now().isoformat(),
            'local_timestamp': local_now().isoformat(),
            'system': {
                'hostname': uname.node,
                'system': uname.system,
                'release': uname.release,
                'version': uname.version,
                'machine': uname.machine,
                'processor': uname.processor,
                'boot_time': datetime.fromtimestamp(boot_time, UTC_TZ).isoformat(),
                'uptime_seconds': time.time() - boot_time
            },
            'cpu': cpu_info,
            'memory': memory_info,
            'disk': disk_info,
            'network': network_info,
            'processes': process_info,
            'load_averages': load_averages,
            'database': {
                'status': db_status,
                'info': db_info
            },
            'services': services_status,
            'temperature': temperature_info
        }

    except Exception as e:
        logger.error(f"Error getting system health: {str(e)}")
        return {
            'error': str(e),
            'timestamp': utc_now().isoformat(),
            'local_timestamp': local_now().isoformat()
        }

def format_bytes(bytes_value):
    """Format bytes into human readable format"""
    if bytes_value == 0:
        return "0 B"

    size_names = ["B", "KB", "MB", "GB", "TB", "PB"]
    import math
    i = int(math.floor(math.log(bytes_value, 1024)))
    p = math.pow(1024, i)
    s = round(bytes_value / p, 2)
    return f"{s} {size_names[i]}"

def format_uptime(seconds):
    """Format uptime seconds into human readable format"""
    days = int(seconds // 86400)
    hours = int((seconds % 86400) // 3600)
    minutes = int((seconds % 3600) // 60)

    if days > 0:
        return f"{days}d {hours}h {minutes}m"
    elif hours > 0:
        return f"{hours}h {minutes}m"
    else:
        return f"{minutes}m"

# Initialize LED controller
def init_led_controller():
    """Initialize the LED sign controller"""
    global led_controller
    if not LED_AVAILABLE:
        logger.warning("LED controller not available - skipping initialization")
        return

    try:
        led_controller = LEDSignController(LED_SIGN_IP, LED_SIGN_PORT)
        logger.info(f"LED controller initialized for {LED_SIGN_IP}:{LED_SIGN_PORT}")

        # Update database status
        status = LEDSignStatus.query.filter_by(sign_ip=LED_SIGN_IP).first()
        if not status:
            status = LEDSignStatus(sign_ip=LED_SIGN_IP)
            db.session.add(status)

        status.is_connected = led_controller.connected
        status.last_update = utc_now()
        db.session.commit()

    except Exception as e:
        logger.error(f"Failed to initialize LED controller: {e}")
        led_controller = None

def update_led_display():
    """Update LED display with current alerts"""
    if not led_controller:
        return False

    try:
        active_alerts = get_active_alerts()

        if active_alerts:
            # Create LED message record
            alert = active_alerts[0]  # Show most severe alert
            led_message = LEDMessage(
                message_type='alert',
                content=f"{alert.event}: {alert.headline}",
                priority=0 if alert.severity in ['Extreme', 'Severe'] else 1,
                alert_id=alert.id,
                scheduled_time=utc_now(),
                expires_at=alert.expires
            )
            db.session.add(led_message)
            db.session.commit()

            # Send to LED sign
            result = led_controller.display_alerts(active_alerts)
            if result:
                led_message.sent_at = utc_now()
                db.session.commit()

            return result
        else:
            # Show default message
            led_message = LEDMessage(
                message_type='canned',
                content='no_alerts',
                priority=3,
                scheduled_time=utc_now()
            )
            db.session.add(led_message)
            db.session.commit()

            result = led_controller.display_default_message()
            if result:
                led_message.sent_at = utc_now()
                db.session.commit()

            return result

    except Exception as e:
        logger.error(f"Error updating LED display: {e}")
        return False

# Template filters
@app.template_filter('nl2br')
def nl2br_filter(text):
    """Convert newlines to HTML br tags"""
    if not text:
        return ""
    return text.replace('\n', '<br>\n')

@app.template_filter('format_local_datetime')
def format_local_datetime_filter(dt, include_utc=True):
    return format_local_datetime(dt, include_utc)

@app.template_filter('format_local_date')
def format_local_date_filter(dt):
    return format_local_date(dt)

@app.template_filter('format_local_time')
def format_local_time_filter(dt):
    return format_local_time(dt)

@app.template_filter('is_expired')
def is_expired_filter(expires_date):
    return is_alert_expired(expires_date)

@app.template_global()
def current_time():
    """Provide current datetime to templates"""
    return utc_now()

@app.template_global()
def local_current_time():
    """Provide current local datetime to templates"""
    return local_now()

# Routes
@app.route('/')
def index():
    """Main dashboard with map"""
    try:
        return render_template('index.html')
    except Exception as e:
        logger.error(f"Error rendering index: {e}")
        return f"<h1>NOAA CAP Alerts System</h1><p>Map interface loading...</p><p><a href='/stats'>📊 Statistics</a> | <a href='/alerts'>📝 Alerts History</a> | <a href='/admin'>⚙️ Admin</a></p>"

@app.route('/admin')
def admin():
    """Enhanced admin interface"""
    try:
        # Get system stats
        total_boundaries = Boundary.query.count()
        total_alerts = CAPAlert.query.count()
        active_alerts = get_active_alerts_query().count()
        expired_alerts = get_expired_alerts_query().count()

        # Get boundary counts by type
        boundary_stats = db.session.query(
            Boundary.type, func.count(Boundary.id).label('count')
        ).group_by(Boundary.type).all()

        # Get LED status
        led_status = None
        if led_controller:
            led_status = led_controller.get_status()

        # Get recent LED messages
        recent_led_messages = LEDMessage.query.order_by(
            LEDMessage.created_at.desc()
        ).limit(10).all()

        return render_template('admin.html',
                             total_boundaries=total_boundaries,
                             total_alerts=total_alerts,
                             active_alerts=active_alerts,
                             expired_alerts=expired_alerts,
                             boundary_stats=boundary_stats,
                             led_status=led_status,
                             recent_led_messages=recent_led_messages)
    except Exception as e:
        logger.error(f"Error loading admin: {e}")
        return f"<h1>Admin Error</h1><p>{e}</p><p><a href='/'>← Back to Main</a></p>"

@app.route('/stats')
def stats():
    """Comprehensive statistics page"""
    try:
        stats_data = {}

        # Basic alert statistics
        total_alerts = CAPAlert.query.count()
        active_alerts = get_active_alerts_query().count()
        expired_alerts = get_expired_alerts_query().count()

        stats_data.update({
            'total_alerts': total_alerts,
            'active_alerts': active_alerts,
            'expired_alerts': expired_alerts
        })

        # Alert statistics by severity
        severity_stats = db.session.query(
            CAPAlert.severity, func.count(CAPAlert.id).label('count')
        ).group_by(CAPAlert.severity).all()

        stats_data['severity_breakdown'] = {
            severity: count for severity, count in severity_stats
        }

        # Alert statistics by event type
        event_stats = db.session.query(
            CAPAlert.event, func.count(CAPAlert.id).label('count')
        ).group_by(CAPAlert.event).order_by(func.count(CAPAlert.id).desc()).limit(10).all()

        stats_data['top_events'] = event_stats

        # Polling statistics
        try:
            total_polls = PollHistory.query.count()
            if total_polls > 0:
                poll_stats = db.session.query(
                    func.avg(PollHistory.alerts_fetched).label('avg_fetched'),
                    func.max(PollHistory.alerts_fetched).label('max_fetched'),
                    func.avg(PollHistory.execution_time_ms).label('avg_time_ms')
                ).first()

                successful_polls = PollHistory.query.filter_by(status='SUCCESS').count()
                failed_polls = PollHistory.query.filter(PollHistory.status != 'SUCCESS').count()

                stats_data['polling'] = {
                    'total_polls': total_polls,
                    'avg_fetched': round(poll_stats.avg_fetched or 0, 1),
                    'max_fetched': poll_stats.max_fetched or 0,
                    'avg_time_ms': round(poll_stats.avg_time_ms or 0, 1),
                    'successful_polls': successful_polls,
                    'failed_polls': failed_polls,
                    'success_rate': round((successful_polls / total_polls * 100), 1) if total_polls > 0 else 0,
                    'data_source': 'poll_history'
                }
            else:
                stats_data['polling'] = {
                    'total_polls': 0, 'avg_fetched': 0, 'max_fetched': 0,
                    'avg_time_ms': 0, 'successful_polls': 0, 'failed_polls': 0,
                    'success_rate': 0, 'data_source': 'no_data'
                }
        except Exception as e:
            logger.error(f"Error getting polling stats: {str(e)}")
            stats_data['polling'] = {
                'total_polls': 0, 'avg_fetched': 0, 'max_fetched': 0,
                'avg_time_ms': 0, 'successful_polls': 0, 'failed_polls': 0,
                'success_rate': 0, 'data_source': 'error'
            }

        # LED statistics
        try:
            led_messages_total = LEDMessage.query.count()
            led_messages_sent = LEDMessage.query.filter(LEDMessage.sent_at.isnot(None)).count()
            led_last_message = LEDMessage.query.order_by(LEDMessage.created_at.desc()).first()

            stats_data['led_stats'] = {
                'total_messages': led_messages_total,
                'sent_messages': led_messages_sent,
                'success_rate': round((led_messages_sent / led_messages_total * 100), 1) if led_messages_total > 0 else 0,
                'last_message_time': led_last_message.created_at.isoformat() if led_last_message else None,
                'controller_available': led_controller is not None,
                'sign_connected': led_controller.connected if led_controller else False
            }
        except Exception as e:
            logger.error(f"Error getting LED stats: {str(e)}")
            stats_data['led_stats'] = {
                'total_messages': 0, 'sent_messages': 0, 'success_rate': 0,
                'last_message_time': None, 'controller_available': False, 'sign_connected': False
            }

        # Fun statistics
        try:
            longest_headline = db.session.query(
                func.max(func.length(CAPAlert.headline)).label('max_length')
            ).scalar() or 0

            most_common_word = db.session.query(
                CAPAlert.event
            ).group_by(CAPAlert.event).order_by(func.count(CAPAlert.event).desc()).first()

            stats_data['fun_stats'] = {
                'longest_headline': longest_headline,
                'most_common_event': most_common_word[0] if most_common_word else 'None'
            }
        except Exception as e:
            logger.error(f"Error getting fun stats: {str(e)}")
            stats_data['fun_stats'] = {'longest_headline': 0, 'most_common_event': 'None'}

        # Add utility functions to template context
        stats_data['format_bytes'] = format_bytes
        stats_data['format_uptime'] = format_uptime

        return render_template('stats.html', **stats_data)

    except Exception as e:
        logger.error(f"Error loading statistics: {str(e)}")
        return f"<h1>Error loading statistics</h1><p>{str(e)}</p><p><a href='/'>← Back to Main</a></p>"

@app.route('/alerts')
def alerts():
    """Alerts history page with enhanced filtering"""
    try:
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 50, type=int)

        status_filter = request.args.get('status', '')
        severity_filter = request.args.get('severity', '')
        event_filter = request.args.get('event', '')
        search_query = request.args.get('search', '')
        show_expired = request.args.get('show_expired', 'false').lower() == 'true'

        query = CAPAlert.query

        if status_filter:
            query = query.filter(CAPAlert.status == status_filter)

        if severity_filter:
            query = query.filter(CAPAlert.severity == severity_filter)

        if event_filter:
            query = query.filter(CAPAlert.event.ilike(f'%{event_filter}%'))

        if search_query:
            search_term = f'%{search_query}%'
            query = query.filter(
                or_(
                    CAPAlert.headline.ilike(search_term),
                    CAPAlert.description.ilike(search_term),
                    CAPAlert.area_desc.ilike(search_term),
                    CAPAlert.event.ilike(search_term)
                )
            )

        if not show_expired:
            # Use our helper function for consistent active alerts logic
            now = utc_now()
            query = query.filter(
                or_(
                    CAPAlert.expires.is_(None),
                    CAPAlert.expires > now
                )
            )

        # Order by sent date descending
        query = query.order_by(CAPAlert.sent.desc())

        # Paginate results
        alerts_paginated = query.paginate(page=page, per_page=per_page, error_out=False)

        # Get filter options for dropdowns
        available_severities = db.session.query(CAPAlert.severity).distinct().all()
        available_events = db.session.query(CAPAlert.event).distinct().order_by(CAPAlert.event).all()
        available_statuses = db.session.query(CAPAlert.status).distinct().all()

        return render_template('alerts.html',
                             alerts=alerts_paginated,
                             current_filters={
                                 'status': status_filter,
                                 'severity': severity_filter,
                                 'event': event_filter,
                                 'search': search_query,
                                 'show_expired': show_expired
                             },
                             available_severities=[s[0] for s in available_severities if s[0]],
                             available_events=[e[0] for e in available_events if e[0]],
                             available_statuses=[s[0] for s in available_statuses if s[0]])

    except Exception as e:
        logger.error(f"Error loading alerts: {str(e)}")
        return f"<h1>Error loading alerts</h1><p>{str(e)}</p><p><a href='/'>← Back to Main</a></p>"

@app.route('/system_health')
def system_health():
    """System health monitoring page"""
    try:
        health_data = get_system_health()
        return render_template('system_health.html', health=health_data)
    except Exception as e:
        logger.error(f"Error loading system health: {str(e)}")
        return f"<h1>System Health Error</h1><p>{str(e)}</p><p><a href='/'>← Back to Main</a></p>"

# API Routes
@app.route('/api/system_status')
def api_system_status():
    """Get comprehensive system status including LED"""
    try:
        # Get basic stats
        total_alerts = CAPAlert.query.count()
        active_alerts_count = len(get_active_alerts())

        # Get LED status
        led_status = 'disconnected'
        if led_controller and led_controller.connected:
            led_status = 'connected'
        elif led_controller:
            led_status = 'error'

        # Get recent system activity
        recent_logs = SystemLog.query.order_by(
            SystemLog.timestamp.desc()
        ).limit(5).all()

        return jsonify({
            'timestamp': utc_now().isoformat(),
            'local_timestamp': local_now().isoformat(),
            'total_alerts': total_alerts,
            'active_alerts_count': active_alerts_count,
            'led_sign_status': led_status,
            'led_sign_ip': LED_SIGN_IP,
            'database_status': 'connected',
            'recent_activity': [
                {
                    'timestamp': log.timestamp.isoformat(),
                    'level': log.level,
                    'message': log.message,
                    'module': log.module
                }
                for log in recent_logs
            ]
        })

    except Exception as e:
        logger.error(f"Error getting system status: {e}")
        return jsonify({'error': str(e)})

@app.route('/api/alerts')
def api_alerts():
    """Get alerts data for AJAX requests"""
    try:
        active_only = request.args.get('active_only', 'false').lower() == 'true'
        limit = request.args.get('limit', 50, type=int)

        if active_only:
            alerts = get_active_alerts()[:limit]
        else:
            alerts = CAPAlert.query.order_by(CAPAlert.sent.desc()).limit(limit).all()

        return jsonify({
            'alerts': [
                {
                    'id': alert.id,
                    'identifier': alert.identifier,
                    'event': alert.event,
                    'severity': alert.severity,
                    'urgency': alert.urgency,
                    'headline': alert.headline,
                    'description': alert.description,
                    'area_desc': alert.area_desc,
                    'sent': alert.sent.isoformat() if alert.sent else None,
                    'expires': alert.expires.isoformat() if alert.expires else None,
                    'is_expired': is_alert_expired(alert.expires),
                    'created_at': alert.created_at.isoformat(),
                    'geometry': alert.geometry
                }
                for alert in alerts
            ],
            'total_count': len(alerts),
            'timestamp': utc_now().isoformat()
        })

    except Exception as e:
        logger.error(f"Error getting alerts API: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/boundaries')
def api_boundaries():
    """Get boundaries data for map display"""
    try:
        boundary_type = request.args.get('type')

        query = Boundary.query
        if boundary_type:
            query = query.filter(Boundary.type == boundary_type)

        boundaries = query.all()

        return jsonify({
            'boundaries': [
                {
                    'id': boundary.id,
                    'name': boundary.name,
                    'type': boundary.type,
                    'description': boundary.description,
                    'geometry': boundary.geometry
                }
                for boundary in boundaries
            ],
            'total_count': len(boundaries),
            'timestamp': utc_now().isoformat()
        })

    except Exception as e:
        logger.error(f"Error getting boundaries API: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/trigger_poll', methods=['POST'])
def api_trigger_poll():
    """Manually trigger CAP polling and LED update"""
    try:
        # Run the CAP poller script
        poller_script = '/home/pi/noaa_alerts_system/poller/cap_poller.py'
        if os.path.exists(poller_script):
            try:
                result = subprocess.run(
                    ['python3', poller_script, '--log-level', 'INFO'],
                    cwd='/home/pi/noaa_alerts_system',
                    capture_output=True,
                    text=True,
                    timeout=120
                )

                if result.returncode == 0:
                    poll_success = True
                    poll_message = "CAP polling completed successfully"
                else:
                    poll_success = False
                    poll_message = f"CAP polling failed: {result.stderr}"
            except subprocess.TimeoutExpired:
                poll_success = False
                poll_message = "CAP polling timed out"
            except Exception as e:
                poll_success = False
                poll_message = f"CAP polling error: {str(e)}"
        else:
            poll_success = False
            poll_message = "CAP poller script not found"

        # Update LED display with current alerts
        led_updated = update_led_display()

        # Log the manual trigger
        log_entry = SystemLog(
            level='INFO',
            message='Manual CAP poll and LED update triggered',
            module='admin',
            details={
                'triggered_by': 'web_interface',
                'poll_success': poll_success,
                'poll_message': poll_message,
                'led_updated': led_updated,
                'timestamp': utc_now().isoformat()
            }
        )
        db.session.add(log_entry)
        db.session.commit()

        return jsonify({
            'success': poll_success,
            'poll_message': poll_message,
            'led_updated': led_updated,
            'timestamp': utc_now().isoformat()
        })

    except Exception as e:
        logger.error(f"Error triggering poll: {e}")
        return jsonify({'success': False, 'error': str(e)})

# LED Sign API Routes
@app.route('/api/led/send_message', methods=['POST'])
def api_led_send_message():
    """Send custom message to LED sign"""
    try:
        data = request.get_json()

        if not led_controller:
            return jsonify({'success': False, 'error': 'LED controller not available'})

        # Extract parameters with defaults
        text = data.get('text', '')
        if not text:
            return jsonify({'success': False, 'error': 'Message text is required'})

        color_name = data.get('color', 'GREEN')
        font_name = data.get('font', 'MEDIUM')
        effect_name = data.get('effect', 'IMMEDIATE')
        speed_name = data.get('speed', 'MEDIUM')
        hold_time = int(data.get('hold_time', 5))
        priority_value = int(data.get('priority', MessagePriority.NORMAL.value))

        try:
            color = Color[color_name.upper()]
            font = FontSize[font_name.upper()]
            effect = Effect[effect_name.upper()]
            speed = Speed[speed_name.upper()]
            priority = MessagePriority(priority_value)
        except (KeyError, ValueError) as e:
            return jsonify({'success': False, 'error': f'Invalid parameter: {str(e)}'})

        # Create database record
        led_message = LEDMessage(
            message_type='custom',
            content=text,
            priority=priority.value,
            color=color.name,
            font_size=font.name,
            effect=effect.name,
            speed=speed.name,
            display_time=hold_time,
            scheduled_time=utc_now()
        )
        db.session.add(led_message)
        db.session.commit()

        # Send to LED sign
        result = led_controller.send_message(
            text=text,
            color=color,
            font=font,
            effect=effect,
            speed=speed,
            hold_time=hold_time,
            priority=priority
        )

        if result:
            led_message.sent_at = utc_now()
            db.session.commit()

        return jsonify({
            'success': result,
            'message_id': led_message.id,
            'timestamp': utc_now().isoformat()
        })

    except Exception as e:
        logger.error(f"Error sending LED message: {e}")
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/led/send_canned', methods=['POST'])
def api_led_send_canned():
    """Send canned message to LED sign"""
    try:
        data = request.get_json()
        message_name = data.get('message_name')
        parameters = data.get('parameters', {})

        if not message_name:
            return jsonify({'success': False, 'error': 'Message name is required'})

        if not led_controller:
            return jsonify({'success': False, 'error': 'LED controller not available'})

        # Create database record
        led_message = LEDMessage(
            message_type='canned',
            content=message_name,
            priority=2,  # Normal priority for canned messages
            scheduled_time=utc_now()
        )
        db.session.add(led_message)
        db.session.commit()

        # Send to LED sign
        result = led_controller.send_canned_message(message_name, **parameters)

        if result:
            led_message.sent_at = utc_now()
            db.session.commit()

        return jsonify({
            'success': result,
            'message_id': led_message.id,
            'timestamp': utc_now().isoformat()
        })

    except Exception as e:
        logger.error(f"Error sending canned message: {e}")
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/led/clear', methods=['POST'])
def api_led_clear():
    """Clear LED display"""
    try:
        if not led_controller:
            return jsonify({'success': False, 'error': 'LED controller not available'})

        result = led_controller.clear_display()

        if result:
            # Log the clear action
            led_message = LEDMessage(
                message_type='system',
                content='DISPLAY_CLEARED',
                priority=1,
                scheduled_time=utc_now(),
                sent_at=utc_now()
            )
            db.session.add(led_message)
            db.session.commit()

        return jsonify({'success': result, 'timestamp': utc_now().isoformat()})

    except Exception as e:
        logger.error(f"Error clearing LED display: {e}")
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/led/brightness', methods=['POST'])
def api_led_brightness():
    """Set LED display brightness"""
    try:
        data = request.get_json()
        brightness = int(data.get('brightness', 10))

        if not 1 <= brightness <= 16:
            return jsonify({'success': False, 'error': 'Brightness must be between 1 and 16'})

        if not led_controller:
            return jsonify({'success': False, 'error': 'LED controller not available'})

        result = led_controller.set_brightness(brightness)

        if result:
            # Update database status
            status = LEDSignStatus.query.filter_by(sign_ip=LED_SIGN_IP).first()
            if status:
                status.brightness_level = brightness
                status.last_update = utc_now()
                db.session.commit()

        return jsonify({'success': result, 'brightness': brightness})

    except Exception as e:
        logger.error(f"Error setting LED brightness: {e}")
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/led/test', methods=['POST'])
def api_led_test():
    """Run LED sign feature test"""
    try:
        if not led_controller:
            return jsonify({'success': False, 'error': 'LED controller not available'})

        result = led_controller.test_all_features()

        # Log the test
        led_message = LEDMessage(
            message_type='system',
            content='FEATURE_TEST',
            priority=1,
            scheduled_time=utc_now(),
            sent_at=utc_now() if result else None
        )
        db.session.add(led_message)
        db.session.commit()

        return jsonify({'success': result, 'message': 'Test sequence started'})

    except Exception as e:
        logger.error(f"Error running LED test: {e}")
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/led/emergency', methods=['POST'])
def api_led_emergency():
    """Send emergency override message"""
    try:
        data = request.get_json()
        message = data.get('message', 'EMERGENCY ALERT')
        duration = int(data.get('duration', 30))

        if not led_controller:
            return jsonify({'success': False, 'error': 'LED controller not available'})

        # Create database record
        led_message = LEDMessage(
            message_type='emergency',
            content=message,
            priority=0,  # Highest priority
            display_time=duration,
            scheduled_time=utc_now()
        )
        db.session.add(led_message)
        db.session.commit()

        result = led_controller.emergency_override(message, duration)

        if result:
            led_message.sent_at = utc_now()
            db.session.commit()

        return jsonify({
            'success': result,
            'message_id': led_message.id,
            'duration': duration
        })

    except Exception as e:
        logger.error(f"Error sending emergency message: {e}")
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/led/status')
def api_led_status():
    """Get LED sign status"""
    try:
        status = {
            'controller_available': led_controller is not None,
            'sign_ip': LED_SIGN_IP,
            'sign_port': LED_SIGN_PORT,
            'led_library_available': LED_AVAILABLE
        }

        if led_controller:
            status.update(led_controller.get_status())

        # Get database status
        db_status = LEDSignStatus.query.filter_by(sign_ip=LED_SIGN_IP).first()
        if db_status:
            status.update({
                'brightness_level': db_status.brightness_level,
                'error_count': db_status.error_count,
                'last_error': db_status.last_error,
                'last_database_update': db_status.last_update.isoformat() if db_status.last_update else None
            })

        return jsonify(status)

    except Exception as e:
        logger.error(f"Error getting LED status: {e}")
        return jsonify({'error': str(e)})

@app.route('/api/led/messages')
def api_led_messages():
    """Get LED message history"""
    try:
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 20, type=int)

        messages = LEDMessage.query.order_by(
            LEDMessage.created_at.desc()
        ).paginate(page=page, per_page=per_page, error_out=False)

        return jsonify({
            'messages': [
                {
                    'id': msg.id,
                    'type': msg.message_type,
                    'content': msg.content,
                    'priority': msg.priority,
                    'color': msg.color,
                    'font_size': msg.font_size,
                    'effect': msg.effect,
                    'speed': msg.speed,
                    'display_time': msg.display_time,
                    'created_at': msg.created_at.isoformat(),
                    'sent_at': msg.sent_at.isoformat() if msg.sent_at else None,
                    'is_active': msg.is_active,
                    'alert_id': msg.alert_id
                }
                for msg in messages.items
            ],
            'total': messages.total,
            'pages': messages.pages,
            'current_page': page
        })

    except Exception as e:
        logger.error(f"Error getting LED messages: {e}")
        return jsonify({'error': str(e)})

@app.route('/api/led/canned_messages')
def api_led_canned_messages():
    """Get available canned messages"""
    try:
        if not led_controller:
            return jsonify({'canned_messages': []})

        canned_messages = []
        for name, config in led_controller.canned_messages.items():
            canned_messages.append({
                'name': name,
                'text': config['text'],
                'color': config['color'].name,
                'font': config['font'].name,
                'effect': config['effect'].name,
                'priority': config['priority'].name
            })

        return jsonify({'canned_messages': canned_messages})

    except Exception as e:
        logger.error(f"Error getting canned messages: {e}")
        return jsonify({'error': str(e)})

# Background maintenance task
def led_maintenance_task():
    """Background task for LED maintenance"""
    while True:
        try:
            if led_controller:
                # Check connection status
                if not led_controller.connected:
                    logger.warning("LED controller disconnected, attempting reconnect")
                    led_controller.connect()

                # Update display with current alerts every 5 minutes
                update_led_display()

                # Update database status
                status = LEDSignStatus.query.filter_by(sign_ip=LED_SIGN_IP).first()
                if status:
                    status.is_connected = led_controller.connected
                    status.last_update = utc_now()
                    if led_controller.last_message:
                        status.last_message = led_controller.last_message
                    db.session.commit()

            time.sleep(300)  # 5 minutes

        except Exception as e:
            logger.error(f"Error in LED maintenance task: {e}")
            time.sleep(60)  # Wait 1 minute before retry

# Error handlers
@app.errorhandler(404)
def not_found(error):
    return render_template('error.html',
                         error_code=404,
                         error_message="Page not found"), 404

@app.errorhandler(500)
def internal_error(error):
    return render_template('error.html',
                         error_code=500,
                         error_message="Internal server error"), 500

# Initialize the application
def create_app():
    """Application factory"""
    with app.app_context():
        try:
            # Create tables
            db.create_all()
            logger.info("Database tables created/verified")

            # Initialize LED controller
            if LED_AVAILABLE:
                init_led_controller()
            else:
                logger.warning("LED functionality disabled - controller not available")

            # Start background maintenance task
            if led_controller:
                maintenance_thread = threading.Thread(target=led_maintenance_task, daemon=True)
                maintenance_thread.start()
                logger.info("LED maintenance task started")

            logger.info("Application initialized successfully")

        except Exception as e:
            logger.error(f"Error initializing application: {e}")

    return app

if __name__ == '__main__':
    # Create and run app
    app = create_app()
    app.run(debug=False, host='0.0.0.0', port=5000)