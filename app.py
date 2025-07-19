#!/usr/bin/env python3
"""
NOAA CAP Alerts and GIS Boundary Mapping System
Flask Web Application with Enhanced Boundary Management and Alerts History
WITH ALERT PRESERVATION AND CONFIRMATION SYSTEMS
NOW WITH PROPER TIMEZONE HANDLING FOR PUTNAM COUNTY, OHIO
"""

import os
import json
import psutil
import platform
import socket
import subprocess
import shutil
import time
import pytz
from datetime import datetime, timedelta
from collections import defaultdict
from flask import Flask, request, jsonify, render_template, flash, redirect, url_for
from flask_sqlalchemy import SQLAlchemy
from geoalchemy2 import Geometry
from geoalchemy2.functions import ST_GeomFromGeoJSON, ST_Intersects, ST_AsGeoJSON
from sqlalchemy import text, func, or_, desc
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'dev-key-change-in-production')

# Database configuration
DATABASE_URL = os.getenv('DATABASE_URL', 'postgresql://noaa_user:rkhkeq@localhost:5432/noaa_alerts')
app.config['SQLALCHEMY_DATABASE_URI'] = DATABASE_URL
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

# Timezone configuration for Putnam County, Ohio (Eastern Time)
PUTNAM_COUNTY_TZ = pytz.timezone('America/New_York')
UTC_TZ = pytz.UTC

logger.info("NOAA Alerts System startup")


def utc_now():
    """Get current UTC time with timezone awareness"""
    return datetime.now(UTC_TZ)


def local_now():
    """Get current Putnam County local time"""
    return utc_now().astimezone(PUTNAM_COUNTY_TZ)


def parse_nws_datetime(dt_string):
    """Parse NWS datetime strings which can be in various formats"""
    if not dt_string:
        return None

    # Remove timezone abbreviations and normalize
    dt_string = str(dt_string).strip()

    # Handle common NWS formats
    if dt_string.endswith('Z'):
        # UTC/Zulu time
        try:
            dt = datetime.fromisoformat(dt_string.replace('Z', '+00:00'))
            return dt.astimezone(UTC_TZ)
        except ValueError:
            pass

    # Try parsing as ISO format with timezone
    try:
        dt = datetime.fromisoformat(dt_string)
        if dt.tzinfo is None:
            # Assume UTC if no timezone info
            dt = dt.replace(tzinfo=UTC_TZ)
        return dt.astimezone(UTC_TZ)
    except ValueError:
        pass

    # Handle EDT/EST format (approximate - NWS sometimes uses these)
    if 'EDT' in dt_string:
        try:
            dt_clean = dt_string.replace(' EDT', '').replace('EDT', '')
            dt = datetime.fromisoformat(dt_clean)
            # EDT is UTC-4
            edt_tz = pytz.timezone('US/Eastern')
            dt = edt_tz.localize(dt)
            return dt.astimezone(UTC_TZ)
        except ValueError:
            pass

    if 'EST' in dt_string:
        try:
            dt_clean = dt_string.replace(' EST', '').replace('EST', '')
            dt = datetime.fromisoformat(dt_clean)
            # EST is UTC-5
            est_tz = pytz.timezone('US/Eastern')
            dt = est_tz.localize(dt)
            return dt.astimezone(UTC_TZ)
        except ValueError:
            pass

    logger.warning(f"Could not parse datetime: {dt_string}")
    return None


def format_local_datetime(dt, include_utc=True):
    """Format datetime in Putnam County local time with optional UTC"""
    if not dt:
        return "Unknown"

    # Ensure datetime is timezone-aware
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC_TZ)

    # Convert to local time
    local_dt = dt.astimezone(PUTNAM_COUNTY_TZ)

    # Format local time
    local_str = local_dt.strftime('%B %d, %Y at %I:%M %p %Z')

    if include_utc:
        utc_str = dt.astimezone(UTC_TZ).strftime('%H:%M UTC')
        return f"{local_str} ({utc_str})"
    else:
        return local_str


def format_local_date(dt):
    """Format date in Putnam County local time"""
    if not dt:
        return "Unknown"

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC_TZ)

    local_dt = dt.astimezone(PUTNAM_COUNTY_TZ)
    return local_dt.strftime('%B %d, %Y')


def format_local_time(dt):
    """Format time only in Putnam County local time with UTC"""
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
    """Check if alert is expired using current time"""
    if not expires_dt:
        return False

    if expires_dt.tzinfo is None:
        expires_dt = expires_dt.replace(tzinfo=UTC_TZ)

    return expires_dt < utc_now()


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
    status = db.Column(db.String(50), nullable=False)
    message_type = db.Column(db.String(50), nullable=False)
    scope = db.Column(db.String(50), nullable=False)
    category = db.Column(db.String(50))
    event = db.Column(db.String(255), nullable=False)
    urgency = db.Column(db.String(50))
    severity = db.Column(db.String(50))
    certainty = db.Column(db.String(50))
    area_desc = db.Column(db.Text)
    headline = db.Column(db.Text)
    description = db.Column(db.Text)
    instruction = db.Column(db.Text)
    raw_json = db.Column(db.JSON)
    geom = db.Column(Geometry('POLYGON', srid=4326))
    created_at = db.Column(db.DateTime, default=utc_now)
    updated_at = db.Column(db.DateTime, default=utc_now, onupdate=utc_now)


class SystemLog(db.Model):
    __tablename__ = 'system_log'

    id = db.Column(db.Integer, primary_key=True)
    timestamp = db.Column(db.DateTime, default=utc_now)
    level = db.Column(db.String(20), nullable=False)
    message = db.Column(db.Text, nullable=False)
    module = db.Column(db.String(100))
    details = db.Column(db.JSON)


class Intersection(db.Model):
    __tablename__ = 'intersections'

    id = db.Column(db.Integer, primary_key=True)
    cap_alert_id = db.Column(db.Integer, db.ForeignKey('cap_alerts.id', ondelete='CASCADE'))
    boundary_id = db.Column(db.Integer, db.ForeignKey('boundaries.id', ondelete='CASCADE'))
    intersection_area = db.Column(db.Float)
    created_at = db.Column(db.DateTime, default=utc_now)


class PollHistory(db.Model):
    __tablename__ = 'poll_history'

    id = db.Column(db.Integer, primary_key=True)
    timestamp = db.Column(db.DateTime, default=utc_now)
    status = db.Column(db.String(20), nullable=False)
    alerts_fetched = db.Column(db.Integer, default=0)
    alerts_new = db.Column(db.Integer, default=0)
    alerts_updated = db.Column(db.Integer, default=0)
    execution_time_ms = db.Column(db.Integer)
    error_message = db.Column(db.Text)


# Helper Functions for Active Alerts
def get_active_alerts_query():
    """Get query for active (non-expired) alerts - preserves all data"""
    now = utc_now()
    return CAPAlert.query.filter(
        or_(
            CAPAlert.expires.is_(None),  # No expiration date
            CAPAlert.expires > now  # Future expiration
        )
    ).filter(
        CAPAlert.status != 'Expired'  # Exclude explicitly expired
    )


def get_expired_alerts_query():
    """Get query for expired alerts"""
    now = utc_now()
    return CAPAlert.query.filter(
        CAPAlert.expires < now
    )


# Enhanced Field Detection Functions
def get_field_mappings():
    """Define field mappings for different boundary types"""
    return {
        'electric': {
            'name_fields': ['COMPNAME', 'Company', 'Provider', 'Utility'],
            'description_fields': ['COMPCODE', 'COMPTYPE', 'Shape_Leng', 'SHAPE_STAr']
        },
        'villages': {
            'name_fields': ['CORPORATIO', 'VILLAGE', 'NAME', 'Municipality'],
            'description_fields': ['POP_2020', 'POP_2010', 'POP_2000', 'SQMI']
        },
        'school': {
            'name_fields': ['District', 'DISTRICT', 'SCHOOL_DIS', 'NAME'],
            'description_fields': ['STUDENTS', 'Shape_Area', 'ENROLLMENT']
        },
        'fire': {
            'name_fields': ['DEPT', 'DEPARTMENT', 'STATION', 'FIRE_DEPT'],
            'description_fields': ['STATION_NUM', 'TYPE', 'SERVICE_AREA']
        },
        'ems': {
            'name_fields': ['DEPT', 'DEPARTMENT', 'SERVICE', 'PROVIDER'],
            'description_fields': ['STATION', 'Area', 'Shape_Area', 'SERVICE_TYPE']
        },
        'township': {
            'name_fields': ['TOWNSHIP_N', 'TOWNSHIP', 'TWP_NAME', 'NAME'],
            'description_fields': ['POPULATION', 'AREA_SQMI', 'POP_2010', 'COUNTY_COD']
        },
        'telephone': {
            'name_fields': ['TELNAME', 'PROVIDER', 'COMPANY', 'TELECOM', 'CARRIER'],
            'description_fields': ['TELCO', 'NAME', 'LATA', 'SERVICE_TYPE']
        },
        'county': {
            'name_fields': ['COUNTY', 'COUNTY_NAME', 'NAME'],
            'description_fields': ['FIPS_CODE', 'POPULATION', 'AREA_SQMI']
        }
    }


def extract_name_and_description(properties, boundary_type):
    """Extract name and description from feature properties"""
    mappings = get_field_mappings()
    type_mapping = mappings.get(boundary_type, {})

    # Extract name
    name = None
    for field in type_mapping.get('name_fields', []):
        if field in properties and properties[field]:
            name = str(properties[field]).strip()
            break

    # Fallback name extraction
    if not name:
        for field in ['name', 'NAME', 'Name', 'OBJECTID', 'ID', 'FID']:
            if field in properties and properties[field]:
                name = str(properties[field]).strip()
                break

    if not name:
        name = "Unknown"

    # Extract description
    description_parts = []
    for field in type_mapping.get('description_fields', []):
        if field in properties and properties[field] is not None:
            value = properties[field]
            if isinstance(value, (int, float)):
                if field.upper().startswith('POP'):
                    description_parts.append(f"Population {field[-4:]}: {value:,}")
                elif field == 'AREA_SQMI':
                    description_parts.append(f"Area: {value:.2f} sq mi")
                elif field == 'SQMI':
                    description_parts.append(f"Area: {value:.2f} sq mi")
                elif field == 'Area':
                    description_parts.append(f"Area: {value:.2f} sq mi")
                elif field in ['Shape_Area', 'SHAPE_STAr', 'ShapeSTArea']:
                    if 'Area' in properties and properties['Area']:
                        continue
                    sq_miles = value / 2589988.11
                    if sq_miles > 500:
                        sq_feet_to_sq_miles = value / 27878400
                        if sq_feet_to_sq_miles <= 500:
                            description_parts.append(f"Area: {sq_feet_to_sq_miles:.2f} sq mi")
                        else:
                            continue
                    else:
                        description_parts.append(f"Area: {sq_miles:.2f} sq mi")
                elif field == 'STATION' and boundary_type == 'ems':
                    description_parts.append(f"Station: {value}")
                elif field.upper() in ['SHAPE_LENG', 'PERIMETER', 'Shape_Length', 'ShapeSTLength']:
                    miles = value * 0.000621371
                    description_parts.append(f"Perimeter: {miles:.2f} miles")
                else:
                    description_parts.append(f"{field}: {value}")
            else:
                description_parts.append(f"{field}: {value}")

    # Add common geographic info
    for field in ['county_nam', 'COUNTY', 'County', 'COUNTY_COD']:
        if field in properties and properties[field]:
            description_parts.append(f"County: {properties[field]}")
            break

    description = "; ".join(description_parts) if description_parts else ""

    return name, description


def get_system_health():
    """Get comprehensive system health information"""
    try:
        uname = platform.uname()
        boot_time = psutil.boot_time()

        cpu_info = {
            'physical_cores': psutil.cpu_count(logical=False),
            'total_cores': psutil.cpu_count(logical=True),
            'max_frequency': psutil.cpu_freq().max if psutil.cpu_freq() else 0,
            'current_frequency': psutil.cpu_freq().current if psutil.cpu_freq() else 0,
            'cpu_usage_percent': psutil.cpu_percent(interval=1),
            'cpu_usage_per_core': psutil.cpu_percent(interval=1, percpu=True)
        }

        memory = psutil.virtual_memory()
        swap = psutil.swap_memory()
        memory_info = {
            'total': memory.total,
            'available': memory.available,
            'used': memory.used,
            'free': memory.free,
            'percentage': memory.percent,
            'swap_total': swap.total,
            'swap_used': swap.used,
            'swap_free': swap.free,
            'swap_percentage': swap.percent
        }

        disk_info = []
        try:
            partitions = psutil.disk_partitions()
            for partition in partitions:
                try:
                    partition_usage = psutil.disk_usage(partition.mountpoint)
                    disk_info.append({
                        'device': partition.device,
                        'mountpoint': partition.mountpoint,
                        'fstype': partition.fstype,
                        'total': partition_usage.total,
                        'used': partition_usage.used,
                        'free': partition_usage.free,
                        'percentage': (partition_usage.used / partition_usage.total) * 100
                    })
                except PermissionError:
                    continue
        except:
            disk_usage = psutil.disk_usage('/')
            disk_info.append({
                'device': '/',
                'mountpoint': '/',
                'fstype': 'unknown',
                'total': disk_usage.total,
                'used': disk_usage.used,
                'free': disk_usage.free,
                'percentage': (disk_usage.used / disk_usage.total) * 100
            })

        network_info = {
            'hostname': socket.gethostname(),
            'interfaces': []
        }

        try:
            net_if_addrs = psutil.net_if_addrs()
            net_if_stats = psutil.net_if_stats()

            for interface_name, interface_addresses in net_if_addrs.items():
                interface_info = {
                    'name': interface_name,
                    'addresses': [],
                    'is_up': net_if_stats[interface_name].isup if interface_name in net_if_stats else False
                }

                for address in interface_addresses:
                    if address.family == socket.AF_INET:
                        interface_info['addresses'].append({
                            'type': 'IPv4',
                            'address': address.address,
                            'netmask': address.netmask,
                            'broadcast': address.broadcast
                        })
                    elif address.family == socket.AF_INET6:
                        interface_info['addresses'].append({
                            'type': 'IPv6',
                            'address': address.address,
                            'netmask': address.netmask
                        })

                if interface_info['addresses']:
                    network_info['interfaces'].append(interface_info)
        except:
            pass

        process_info = {
            'total_processes': len(psutil.pids()),
            'running_processes': len(
                [p for p in psutil.process_iter(['status']) if p.info['status'] == psutil.STATUS_RUNNING]),
            'top_processes': []
        }

        try:
            processes = []
            for proc in psutil.process_iter(['pid', 'name', 'cpu_percent', 'memory_percent', 'username']):
                try:
                    proc.cpu_percent()
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue

            time.sleep(0.1)

            for proc in psutil.process_iter(['pid', 'name', 'cpu_percent', 'memory_percent', 'username']):
                try:
                    pinfo = proc.as_dict(attrs=['pid', 'name', 'cpu_percent', 'memory_percent', 'username'])
                    if pinfo['cpu_percent'] is not None:
                        processes.append(pinfo)
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue

            processes.sort(key=lambda x: x['cpu_percent'] or 0, reverse=True)
            process_info['top_processes'] = processes[:10]
        except:
            pass

        load_averages = None
        try:
            if hasattr(os, 'getloadavg'):
                load_averages = os.getloadavg()
        except:
            pass

        db_status = 'unknown'
        db_info = {}
        try:
            result = db.session.execute(text('SELECT version()')).fetchone()
            if result:
                db_status = 'connected'
                db_info['version'] = result[0] if result[0] else 'Unknown'

                try:
                    size_result = db.session.execute(text(
                        "SELECT pg_size_pretty(pg_database_size(current_database()))"
                    )).fetchone()
                    if size_result:
                        db_info['size'] = size_result[0]
                except:
                    db_info['size'] = 'Unknown'

                try:
                    conn_result = db.session.execute(text(
                        "SELECT count(*) FROM pg_stat_activity WHERE state = 'active'"
                    )).fetchone()
                    if conn_result:
                        db_info['active_connections'] = conn_result[0]
                except:
                    db_info['active_connections'] = 'Unknown'
        except Exception as e:
            db_status = f'error: {str(e)}'

        services_status = {}
        try:
            result = subprocess.run(['systemctl', 'is-active', 'apache2'],
                                    capture_output=True, text=True, timeout=5)
            services_status['apache2'] = result.stdout.strip()
        except:
            services_status['apache2'] = 'unknown'

        try:
            result = subprocess.run(['systemctl', 'is-active', 'postgresql'],
                                    capture_output=True, text=True, timeout=5)
            services_status['postgresql'] = result.stdout.strip()
        except:
            services_status['postgresql'] = 'unknown'

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


def ensure_multipolygon(geometry):
    """Convert Polygon to MultiPolygon if needed"""
    if geometry['type'] == 'Polygon':
        return {
            'type': 'MultiPolygon',
            'coordinates': [geometry['coordinates']]
        }
    return geometry


# Template filters
@app.template_filter('nl2br')
def nl2br_filter(text):
    """Convert newlines to HTML br tags"""
    if not text:
        return ""
    return text.replace('\n', '<br>\n')


@app.template_filter('format_local_datetime')
def format_local_datetime_filter(dt, include_utc=True):
    """Template filter for formatting local datetime"""
    return format_local_datetime(dt, include_utc)


@app.template_filter('format_local_date')
def format_local_date_filter(dt):
    """Template filter for formatting local date"""
    return format_local_date(dt)


@app.template_filter('format_local_time')
def format_local_time_filter(dt):
    """Template filter for formatting local time"""
    return format_local_time(dt)


@app.template_filter('is_expired')
def is_expired_filter(expires_date):
    """Check if an alert has expired"""
    return is_alert_expired(expires_date)


@app.template_global()
def current_time():
    """Provide current datetime to templates"""
    return utc_now()


@app.template_global()
def local_current_time():
    """Provide current local datetime to templates"""
    return local_now()


# Main Routes
@app.route('/')
def index():
    """Main dashboard"""
    try:
        return render_template('index.html')
    except Exception as e:
        logger.error(f"Error rendering index template: {str(e)}")
        return f"<h1>NOAA CAP Alerts System</h1><p>Map interface loading...</p><p><a href='/stats'>📊 Statistics</a> | <a href='/alerts'>📝 Alerts History</a> | <a href='/admin'>⚙️ Admin</a></p>"


@app.route('/admin')
def admin():
    """Admin interface"""
    try:
        # Get some basic stats for the admin dashboard using new helper functions
        total_boundaries = Boundary.query.count()
        total_alerts = CAPAlert.query.count()
        active_alerts = get_active_alerts_query().count()
        expired_alerts = get_expired_alerts_query().count()

        # Get boundary counts by type
        boundary_stats = db.session.query(
            Boundary.type, func.count(Boundary.id).label('count')
        ).group_by(Boundary.type).all()

        return render_template('admin.html',
                               total_boundaries=total_boundaries,
                               total_alerts=total_alerts,
                               active_alerts=active_alerts,
                               expired_alerts=expired_alerts,
                               boundary_stats=boundary_stats
                               )
    except Exception as e:
        logger.error(f"Error rendering admin template: {str(e)}")
        return f"<h1>Admin Interface</h1><p>Admin panel loading...</p><p><a href='/'>← Back to Main</a></p>"


@app.route('/logs')
def logs():
    """View system logs"""
    try:
        logs = SystemLog.query.order_by(SystemLog.timestamp.desc()).limit(100).all()
        return render_template('logs.html', logs=logs)
    except Exception as e:
        logger.error(f"Error loading logs: {str(e)}")
        return f"<h1>Error loading logs</h1><p>{str(e)}</p><p><a href='/'>← Back to Main</a></p>"


@app.route('/stats')
def stats():
    """Enhanced system statistics page"""
    try:
        stats_data = {}

        # Basic counts
        try:
            stats_data.update({
                'total_boundaries': Boundary.query.count(),
                'total_alerts': CAPAlert.query.count(),
                'active_alerts': get_active_alerts_query().count(),
                'expired_alerts': get_expired_alerts_query().count()
            })
        except Exception as e:
            logger.error(f"Error getting basic counts: {str(e)}")
            stats_data.update({
                'total_boundaries': 0, 'total_alerts': 0,
                'active_alerts': 0, 'expired_alerts': 0
            })

        # Boundary stats
        try:
            boundary_stats = db.session.query(
                Boundary.type, func.count(Boundary.id).label('count')
            ).group_by(Boundary.type).all()
            stats_data['boundary_stats'] = [{'type': t, 'count': c} for t, c in boundary_stats]
        except Exception as e:
            logger.error(f"Error getting boundary stats: {str(e)}")
            stats_data['boundary_stats'] = []

        # Alert category stats
        try:
            alert_by_status = db.session.query(
                CAPAlert.status, func.count(CAPAlert.id).label('count')
            ).group_by(CAPAlert.status).all()
            stats_data['alert_by_status'] = [{'status': s, 'count': c} for s, c in alert_by_status]

            alert_by_severity = db.session.query(
                CAPAlert.severity, func.count(CAPAlert.id).label('count')
            ).filter(CAPAlert.severity.isnot(None)).group_by(CAPAlert.severity).all()
            stats_data['alert_by_severity'] = [{'severity': s, 'count': c} for s, c in alert_by_severity]

            alert_by_event = db.session.query(
                CAPAlert.event, func.count(CAPAlert.id).label('count')
            ).group_by(CAPAlert.event).order_by(func.count(CAPAlert.id).desc()).limit(10).all()
            stats_data['alert_by_event'] = [{'event': e, 'count': c} for e, c in alert_by_event]
        except Exception as e:
            logger.error(f"Error getting alert category stats: {str(e)}")
            stats_data.update({
                'alert_by_status': [], 'alert_by_severity': [], 'alert_by_event': []
            })

        # Time-based stats
        try:
            alert_by_hour = db.session.query(
                func.extract('hour', CAPAlert.sent).label('hour'),
                func.count(CAPAlert.id).label('count')
            ).group_by(func.extract('hour', CAPAlert.sent)).all()

            hourly_data = [0] * 24
            for hour, count in alert_by_hour:
                if hour is not None:
                    hourly_data[int(hour)] = count
            stats_data['alert_by_hour'] = hourly_data

            alert_by_dow = db.session.query(
                func.extract('dow', CAPAlert.sent).label('dow'),
                func.count(CAPAlert.id).label('count')
            ).group_by(func.extract('dow', CAPAlert.sent)).all()

            dow_data = [0] * 7
            for dow, count in alert_by_dow:
                if dow is not None:
                    dow_data[int(dow)] = count
            stats_data['alert_by_dow'] = dow_data

            alert_by_month = db.session.query(
                func.extract('month', CAPAlert.sent).label('month'),
                func.count(CAPAlert.id).label('count')
            ).group_by(func.extract('month', CAPAlert.sent)).all()

            monthly_data = [0] * 12
            for month, count in alert_by_month:
                if month is not None:
                    monthly_data[int(month) - 1] = count
            stats_data['alert_by_month'] = monthly_data

            alert_by_year = db.session.query(
                func.extract('year', CAPAlert.sent).label('year'),
                func.count(CAPAlert.id).label('count')
            ).group_by(func.extract('year', CAPAlert.sent)).order_by(func.extract('year', CAPAlert.sent)).all()
            stats_data['alert_by_year'] = [{'year': int(y), 'count': c} for y, c in alert_by_year if y]
        except Exception as e:
            logger.error(f"Error getting time-based stats: {str(e)}")
            stats_data.update({
                'alert_by_hour': [0] * 24,
                'alert_by_dow': [0] * 7,
                'alert_by_month': [0] * 12,
                'alert_by_year': []
            })

        # Most affected boundaries
        try:
            most_affected = db.session.query(
                Boundary.name, Boundary.type, func.count(Intersection.id).label('alert_count')
            ).join(Intersection, Boundary.id == Intersection.boundary_id) \
                .group_by(Boundary.id, Boundary.name, Boundary.type) \
                .order_by(func.count(Intersection.id).desc()).limit(10).all()
            stats_data['most_affected_boundaries'] = [
                {'name': n, 'type': t, 'count': c} for n, t, c in most_affected
            ]
        except Exception as e:
            logger.error(f"Error getting affected boundaries: {str(e)}")
            stats_data['most_affected_boundaries'] = []

        # Duration analysis
        try:
            durations = db.session.query(
                CAPAlert.event,
                (func.extract('epoch', CAPAlert.expires) - func.extract('epoch', CAPAlert.sent)).label(
                    'duration_seconds')
            ).filter(CAPAlert.expires.isnot(None), CAPAlert.sent.isnot(None)).all()

            duration_by_event = defaultdict(list)
            for event, duration in durations:
                if duration and duration > 0:
                    duration_by_event[event].append(duration / 3600)

            avg_durations = [
                {'event': event, 'avg_hours': sum(durs) / len(durs)}
                for event, durs in duration_by_event.items() if durs
            ]
            stats_data['avg_durations'] = sorted(avg_durations, key=lambda x: x['avg_hours'], reverse=True)[:10]
        except Exception as e:
            logger.error(f"Error calculating durations: {str(e)}")
            stats_data['avg_durations'] = []

        # Recent activity (using timezone-aware date calculation)
        try:
            thirty_days_ago = utc_now() - timedelta(days=30)
            recent_alerts = CAPAlert.query.filter(CAPAlert.sent >= thirty_days_ago).count()
            recent_by_day = db.session.query(
                func.date(CAPAlert.sent).label('date'),
                func.count(CAPAlert.id).label('count')
            ).filter(CAPAlert.sent >= thirty_days_ago) \
                .group_by(func.date(CAPAlert.sent)) \
                .order_by(func.date(CAPAlert.sent)).all()

            stats_data['recent_alerts'] = recent_alerts
            stats_data['recent_by_day'] = [
                {'date': str(d), 'count': c} for d, c in recent_by_day
            ]
        except Exception as e:
            logger.error(f"Error getting recent activity: {str(e)}")
            stats_data.update({'recent_alerts': 0, 'recent_by_day': []})

        # Polling statistics
        try:
            poll_stats_query = db.session.query(
                func.count(PollHistory.id).label('total_polls'),
                func.avg(PollHistory.alerts_fetched).label('avg_fetched'),
                func.max(PollHistory.alerts_fetched).label('max_fetched'),
                func.avg(PollHistory.execution_time_ms).label('avg_time_ms')
            ).first()

            successful_polls = PollHistory.query.filter(PollHistory.status == 'SUCCESS').count()
            failed_polls = PollHistory.query.filter(PollHistory.status == 'ERROR').count()
            total_polls_from_history = poll_stats_query.total_polls or 0

            if total_polls_from_history == 0:
                cap_poller_logs = SystemLog.query.filter(
                    SystemLog.module == 'cap_poller',
                    SystemLog.message.like('%CAP polling successful%')
                ).count()

                manual_polls = SystemLog.query.filter(
                    SystemLog.module == 'admin',
                    SystemLog.message.like('%Manual CAP poll triggered%')
                ).count()

                total_polls_from_logs = cap_poller_logs + manual_polls

                stats_data['polling'] = {
                    'total_polls': total_polls_from_logs,
                    'avg_fetched': 0,
                    'max_fetched': 0,
                    'avg_time_ms': 0,
                    'successful_polls': cap_poller_logs,
                    'failed_polls': 0,
                    'success_rate': round((cap_poller_logs / total_polls_from_logs * 100),
                                          1) if total_polls_from_logs > 0 else 0,
                    'data_source': 'system_logs'
                }
            else:
                stats_data['polling'] = {
                    'total_polls': total_polls_from_history,
                    'avg_fetched': round(poll_stats_query.avg_fetched or 0, 1),
                    'max_fetched': poll_stats_query.max_fetched or 0,
                    'avg_time_ms': round(poll_stats_query.avg_time_ms or 0, 1),
                    'successful_polls': successful_polls,
                    'failed_polls': failed_polls,
                    'success_rate': round((successful_polls / (successful_polls + failed_polls) * 100), 1) if (
                                                                                                                      successful_polls + failed_polls) > 0 else 0,
                    'data_source': 'poll_history'
                }

        except Exception as e:
            logger.error(f"Error getting polling stats: {str(e)}")
            try:
                emergency_count = SystemLog.query.filter(SystemLog.module == 'cap_poller').count()
                stats_data['polling'] = {
                    'total_polls': emergency_count,
                    'avg_fetched': 0,
                    'max_fetched': 0,
                    'avg_time_ms': 0,
                    'successful_polls': emergency_count,
                    'failed_polls': 0,
                    'success_rate': 100 if emergency_count > 0 else 0,
                    'data_source': 'emergency_fallback'
                }
            except:
                stats_data['polling'] = {
                    'total_polls': 0, 'avg_fetched': 0, 'max_fetched': 0,
                    'avg_time_ms': 0, 'successful_polls': 0, 'failed_polls': 0, 'success_rate': 0,
                    'data_source': 'error'
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
    """Alerts history page with improved active/expired logic"""
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
            ).filter(
                CAPAlert.status != 'Expired'
            )

        query = query.order_by(CAPAlert.sent.desc())

        alerts_pagination = query.paginate(
            page=page, per_page=per_page, error_out=False
        )

        statuses = [s[0] for s in db.session.query(CAPAlert.status).distinct().all() if s[0]]
        severities = [s[0] for s in db.session.query(CAPAlert.severity).filter(
            CAPAlert.severity.isnot(None)).distinct().all() if s[0]]
        events = [e[0] for e in db.session.query(CAPAlert.event).distinct().limit(20).all() if e[0]]

        total_alerts = CAPAlert.query.count()
        active_alerts = get_active_alerts_query().count()
        expired_alerts = get_expired_alerts_query().count()

        return render_template('alerts.html',
                               alerts=alerts_pagination.items,
                               pagination=alerts_pagination,
                               total_alerts=total_alerts,
                               active_alerts=active_alerts,
                               expired_alerts=expired_alerts,
                               statuses=statuses,
                               severities=severities,
                               events=events,
                               current_filters={
                                   'status': status_filter,
                                   'severity': severity_filter,
                                   'event': event_filter,
                                   'search': search_query,
                                   'show_expired': show_expired,
                                   'per_page': per_page
                               }
                               )

    except Exception as e:
        logger.error(f"Error loading alerts history: {str(e)}")
        return f"<h1>Error loading alerts history</h1><p>{str(e)}</p><p><a href='/'>← Back to Main</a></p>"


@app.route('/alerts/<int:alert_id>')
def alert_detail(alert_id):
    """Individual alert detail page"""
    try:
        alert = CAPAlert.query.get_or_404(alert_id)

        intersections = db.session.query(Intersection, Boundary).join(
            Boundary, Intersection.boundary_id == Boundary.id
        ).filter(Intersection.cap_alert_id == alert_id).all()

        return render_template('alert_detail.html',
                               alert=alert,
                               intersections=intersections
                               )

    except Exception as e:
        logger.error(f"Error loading alert details: {str(e)}")
        return f"<h1>Error loading alert details</h1><p>{str(e)}</p><p><a href='/alerts'>← Back to Alerts</a></p>"


@app.route('/system_health')
def system_health_page():
    """Dedicated system health monitoring page"""
    try:
        health_data = get_system_health()
        health_data['format_bytes'] = format_bytes
        health_data['format_uptime'] = format_uptime
        return render_template('system_health.html', **health_data)
    except Exception as e:
        logger.error(f"Error loading system health page: {str(e)}")
        return f"<h1>Error loading system health</h1><p>{str(e)}</p><p><a href='/'>← Back to Main</a></p>"


# API Routes
@app.route('/api/boundaries')
def get_boundaries():
    """Get all boundaries as GeoJSON"""
    try:
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 1000, type=int)
        boundary_type = request.args.get('type')
        search = request.args.get('search')

        query = db.session.query(
            Boundary.id, Boundary.name, Boundary.type, Boundary.description,
            func.ST_AsGeoJSON(Boundary.geom).label('geometry')
        )

        if boundary_type:
            query = query.filter(Boundary.type == boundary_type)

        if search:
            query = query.filter(Boundary.name.ilike(f'%{search}%'))

        boundaries = query.paginate(
            page=page, per_page=per_page, error_out=False
        ).items

        features = []
        for boundary in boundaries:
            if boundary.geometry:
                features.append({
                    'type': 'Feature',
                    'properties': {
                        'id': boundary.id,
                        'name': boundary.name,
                        'type': boundary.type,
                        'description': boundary.description
                    },
                    'geometry': json.loads(boundary.geometry)
                })

        return jsonify({
            'type': 'FeatureCollection',
            'features': features
        })
    except Exception as e:
        logger.error(f"Error fetching boundaries: {str(e)}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/alerts')
def get_alerts():
    """Get active CAP alerts as GeoJSON using new active logic with timezone support"""
    try:
        # Use helper function for consistent active alerts logic
        alerts_query = get_active_alerts_query()

        alerts = db.session.query(
            CAPAlert.id, CAPAlert.identifier, CAPAlert.event, CAPAlert.severity,
            CAPAlert.urgency, CAPAlert.headline, CAPAlert.description, CAPAlert.expires,
            CAPAlert.area_desc, func.ST_AsGeoJSON(CAPAlert.geom).label('geometry')
        ).filter(
            CAPAlert.id.in_(alerts_query.with_entities(CAPAlert.id).subquery())
        ).all()

        # Get the actual county boundary geometry for fallback
        county_boundary = None
        try:
            county_geom = db.session.query(
                func.ST_AsGeoJSON(Boundary.geom).label('geometry')
            ).filter(
                Boundary.type == 'county'
            ).first()

            if county_geom and county_geom.geometry:
                county_boundary = json.loads(county_geom.geometry)
        except Exception as e:
            logger.warning(f"Could not get county boundary: {str(e)}")

        features = []
        for alert in alerts:
            # Use existing geometry or fall back to county boundary
            geometry = None
            is_county_wide = False

            if alert.geometry:
                geometry = json.loads(alert.geometry)
            elif alert.area_desc and any(county_term in alert.area_desc.lower()
                                         for county_term in ['county', 'putnam', 'ohio']):
                # Use actual county boundary if available
                if county_boundary:
                    geometry = county_boundary
                    is_county_wide = True
                else:
                    # Fallback to approximate Putnam County boundary
                    geometry = {
                        "type": "Polygon",
                        "coordinates": [[
                            [-84.255, 40.954], [-84.254, 40.935], [-84.239, 40.921], [-84.226, 40.903],
                            [-84.210, 40.896], [-84.198, 40.880], [-84.186, 40.866], [-84.174, 40.852],
                            [-84.162, 40.838], [-84.150, 40.824], [-84.138, 40.810], [-84.126, 40.796],
                            [-84.114, 40.782], [-84.102, 40.768], [-84.090, 40.754], [-84.078, 40.740],
                            [-84.066, 40.726], [-84.054, 40.712], [-84.042, 40.698], [-84.030, 40.684],
                            [-84.018, 40.670], [-84.006, 40.656], [-83.994, 40.642], [-83.982, 40.628],
                            [-83.970, 40.614], [-83.958, 40.600], [-83.946, 40.586], [-83.934, 40.572],
                            [-83.922, 40.558], [-83.910, 40.544], [-83.898, 40.530], [-83.886, 40.516],
                            [-83.874, 40.502], [-83.862, 40.488], [-83.850, 40.474], [-83.838, 40.460],
                            [-83.826, 40.446], [-83.814, 40.432], [-83.802, 40.418], [-83.790, 40.404],
                            [-83.778, 40.390], [-83.766, 40.376], [-83.754, 40.362], [-83.742, 40.348],
                            [-83.730, 40.334], [-83.718, 40.320], [-83.706, 40.306], [-83.694, 40.292],
                            [-83.682, 40.278], [-83.670, 40.264], [-83.658, 40.250], [-83.646, 40.236],
                            [-83.634, 40.222], [-83.622, 40.208], [-83.610, 40.194], [-83.598, 40.180],
                            [-83.586, 40.166], [-83.574, 40.152], [-83.562, 40.138], [-83.550, 40.124],
                            [-83.538, 40.110], [-83.526, 40.096], [-83.514, 40.082], [-83.502, 40.068],
                            [-83.490, 40.054], [-83.478, 40.040], [-83.466, 40.026], [-83.454, 40.012],
                            [-83.442, 39.998], [-83.430, 39.984], [-83.750, 40.650], [-84.000, 40.850],
                            [-84.255, 40.954]
                        ]]
                    }
                    is_county_wide = True

            # Check if this should be marked as county-wide based on area description
            if not is_county_wide and alert.area_desc:
                area_lower = alert.area_desc.lower()

                # Multi-county alerts that include Putnam should be treated as county-wide for Putnam
                if 'putnam' in area_lower:
                    # Count counties (semicolons or commas usually separate them)
                    separator_count = max(area_lower.count(';'), area_lower.count(','))
                    if separator_count >= 2:  # 3+ counties = treat as county-wide
                        is_county_wide = True

                # Direct county-wide keywords
                county_keywords = ['county', 'putnam county', 'entire county']
                if any(keyword in area_lower for keyword in county_keywords):
                    is_county_wide = True

            if geometry:
                # Convert expires to ISO format for JavaScript (will be in UTC)
                expires_iso = None
                if alert.expires:
                    if alert.expires.tzinfo is None:
                        expires_dt = alert.expires.replace(tzinfo=UTC_TZ)
                    else:
                        expires_dt = alert.expires.astimezone(UTC_TZ)
                    expires_iso = expires_dt.isoformat()

                features.append({
                    'type': 'Feature',
                    'properties': {
                        'id': alert.id,
                        'identifier': alert.identifier,
                        'event': alert.event,
                        'severity': alert.severity,
                        'urgency': alert.urgency,
                        'headline': alert.headline,
                        'description': alert.description,
                        'area_desc': alert.area_desc,
                        'expires': expires_iso,
                        'is_county_wide': is_county_wide,
                        'geometry_source': 'county_boundary' if is_county_wide and county_boundary else 'original'
                    },
                    'geometry': geometry
                })

        return jsonify({
            'type': 'FeatureCollection',
            'features': features
        })
    except Exception as e:
        logger.error(f"Error fetching alerts: {str(e)}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/system_status')
def api_system_status():
    """Get system status information using new helper functions with timezone support"""
    try:
        total_boundaries = Boundary.query.count()
        active_alerts = get_active_alerts_query().count()

        last_poll = PollHistory.query.order_by(desc(PollHistory.timestamp)).first()

        cpu = psutil.cpu_percent(interval=1)
        memory = psutil.virtual_memory()
        disk = psutil.disk_usage('/')

        current_utc = utc_now()
        current_local = local_now()

        return jsonify({
            'status': 'online',
            'timestamp': current_utc.isoformat(),
            'local_timestamp': current_local.isoformat(),
            'timezone': str(PUTNAM_COUNTY_TZ),
            'boundaries_count': total_boundaries,
            'active_alerts_count': active_alerts,
            'database_status': 'connected',
            'last_poll': {
                'timestamp': last_poll.timestamp.isoformat() if last_poll else None,
                'local_timestamp': last_poll.timestamp.astimezone(PUTNAM_COUNTY_TZ).isoformat() if last_poll else None,
                'status': last_poll.status if last_poll else None,
                'alerts_fetched': last_poll.alerts_fetched if last_poll else 0,
                'alerts_new': last_poll.alerts_new if last_poll else 0
            } if last_poll else None,
            'system_resources': {
                'cpu_usage_percent': cpu,
                'memory_usage_percent': memory.percent,
                'disk_usage_percent': disk.percent,
                'disk_free_gb': disk.free // (1024 * 1024 * 1024)
            }
        })
    except Exception as e:
        logger.error(f"Error getting system status: {str(e)}")
        return jsonify({'error': f'Failed to get system status: {str(e)}'}), 500


@app.route('/api/system_health')
def api_system_health():
    """Get comprehensive system health information via API"""
    try:
        health_data = get_system_health()
        return jsonify(health_data)
    except Exception as e:
        logger.error(f"Error getting system health via API: {str(e)}")
        return jsonify({'error': str(e)}), 500


# Export Routes
@app.route('/export/alerts')
def export_alerts():
    """Export alerts data to Excel with proper timezone formatting"""
    try:
        alerts = CAPAlert.query.order_by(CAPAlert.sent.desc()).all()

        alerts_data = []
        for alert in alerts:
            # Format times in local timezone for export
            sent_local = format_local_datetime(alert.sent, include_utc=False) if alert.sent else ''
            expires_local = format_local_datetime(alert.expires, include_utc=False) if alert.expires else ''
            created_local = format_local_datetime(alert.created_at, include_utc=False) if alert.created_at else ''

            alerts_data.append({
                'ID': alert.id,
                'Identifier': alert.identifier,
                'Event': alert.event,
                'Status': alert.status,
                'Severity': alert.severity or '',
                'Urgency': alert.urgency or '',
                'Certainty': alert.certainty or '',
                'Sent_Local_Time': sent_local,
                'Expires_Local_Time': expires_local,
                'Sent_UTC': alert.sent.isoformat() if alert.sent else '',
                'Expires_UTC': alert.expires.isoformat() if alert.expires else '',
                'Headline': alert.headline or '',
                'Area_Description': alert.area_desc or '',
                'Created_Local_Time': created_local,
                'Is_Expired': is_alert_expired(alert.expires)
            })

        return jsonify({
            'data': alerts_data,
            'total': len(alerts_data),
            'exported_at': utc_now().isoformat(),
            'exported_at_local': local_now().isoformat(),
            'timezone': str(PUTNAM_COUNTY_TZ)
        })

    except Exception as e:
        logger.error(f"Error exporting alerts: {str(e)}")
        return jsonify({'error': 'Failed to export alerts data'}), 500


@app.route('/export/boundaries')
def export_boundaries():
    """Export boundaries data to Excel with timezone formatting"""
    try:
        boundaries = Boundary.query.order_by(Boundary.type, Boundary.name).all()

        boundaries_data = []
        for boundary in boundaries:
            created_local = format_local_datetime(boundary.created_at, include_utc=False) if boundary.created_at else ''
            updated_local = format_local_datetime(boundary.updated_at, include_utc=False) if boundary.updated_at else ''

            boundaries_data.append({
                'ID': boundary.id,
                'Name': boundary.name,
                'Type': boundary.type,
                'Description': boundary.description or '',
                'Created_Local_Time': created_local,
                'Updated_Local_Time': updated_local,
                'Created_UTC': boundary.created_at.isoformat() if boundary.created_at else '',
                'Updated_UTC': boundary.updated_at.isoformat() if boundary.updated_at else ''
            })

        return jsonify({
            'data': boundaries_data,
            'total': len(boundaries_data),
            'exported_at': utc_now().isoformat(),
            'exported_at_local': local_now().isoformat(),
            'timezone': str(PUTNAM_COUNTY_TZ)
        })

    except Exception as e:
        logger.error(f"Error exporting boundaries: {str(e)}")
        return jsonify({'error': 'Failed to export boundaries data'}), 500


@app.route('/export/statistics')
def export_statistics():
    """Export current statistics to Excel with timezone info"""
    try:
        stats_data = [{
            'Metric': 'Total Alerts',
            'Value': CAPAlert.query.count(),
            'Category': 'Alerts'
        }, {
            'Metric': 'Active Alerts',
            'Value': get_active_alerts_query().count(),
            'Category': 'Alerts'
        }, {
            'Metric': 'Expired Alerts',
            'Value': get_expired_alerts_query().count(),
            'Category': 'Alerts'
        }, {
            'Metric': 'Total Boundaries',
            'Value': Boundary.query.count(),
            'Category': 'Boundaries'
        }]

        severity_stats = db.session.query(
            CAPAlert.severity, func.count(CAPAlert.id).label('count')
        ).filter(CAPAlert.severity.isnot(None)).group_by(CAPAlert.severity).all()

        for severity, count in severity_stats:
            stats_data.append({
                'Metric': f'Alerts - {severity}',
                'Value': count,
                'Category': 'Severity'
            })

        boundary_stats = db.session.query(
            Boundary.type, func.count(Boundary.id).label('count')
        ).group_by(Boundary.type).all()

        for btype, count in boundary_stats:
            stats_data.append({
                'Metric': f'Boundaries - {btype.title()}',
                'Value': count,
                'Category': 'Boundary Types'
            })

        return jsonify({
            'data': stats_data,
            'total': len(stats_data),
            'exported_at': utc_now().isoformat(),
            'exported_at_local': local_now().isoformat(),
            'timezone': str(PUTNAM_COUNTY_TZ)
        })

    except Exception as e:
        logger.error(f"Error exporting statistics: {str(e)}")
        return jsonify({'error': 'Failed to export statistics data'}), 500


# Debug Route
@app.route('/debug/boundaries/<int:alert_id>')
def debug_boundaries(alert_id):
    """Debug route to check boundary counts for an alert"""
    try:
        alert = CAPAlert.query.get_or_404(alert_id)

        all_boundaries = Boundary.query.all()
        current_intersections = db.session.query(Intersection, Boundary).join(
            Boundary, Intersection.boundary_id == Boundary.id
        ).filter(Intersection.cap_alert_id == alert_id).all()

        boundary_counts = {}
        for boundary in all_boundaries:
            boundary_counts[boundary.type] = boundary_counts.get(boundary.type, 0) + 1

        is_county_wide = False
        if alert.area_desc:
            area_lower = alert.area_desc.lower()
            county_wide_keywords = ['county', 'putnam county', 'entire county', 'all of putnam']
            putnam_indicators = ['putnam;', 'putnam,', '; putnam;', '; putnam,', ', putnam;', ', putnam,', 'putnam ',
                                 ' putnam']

            if 'putnam' in area_lower:
                county_count = len([x for x in area_lower.split(';') if x.strip()])
                if county_count >= 3:
                    is_county_wide = True

            if any(keyword in area_lower for keyword in county_wide_keywords):
                is_county_wide = True

            if any(indicator in area_lower for indicator in putnam_indicators):
                is_county_wide = True

        # Format alert times with timezone info
        sent_time = format_local_datetime(alert.sent) if alert.sent else 'Unknown'
        expires_time = format_local_datetime(alert.expires) if alert.expires else 'No expiration'
        is_expired = is_alert_expired(alert.expires)

        html = f"""
        <html>
        <head><title>Boundary Debug for Alert {alert_id}</title></head>
        <body style="font-family: Arial; margin: 40px;">
            <h1>Boundary Debug Information</h1>
            <p><a href="/alerts/{alert_id}">← Back to Alert Details</a></p>

            <h2>Alert Information</h2>
            <p><strong>Event:</strong> {alert.event}</p>
            <p><strong>Sent:</strong> {sent_time}</p>
            <p><strong>Expires:</strong> {expires_time}</p>
            <p><strong>Status:</strong> {'EXPIRED' if is_expired else 'ACTIVE'}</p>
            <p><strong>Area Description:</strong> {alert.area_desc or 'None'}</p>
            <p><strong>Detected as County-Wide:</strong> {'Yes' if is_county_wide else 'No'}</p>
        """

        if alert.area_desc:
            area_lower = alert.area_desc.lower()
            county_list = [x.strip() for x in area_lower.split(';') if x.strip()]

            html += f"""
            <h3>County-Wide Detection Analysis</h3>
            <ul>
                <li><strong>Contains 'Putnam':</strong> {'Yes' if 'putnam' in area_lower else 'No'}</li>
                <li><strong>Counties Listed:</strong> {len(county_list)} counties</li>
                <li><strong>Multi-County Alert:</strong> {'Yes' if len(county_list) >= 3 else 'No'}</li>
                <li><strong>County List:</strong> {', '.join(county_list[:10])}{'...' if len(county_list) > 10 else ''}</li>
            </ul>
            """

        html += f"""
            <h2>Total Boundaries in System</h2>
            <ul>
        """

        total_boundaries = 0
        for boundary_type, count in boundary_counts.items():
            html += f"<li><strong>{boundary_type.title()}:</strong> {count}</li>"
            total_boundaries += count

        html += f"""
            </ul>
            <p><strong>Total:</strong> {total_boundaries} boundaries</p>

            <h2>Current Intersections for This Alert</h2>
            <p><strong>Found:</strong> {len(current_intersections)} intersections</p>
            <ul>
        """

        for intersection, boundary in current_intersections:
            html += f"<li>{boundary.type.title()}: {boundary.name}</li>"

        html += f"""
            </ul>

            <h2>Missing Intersections</h2>
            <p>If this is a county-wide alert, it should intersect with ALL {total_boundaries} boundaries.</p>
            <p><strong>Missing:</strong> {total_boundaries - len(current_intersections)} intersections</p>

            <div style="margin: 20px 0;">
                <button onclick="fixIntersections()" style="background: #007bff; color: white; padding: 10px 20px; border: none; border-radius: 4px; cursor: pointer;">
                    Fix All Intersections for This Alert
                </button>
            </div>

            <div id="result" style="margin-top: 20px;"></div>

            <script>
            async function fixIntersections() {{
                const resultDiv = document.getElementById('result');
                resultDiv.innerHTML = 'Fixing intersections...';

                try {{
                    const response = await fetch('/admin/fix_single_alert_intersections/{alert_id}', {{
                        method: 'POST'
                    }});
                    const result = await response.json();

                    if (response.ok) {{
                        resultDiv.innerHTML = '<div style="color: green;">' + result.success + '</div>';
                        setTimeout(() => {{
                            window.location.reload();
                        }}, 2000);
                    }} else {{
                        resultDiv.innerHTML = '<div style="color: red;">' + result.error + '</div>';
                    }}
                }} catch (error) {{
                    resultDiv.innerHTML = '<div style="color: red;">Error: ' + error.message + '</div>';
                }}
            }}
            </script>
        </body>
        </html>
        """

        return html

    except Exception as e:
        return f"<h1>Debug Error</h1><p>{str(e)}</p><p><a href='/alerts/{alert_id}'>← Back to Alert</a></p>"


# ADMIN ROUTES WITH PRESERVATION AND CONFIRMATIONS

@app.route('/admin/trigger_poll', methods=['POST'])
def trigger_poll():
    """Manually trigger CAP alert polling with timezone logging"""
    try:
        log_entry = SystemLog(
            level='INFO',
            message='Manual CAP poll triggered',
            module='admin',
            details={
                'triggered_at_utc': utc_now().isoformat(),
                'triggered_at_local': local_now().isoformat()
            }
        )
        db.session.add(log_entry)
        db.session.commit()

        return jsonify({'message': 'CAP poll triggered successfully'})
    except Exception as e:
        logger.error(f"Error triggering poll: {str(e)}")
        return jsonify({'error': str(e)}), 500


@app.route('/admin/mark_expired', methods=['POST'])
def mark_expired():
    """Mark expired alerts as inactive without deleting them (SAFE OPTION)"""
    try:
        now = utc_now()

        # Find alerts that are expired but not marked as such
        expired_alerts = CAPAlert.query.filter(
            CAPAlert.expires < now,
            CAPAlert.status != 'Expired'
        ).all()

        count = len(expired_alerts)

        if count == 0:
            return jsonify({'message': 'No alerts need to be marked as expired'})

        # Mark as expired instead of deleting
        for alert in expired_alerts:
            alert.status = 'Expired'
            alert.updated_at = now

        db.session.commit()

        log_entry = SystemLog(
            level='INFO',
            message=f'Marked {count} alerts as expired (data preserved)',
            module='admin',
            details={
                'marked_at_utc': now.isoformat(),
                'marked_at_local': local_now().isoformat(),
                'count': count
            }
        )
        db.session.add(log_entry)
        db.session.commit()

        return jsonify({
            'message': f'Marked {count} alerts as expired',
            'note': 'Alert data has been preserved in the database',
            'marked_count': count
        })

    except Exception as e:
        db.session.rollback()
        logger.error(f"Error marking expired alerts: {str(e)}")
        return jsonify({'error': str(e)}), 500


@app.route('/admin/clear_expired', methods=['POST'])
def clear_expired():
    """Clear expired alerts from database with confirmation (DESTRUCTIVE)"""
    try:
        # Check for confirmation parameter
        data = request.get_json() or {}
        confirmed = data.get('confirmed', False)

        if not confirmed:
            # First request - return count and require confirmation
            now = utc_now()
            expired_count = CAPAlert.query.filter(CAPAlert.expires < now).count()

            return jsonify({
                'requires_confirmation': True,
                'message': f'This will permanently delete {expired_count} expired alerts from the database.',
                'warning': 'This action cannot be undone. Historical data will be lost.',
                'expired_count': expired_count
            })

        # Confirmed request - proceed with deletion
        now = utc_now()
        expired_alerts = CAPAlert.query.filter(CAPAlert.expires < now).all()
        count = len(expired_alerts)

        if count == 0:
            return jsonify({'message': 'No expired alerts found to delete'})

        # Log the deletion before it happens
        alert_ids = [alert.id for alert in expired_alerts]
        log_entry = SystemLog(
            level='WARNING',
            message=f'PERMANENT DELETION: Removing {count} expired alerts from database',
            module='admin',
            details={
                'deleted_alert_ids': alert_ids[:10],  # Log first 10 IDs
                'total_deleted': count,
                'deletion_confirmed': True,
                'deleted_at_utc': now.isoformat(),
                'deleted_at_local': local_now().isoformat()
            }
        )
        db.session.add(log_entry)

        # Actually delete the alerts
        for alert in expired_alerts:
            db.session.delete(alert)

        db.session.commit()

        return jsonify({
            'message': f'Permanently deleted {count} expired alerts',
            'warning': 'Historical data has been removed from the database',
            'deleted_count': count
        })

    except Exception as e:
        db.session.rollback()
        logger.error(f"Error clearing expired alerts: {str(e)}")
        return jsonify({'error': str(e)}), 500


@app.route('/admin/alert_status/<int:alert_id>', methods=['POST'])
def update_alert_status(alert_id):
    """Update the status of a specific alert with timezone logging"""
    try:
        data = request.get_json()
        new_status = data.get('status')

        valid_statuses = ['Active', 'Expired', 'Cancelled', 'Test', 'Draft']
        if new_status not in valid_statuses:
            return jsonify({'error': f'Invalid status. Must be one of: {valid_statuses}'}), 400

        alert = CAPAlert.query.get_or_404(alert_id)
        old_status = alert.status

        alert.status = new_status
        alert.updated_at = utc_now()

        db.session.commit()

        log_entry = SystemLog(
            level='INFO',
            message=f'Alert {alert.identifier} status changed from {old_status} to {new_status}',
            module='admin',
            details={
                'updated_at_utc': utc_now().isoformat(),
                'updated_at_local': local_now().isoformat(),
                'alert_id': alert_id,
                'old_status': old_status,
                'new_status': new_status
            }
        )
        db.session.add(log_entry)
        db.session.commit()

        return jsonify({
            'success': f'Alert status updated to {new_status}',
            'alert_id': alert_id,
            'old_status': old_status,
            'new_status': new_status
        })

    except Exception as e:
        db.session.rollback()
        logger.error(f"Error updating alert status: {str(e)}")
        return jsonify({'error': str(e)}), 500


@app.route('/admin/optimize_db', methods=['POST'])
def optimize_db():
    """Run database optimization with fixed VACUUM handling"""
    try:
        start_time = time.time()

        # Get a raw connection and enable autocommit
        raw_connection = db.engine.raw_connection()
        raw_connection.autocommit = True

        cursor = raw_connection.cursor()

        # Run VACUUM ANALYZE outside of transaction
        cursor.execute('VACUUM ANALYZE')

        # Close the raw connection
        cursor.close()
        raw_connection.close()

        execution_time = int((time.time() - start_time) * 1000)

        log_entry = SystemLog(
            level='INFO',
            message=f'Database optimization completed in {execution_time}ms',
            module='admin',
            details={
                'execution_time_ms': execution_time,
                'operation': 'VACUUM ANALYZE',
                'completed_at_utc': utc_now().isoformat(),
                'completed_at_local': local_now().isoformat()
            }
        )
        db.session.add(log_entry)
        db.session.commit()

        return jsonify({
            'message': f'Database optimization completed successfully in {execution_time}ms',
            'execution_time_ms': execution_time
        })

    except Exception as e:
        logger.error(f"Error optimizing database: {str(e)}")
        return jsonify({'error': f'Database optimization failed: {str(e)}'}), 500


@app.route('/admin/check_db_health', methods=['GET'])
def check_db_health():
    """Check database health and vacuum status"""
    try:
        health_info = {}

        # Check basic connectivity
        result = db.session.execute(text('SELECT 1')).fetchone()
        health_info['connectivity'] = 'OK' if result else 'Failed'

        # Get database size
        try:
            size_result = db.session.execute(text(
                "SELECT pg_size_pretty(pg_database_size(current_database()))"
            )).fetchone()
            health_info['database_size'] = size_result[0] if size_result else 'Unknown'
        except:
            health_info['database_size'] = 'Unknown'

        # Get table statistics
        try:
            table_stats = db.session.execute(text("""
                                                  SELECT schemaname,
                                                         tablename,
                                                         n_tup_ins,
                                                         n_tup_upd,
                                                         n_tup_del,
                                                         last_vacuum,
                                                         last_autovacuum,
                                                         last_analyze,
                                                         last_autoanalyze
                                                  FROM pg_stat_user_tables
                                                  WHERE schemaname = 'public'
                                                  ORDER BY tablename
                                                  """)).fetchall()

            health_info['table_statistics'] = []
            for stat in table_stats:
                health_info['table_statistics'].append({
                    'table': stat[1],
                    'inserts': stat[2],
                    'updates': stat[3],
                    'deletes': stat[4],
                    'last_vacuum': str(stat[5]) if stat[5] else 'Never',
                    'last_autovacuum': str(stat[6]) if stat[6] else 'Never',
                    'last_analyze': str(stat[7]) if stat[7] else 'Never',
                    'last_autoanalyze': str(stat[8]) if stat[8] else 'Never'
                })
        except Exception as e:
            health_info['table_statistics_error'] = str(e)

        # Get active connections
        try:
            conn_result = db.session.execute(text(
                "SELECT count(*) FROM pg_stat_activity WHERE state = 'active'"
            )).fetchone()
            health_info['active_connections'] = conn_result[0] if conn_result else 0
        except:
            health_info['active_connections'] = 'Unknown'

        # Add timezone info
        health_info['checked_at_utc'] = utc_now().isoformat()
        health_info['checked_at_local'] = local_now().isoformat()
        health_info['timezone'] = str(PUTNAM_COUNTY_TZ)

        return jsonify(health_info)

    except Exception as e:
        logger.error(f"Error checking database health: {str(e)}")
        return jsonify({'error': str(e)}), 500


# BOUNDARY MANAGEMENT WITH CONFIRMATIONS

@app.route('/admin/preview_geojson', methods=['POST'])
def preview_geojson():
    """Preview what will be extracted from a GeoJSON file"""
    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400

    file = request.files['file']
    boundary_type = request.form.get('boundary_type', 'unknown')

    if file.filename == '':
        return jsonify({'error': 'No file selected'}), 400

    if file and (file.filename.endswith('.geojson') or file.filename.endswith('.json')):
        try:
            geojson_data = json.load(file)

            features = geojson_data.get('features', [])[:10]
            preview_data = []
            all_fields = set()

            for feature in features:
                if feature.get('properties'):
                    properties = feature['properties']
                    all_fields.update(properties.keys())

                    name, description = extract_name_and_description(properties, boundary_type)

                    preview_data.append({
                        'name': name,
                        'description': description,
                        'properties': properties
                    })

            return jsonify({
                'total_features': len(geojson_data.get('features', [])),
                'preview_count': len(preview_data),
                'boundary_type': boundary_type,
                'all_fields': sorted(list(all_fields)),
                'previews': preview_data,
                'field_mappings': get_field_mappings().get(boundary_type, {})
            })

        except Exception as e:
            logger.error(f"Error previewing GeoJSON: {str(e)}")
            return jsonify({'error': f'Error reading file: {str(e)}'}), 500

    return jsonify({'error': 'Invalid file type. Please upload a .geojson or .json file.'}), 400


@app.route('/admin/upload_boundary', methods=['POST'])
def upload_boundary():
    """Upload and import GeoJSON boundary file with smart field detection"""
    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400

    file = request.files['file']
    boundary_type = request.form.get('boundary_type')

    if file.filename == '':
        return jsonify({'error': 'No file selected'}), 400

    if file and (file.filename.endswith('.geojson') or file.filename.endswith('.json')):
        try:
            geojson_data = json.load(file)
            imported_count = 0
            skipped_count = 0

            for feature in geojson_data.get('features', []):
                if feature.get('geometry') and feature.get('properties'):
                    try:
                        name, description = extract_name_and_description(
                            feature['properties'], boundary_type
                        )

                        geometry = ensure_multipolygon(feature['geometry'])

                        boundary = Boundary(
                            name=name,
                            type=boundary_type,
                            description=description,
                            geom=ST_GeomFromGeoJSON(json.dumps(geometry))
                        )

                        db.session.add(boundary)
                        imported_count += 1

                    except Exception as e:
                        logger.warning(f"Skipped feature due to error: {str(e)}")
                        skipped_count += 1
                        continue
                else:
                    skipped_count += 1

            db.session.commit()

            log_entry = SystemLog(
                level='INFO',
                message=f'Imported {imported_count} {boundary_type} boundaries (skipped {skipped_count})',
                module='admin',
                details={
                    'boundary_type': boundary_type,
                    'imported_count': imported_count,
                    'skipped_count': skipped_count,
                    'imported_at_utc': utc_now().isoformat(),
                    'imported_at_local': local_now().isoformat()
                }
            )
            db.session.add(log_entry)
            db.session.commit()

            message = f'Imported {imported_count} boundaries'
            if skipped_count > 0:
                message += f' (skipped {skipped_count} invalid features)'

            return jsonify({'success': message})

        except Exception as e:
            db.session.rollback()
            logger.error(f"Error importing boundaries: {str(e)}")
            return jsonify({'error': f'Error importing boundaries: {str(e)}'}), 500

    return jsonify({'error': 'Invalid file type. Please upload a .geojson or .json file.'}), 400


@app.route('/admin/delete_boundary/<int:boundary_id>', methods=['DELETE'])
def delete_boundary(boundary_id):
    """Delete a specific boundary"""
    try:
        boundary = Boundary.query.get_or_404(boundary_id)
        boundary_name = boundary.name
        boundary_type = boundary.type

        db.session.delete(boundary)
        db.session.commit()

        log_entry = SystemLog(
            level='INFO',
            message=f'Deleted {boundary_type} boundary: {boundary_name}',
            module='admin',
            details={
                'boundary_id': boundary_id,
                'boundary_name': boundary_name,
                'boundary_type': boundary_type,
                'deleted_at_utc': utc_now().isoformat(),
                'deleted_at_local': local_now().isoformat()
            }
        )
        db.session.add(log_entry)
        db.session.commit()

        return jsonify({'success': f'Boundary "{boundary_name}" deleted successfully'})

    except Exception as e:
        db.session.rollback()
        logger.error(f"Error deleting boundary {boundary_id}: {str(e)}")
        return jsonify({'error': f'Failed to delete boundary: {str(e)}'}), 500


# Error handlers
@app.errorhandler(404)
def not_found_error(error):
    """Enhanced 404 error page"""
    return "<h1>404 - Page Not Found</h1><p><a href='/'>← Back to Main</a></p>", 404


@app.errorhandler(500)
def internal_error(error):
    """Enhanced 500 error page"""
    if hasattr(db, 'session') and db.session:
        db.session.rollback()
    return "<h1>500 - Internal Server Error</h1><p><a href='/'>← Back to Main</a></p>", 500


if __name__ == '__main__':
    with app.app_context():
        db.create_all()

    app.run(debug=True, host='0.0.0.0', port=5000)