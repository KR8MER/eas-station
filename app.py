#!/usr/bin/env python3
"""
NOAA CAP Alerts and GIS Boundary Mapping System
Flask Web Application with Enhanced Boundary Management and Alerts History
"""

import os
import json
import psutil
import platform
import socket
import subprocess
import shutil
import time
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

logger.info("NOAA Alerts System startup")


# Database Models
class Boundary(db.Model):
    __tablename__ = 'boundaries'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False)
    type = db.Column(db.String(50), nullable=False)
    description = db.Column(db.Text)
    geom = db.Column(Geometry('MULTIPOLYGON', srid=4326))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


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
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class SystemLog(db.Model):
    __tablename__ = 'system_log'

    id = db.Column(db.Integer, primary_key=True)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
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
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class PollHistory(db.Model):
    __tablename__ = 'poll_history'

    id = db.Column(db.Integer, primary_key=True)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    status = db.Column(db.String(20), nullable=False)
    alerts_fetched = db.Column(db.Integer, default=0)
    alerts_new = db.Column(db.Integer, default=0)
    alerts_updated = db.Column(db.Integer, default=0)
    execution_time_ms = db.Column(db.Integer)
    error_message = db.Column(db.Text)


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
            'timestamp': datetime.utcnow().isoformat(),
            'system': {
                'hostname': uname.node,
                'system': uname.system,
                'release': uname.release,
                'version': uname.version,
                'machine': uname.machine,
                'processor': uname.processor,
                'boot_time': datetime.fromtimestamp(boot_time).isoformat(),
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
            'timestamp': datetime.utcnow().isoformat()
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


@app.template_global()
def moment():
    """Provide current datetime to templates"""
    return datetime.utcnow()


@app.template_filter('is_expired')
def is_expired_filter(expires_date):
    """Check if an alert has expired"""
    if not expires_date:
        return False
    return expires_date < datetime.utcnow()


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
        # Get some basic stats for the admin dashboard
        total_boundaries = Boundary.query.count()
        total_alerts = CAPAlert.query.count()
        active_alerts = CAPAlert.query.filter(
            or_(CAPAlert.expires.is_(None), CAPAlert.expires > datetime.utcnow())
        ).count()

        # Get boundary counts by type
        boundary_stats = db.session.query(
            Boundary.type, func.count(Boundary.id).label('count')
        ).group_by(Boundary.type).all()

        return render_template('admin.html',
                               total_boundaries=total_boundaries,
                               total_alerts=total_alerts,
                               active_alerts=active_alerts,
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

        try:
            now = datetime.utcnow()
            stats_data.update({
                'total_boundaries': Boundary.query.count(),
                'total_alerts': CAPAlert.query.count(),
                'active_alerts': CAPAlert.query.filter(
                    or_(CAPAlert.expires.is_(None), CAPAlert.expires > now)
                ).count(),
                'expired_alerts': CAPAlert.query.filter(CAPAlert.expires < now).count()
            })
        except Exception as e:
            logger.error(f"Error getting basic counts: {str(e)}")
            stats_data.update({
                'total_boundaries': 0, 'total_alerts': 0,
                'active_alerts': 0, 'expired_alerts': 0
            })

        try:
            boundary_stats = db.session.query(
                Boundary.type, func.count(Boundary.id).label('count')
            ).group_by(Boundary.type).all()
            stats_data['boundary_stats'] = [{'type': t, 'count': c} for t, c in boundary_stats]
        except Exception as e:
            logger.error(f"Error getting boundary stats: {str(e)}")
            stats_data['boundary_stats'] = []

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

        try:
            thirty_days_ago = now - timedelta(days=30)
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
    """Alerts history page"""
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

        now = datetime.utcnow()
        if not show_expired:
            query = query.filter(
                or_(CAPAlert.expires.is_(None), CAPAlert.expires > now)
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
        active_alerts = CAPAlert.query.filter(
            or_(CAPAlert.expires.is_(None), CAPAlert.expires > now)
        ).count()
        expired_alerts = total_alerts - active_alerts

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
    """Get all boundaries as GeoJSON with county-wide alert fixing"""
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
    """Get active CAP alerts as GeoJSON with county-wide coverage fix"""
    try:
        now = datetime.utcnow()

        # Get alerts that are either unexpired or covering the county
        alerts = db.session.query(
            CAPAlert.id, CAPAlert.identifier, CAPAlert.event, CAPAlert.severity,
            CAPAlert.urgency, CAPAlert.headline, CAPAlert.description, CAPAlert.expires,
            CAPAlert.area_desc, func.ST_AsGeoJSON(CAPAlert.geom).label('geometry')
        ).filter(
            or_(
                CAPAlert.expires.is_(None),
                CAPAlert.expires > now,
                # Include county-wide alerts even if slightly expired (within 1 hour)
                CAPAlert.area_desc.ilike('%county%')
            )
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
                            [-84.255, 40.954],  # NW
                            [-84.254, 40.935],  #
                            [-84.239, 40.921],  #
                            [-84.226, 40.903],  #
                            [-84.210, 40.896],  #
                            [-84.198, 40.880],  #
                            [-84.186, 40.866],  #
                            [-84.174, 40.852],  #
                            [-84.162, 40.838],  #
                            [-84.150, 40.824],  #
                            [-84.138, 40.810],  #
                            [-84.126, 40.796],  #
                            [-84.114, 40.782],  #
                            [-84.102, 40.768],  #
                            [-84.090, 40.754],  #
                            [-84.078, 40.740],  #
                            [-84.066, 40.726],  #
                            [-84.054, 40.712],  #
                            [-84.042, 40.698],  #
                            [-84.030, 40.684],  #
                            [-84.018, 40.670],  #
                            [-84.006, 40.656],  #
                            [-83.994, 40.642],  #
                            [-83.982, 40.628],  #
                            [-83.970, 40.614],  #
                            [-83.958, 40.600],  #
                            [-83.946, 40.586],  #
                            [-83.934, 40.572],  #
                            [-83.922, 40.558],  #
                            [-83.910, 40.544],  #
                            [-83.898, 40.530],  #
                            [-83.886, 40.516],  #
                            [-83.874, 40.502],  #
                            [-83.862, 40.488],  #
                            [-83.850, 40.474],  #
                            [-83.838, 40.460],  #
                            [-83.826, 40.446],  #
                            [-83.814, 40.432],  #
                            [-83.802, 40.418],  #
                            [-83.790, 40.404],  #
                            [-83.778, 40.390],  #
                            [-83.766, 40.376],  #
                            [-83.754, 40.362],  #
                            [-83.742, 40.348],  #
                            [-83.730, 40.334],  #
                            [-83.718, 40.320],  #
                            [-83.706, 40.306],  #
                            [-83.694, 40.292],  #
                            [-83.682, 40.278],  #
                            [-83.670, 40.264],  #
                            [-83.658, 40.250],  #
                            [-83.646, 40.236],  #
                            [-83.634, 40.222],  #
                            [-83.622, 40.208],  #
                            [-83.610, 40.194],  #
                            [-83.598, 40.180],  #
                            [-83.586, 40.166],  #
                            [-83.574, 40.152],  #
                            [-83.562, 40.138],  #
                            [-83.550, 40.124],  #
                            [-83.538, 40.110],  #
                            [-83.526, 40.096],  #
                            [-83.514, 40.082],  #
                            [-83.502, 40.068],  #
                            [-83.490, 40.054],  #
                            [-83.478, 40.040],  #
                            [-83.466, 40.026],  #
                            [-83.454, 40.012],  #
                            [-83.442, 39.998],  #
                            [-83.430, 39.984],  # SE (approximate)
                            [-83.750, 40.650],  # Eastern boundary
                            [-84.000, 40.850],  # Northern boundary
                            [-84.255, 40.954]  # Close polygon
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
                        'expires': alert.expires.isoformat() if alert.expires else None,
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
    """Get system status information"""
    try:
        total_boundaries = Boundary.query.count()
        active_alerts = CAPAlert.query.filter(
            or_(CAPAlert.expires.is_(None), CAPAlert.expires > datetime.utcnow())
        ).count()

        last_poll = PollHistory.query.order_by(desc(PollHistory.timestamp)).first()

        cpu = psutil.cpu_percent(interval=1)
        memory = psutil.virtual_memory()
        disk = psutil.disk_usage('/')

        return jsonify({
            'status': 'online',
            'timestamp': datetime.utcnow().isoformat(),
            'boundaries_count': total_boundaries,
            'active_alerts_count': active_alerts,
            'database_status': 'connected',
            'last_poll': {
                'timestamp': last_poll.timestamp.isoformat() if last_poll else None,
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
    """Export alerts data to Excel"""
    try:
        alerts = CAPAlert.query.order_by(CAPAlert.sent.desc()).all()

        alerts_data = []
        for alert in alerts:
            alerts_data.append({
                'ID': alert.id,
                'Identifier': alert.identifier,
                'Event': alert.event,
                'Status': alert.status,
                'Severity': alert.severity or '',
                'Urgency': alert.urgency or '',
                'Certainty': alert.certainty or '',
                'Sent': alert.sent.strftime('%Y-%m-%d %H:%M:%S') if alert.sent else '',
                'Expires': alert.expires.strftime('%Y-%m-%d %H:%M:%S') if alert.expires else '',
                'Headline': alert.headline or '',
                'Area_Description': alert.area_desc or '',
                'Created_At': alert.created_at.strftime('%Y-%m-%d %H:%M:%S') if alert.created_at else ''
            })

        return jsonify({
            'data': alerts_data,
            'total': len(alerts_data),
            'exported_at': datetime.utcnow().isoformat()
        })

    except Exception as e:
        logger.error(f"Error exporting alerts: {str(e)}")
        return jsonify({'error': 'Failed to export alerts data'}), 500


@app.route('/export/boundaries')
def export_boundaries():
    """Export boundaries data to Excel"""
    try:
        boundaries = Boundary.query.order_by(Boundary.type, Boundary.name).all()

        boundaries_data = []
        for boundary in boundaries:
            boundaries_data.append({
                'ID': boundary.id,
                'Name': boundary.name,
                'Type': boundary.type,
                'Description': boundary.description or '',
                'Created_At': boundary.created_at.strftime('%Y-%m-%d %H:%M:%S') if boundary.created_at else '',
                'Updated_At': boundary.updated_at.strftime('%Y-%m-%d %H:%M:%S') if boundary.updated_at else ''
            })

        return jsonify({
            'data': boundaries_data,
            'total': len(boundaries_data),
            'exported_at': datetime.utcnow().isoformat()
        })

    except Exception as e:
        logger.error(f"Error exporting boundaries: {str(e)}")
        return jsonify({'error': 'Failed to export boundaries data'}), 500


@app.route('/export/statistics')
def export_statistics():
    """Export current statistics to Excel"""
    try:
        now = datetime.utcnow()

        stats_data = [{
            'Metric': 'Total Alerts',
            'Value': CAPAlert.query.count(),
            'Category': 'Alerts'
        }, {
            'Metric': 'Active Alerts',
            'Value': CAPAlert.query.filter(
                or_(CAPAlert.expires.is_(None), CAPAlert.expires > now)
            ).count(),
            'Category': 'Alerts'
        }, {
            'Metric': 'Expired Alerts',
            'Value': CAPAlert.query.filter(CAPAlert.expires < now).count(),
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
            'exported_at': datetime.utcnow().isoformat()
        })

    except Exception as e:
        logger.error(f"Error exporting statistics: {str(e)}")
        return jsonify({'error': 'Failed to export statistics data'}), 500


# Add diagnostic route to check boundary counts
@app.route('/debug/boundaries/<int:alert_id>')
def debug_boundaries(alert_id):
    """Debug route to check boundary counts for an alert"""
    try:
        alert = CAPAlert.query.get_or_404(alert_id)

        # Get all boundaries in the system
        all_boundaries = Boundary.query.all()

        # Get current intersections for this alert
        current_intersections = db.session.query(Intersection, Boundary).join(
            Boundary, Intersection.boundary_id == Boundary.id
        ).filter(Intersection.cap_alert_id == alert_id).all()

        # Group boundaries by type
        boundary_counts = {}
        for boundary in all_boundaries:
            boundary_counts[boundary.type] = boundary_counts.get(boundary.type, 0) + 1

        # Check if this should be county-wide (improved detection - same as main logic)
        is_county_wide = False
        if alert.area_desc:
            area_lower = alert.area_desc.lower()

            # Method 1: Direct county-wide keywords
            county_wide_keywords = [
                'county', 'putnam county', 'entire county', 'all of putnam'
            ]

            # Method 2: Check if Putnam is listed among counties
            putnam_indicators = [
                'putnam;', 'putnam,', '; putnam;', '; putnam,',
                ', putnam;', ', putnam,', 'putnam ', ' putnam'
            ]

            # Method 3: Multi-county alerts that include Putnam
            if 'putnam' in area_lower:
                # Count how many counties are mentioned (semicolons usually separate counties)
                county_count = len([x for x in area_lower.split(';') if x.strip()])

                # If it's a multi-county alert including Putnam, treat as county-wide for Putnam
                if county_count >= 3:  # 3 or more counties = regional alert
                    is_county_wide = True

            # Check direct keywords
            if any(keyword in area_lower for keyword in county_wide_keywords):
                is_county_wide = True

            # Check Putnam-specific indicators
            if any(indicator in area_lower for indicator in putnam_indicators):
                is_county_wide = True

        html = f"""
        <html>
        <head><title>Boundary Debug for Alert {alert_id}</title></head>
        <body style="font-family: Arial; margin: 40px;">
            <h1>Boundary Debug Information</h1>
            <p><a href="/alerts/{alert_id}">← Back to Alert Details</a></p>

            <h2>Alert Information</h2>
            <p><strong>Event:</strong> {alert.event}</p>
            <p><strong>Area Description:</strong> {alert.area_desc or 'None'}</p>
            <p><strong>Detected as County-Wide:</strong> {'Yes' if is_county_wide else 'No'}</p>
        """

        # Add detection reasoning
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


# Add route to fix intersections for a single alert
@app.route('/admin/fix_single_alert_intersections/<int:alert_id>', methods=['POST'])
def fix_single_alert_intersections(alert_id):
    """Fix intersections for a specific alert"""
    try:
        alert = CAPAlert.query.get_or_404(alert_id)

        # Delete existing intersections for this alert
        Intersection.query.filter_by(cap_alert_id=alert_id).delete()

        # Check if this should be county-wide (improved detection)
        is_county_wide = False
        if alert.area_desc:
            area_lower = alert.area_desc.lower()

            # Method 1: Direct county-wide keywords
            county_wide_keywords = [
                'county', 'putnam county', 'entire county', 'all of putnam'
            ]

            # Method 2: Check if Putnam is listed among counties
            putnam_indicators = [
                'putnam;', 'putnam,', '; putnam;', '; putnam,',
                ', putnam;', ', putnam,', 'putnam ', ' putnam'
            ]

            # Method 3: Multi-county alerts that include Putnam
            if 'putnam' in area_lower:
                # Count how many counties are mentioned (semicolons usually separate counties)
                county_count = len([x for x in area_lower.split(';') if x.strip()])

                # If it's a multi-county alert including Putnam, treat as county-wide for Putnam
                if county_count >= 3:  # 3 or more counties = regional alert
                    is_county_wide = True

            # Check direct keywords
            if any(keyword in area_lower for keyword in county_wide_keywords):
                is_county_wide = True

            # Check Putnam-specific indicators
            if any(indicator in area_lower for indicator in putnam_indicators):
                is_county_wide = True

        intersections_created = 0

        if is_county_wide:
            # For county-wide alerts, intersect with ALL boundaries
            all_boundaries = Boundary.query.all()

            for boundary in all_boundaries:
                # Calculate intersection area based on boundary area
                intersection_area = 0
                if boundary.geom:
                    try:
                        area_result = db.session.execute(text("""
                                                              SELECT ST_Area(ST_Transform(geom, 3857)) as area
                                                              FROM boundaries
                                                              WHERE id = :boundary_id
                                                              """), {'boundary_id': boundary.id}).fetchone()

                        if area_result:
                            intersection_area = area_result[0]
                    except Exception as e:
                        logger.warning(f"Could not calculate area for boundary {boundary.id}: {e}")

                # Create intersection record
                intersection = Intersection(
                    cap_alert_id=alert_id,
                    boundary_id=boundary.id,
                    intersection_area=intersection_area or 0
                )

                db.session.add(intersection)
                intersections_created += 1

        elif alert.geom:
            # For regular alerts with geometry, use spatial intersection
            try:
                intersecting_boundaries = db.session.query(Boundary).filter(
                    ST_Intersects(Boundary.geom, alert.geom)
                ).all()

                for boundary in intersecting_boundaries:
                    # Calculate actual intersection area
                    try:
                        intersection_area = db.session.scalar(
                            text("""
                                 SELECT ST_Area(ST_Intersection(
                                         ST_Transform(b.geom, 3857),
                                         ST_Transform(a.geom, 3857)
                                                )) as area
                                 FROM boundaries b,
                                      cap_alerts a
                                 WHERE b.id = :boundary_id
                                   AND a.id = :alert_id
                                 """),
                            {'boundary_id': boundary.id, 'alert_id': alert_id}
                        )
                    except Exception as e:
                        logger.warning(f"Could not calculate intersection area: {e}")
                        intersection_area = 0

                    intersection = Intersection(
                        cap_alert_id=alert_id,
                        boundary_id=boundary.id,
                        intersection_area=intersection_area or 0
                    )

                    db.session.add(intersection)
                    intersections_created += 1

            except Exception as e:
                logger.error(f"Error calculating spatial intersections: {e}")

        db.session.commit()

        log_entry = SystemLog(
            level='INFO',
            message=f'Fixed intersections for alert {alert_id}: created {intersections_created} intersection records',
            module='admin'
        )
        db.session.add(log_entry)
        db.session.commit()

        return jsonify({
            'success': f'Created {intersections_created} intersection records for this alert',
            'alert_type': 'county-wide' if is_county_wide else 'localized',
            'intersections_created': intersections_created
        })

    except Exception as e:
        db.session.rollback()
        logger.error(f"Error fixing intersections for alert {alert_id}: {str(e)}")
        return jsonify({'error': f'Failed to fix intersections: {str(e)}'}), 500


@app.route('/admin/fix_county_intersections', methods=['POST'])
def fix_county_intersections():
    """Fix intersections for county-wide alerts that use fallback geometry"""
    try:
        # Get county-wide alerts that might need intersection fixes
        county_alerts = CAPAlert.query.filter(
            or_(
                CAPAlert.area_desc.ilike('%county%'),
                CAPAlert.area_desc.ilike('%putnam%')
            )
        ).all()

        fixed_count = 0

        for alert in county_alerts:
            # Check if this alert already has intersections
            existing_intersections = Intersection.query.filter_by(cap_alert_id=alert.id).count()

            # If no intersections exist or very few, try to create them
            if existing_intersections < 2:  # Assume county should intersect with multiple boundaries
                try:
                    # Get all boundaries in the county
                    all_boundaries = Boundary.query.all()

                    for boundary in all_boundaries:
                        # Check if intersection already exists
                        existing = Intersection.query.filter_by(
                            cap_alert_id=alert.id,
                            boundary_id=boundary.id
                        ).first()

                        if not existing:
                            # For county-wide alerts, assume they intersect with all boundaries
                            # Calculate a reasonable intersection area based on boundary type
                            if boundary.geom:
                                try:
                                    # Try to calculate actual intersection area
                                    area_result = db.session.execute(text("""
                                                                          SELECT ST_Area(ST_Transform(geom, 3857)) as area
                                                                          FROM boundaries
                                                                          WHERE id = :boundary_id
                                                                          """), {'boundary_id': boundary.id}).fetchone()

                                    intersection_area = area_result[0] if area_result else 0
                                except:
                                    # Fallback area estimates by boundary type
                                    area_estimates = {
                                        'county': 1500000000,  # ~580 sq miles
                                        'township': 150000000,  # ~58 sq miles
                                        'village': 10000000,  # ~4 sq miles
                                        'fire': 100000000,  # ~39 sq miles
                                        'ems': 100000000,  # ~39 sq miles
                                        'electric': 200000000,  # ~77 sq miles
                                        'telephone': 150000000,  # ~58 sq miles
                                        'school': 120000000  # ~46 sq miles
                                    }
                                    intersection_area = area_estimates.get(boundary.type, 50000000)
                            else:
                                intersection_area = 50000000  # Default ~19 sq miles

                            # Create intersection record
                            intersection = Intersection(
                                cap_alert_id=alert.id,
                                boundary_id=boundary.id,
                                intersection_area=intersection_area
                            )

                            db.session.add(intersection)
                            fixed_count += 1

                except Exception as e:
                    logger.warning(f"Error processing intersections for alert {alert.id}: {str(e)}")
                    continue

        db.session.commit()

        log_entry = SystemLog(
            level='INFO',
            message=f'Fixed {fixed_count} county-wide alert intersections',
            module='admin'
        )
        db.session.add(log_entry)
        db.session.commit()

        return jsonify({
            'success': f'Fixed intersections for {fixed_count} boundary relationships',
            'message': f'County-wide alerts now properly show affected boundaries'
        })

    except Exception as e:
        db.session.rollback()
        logger.error(f"Error fixing county intersections: {str(e)}")
        return jsonify({'error': f'Failed to fix intersections: {str(e)}'}), 500


# Update the CAP poller intersection processing to handle county-wide alerts better
def process_intersections_enhanced(alert: CAPAlert):
    """Enhanced intersection processing for county-wide alerts"""
    try:
        # Check if this is a county-wide alert
        is_county_wide = bool(alert.area_desc and any(
            term in alert.area_desc.lower()
            for term in ['county', 'putnam county', 'entire county']
        ))

        if is_county_wide:
            # For county-wide alerts, intersect with all boundaries
            all_boundaries = db.session.query(Boundary).all()

            logger.info(f"Processing county-wide alert {alert.identifier} against all {len(all_boundaries)} boundaries")

            for boundary in all_boundaries:
                # Check if intersection already exists
                existing_intersection = db.session.query(Intersection).filter_by(
                    cap_alert_id=alert.id,
                    boundary_id=boundary.id
                ).first()

                if existing_intersection:
                    continue

                # Calculate intersection area
                intersection_area = 0
                if boundary.geom:
                    try:
                        # Calculate actual area of the boundary (approximation for county-wide)
                        area_result = db.session.execute(text("""
                                                              SELECT ST_Area(ST_Transform(geom, 3857)) as area
                                                              FROM boundaries
                                                              WHERE id = :boundary_id
                                                              """), {'boundary_id': boundary.id}).fetchone()

                        if area_result:
                            intersection_area = area_result[0]
                    except Exception as e:
                        logger.warning(f"Could not calculate area for boundary {boundary.id}: {e}")
                        intersection_area = 0

                # Save intersection record
                intersection = Intersection(
                    cap_alert_id=alert.id,
                    boundary_id=boundary.id,
                    intersection_area=intersection_area or 0
                )

                db.session.add(intersection)
                logger.debug(f"County-wide alert {alert.identifier} intersects with {boundary.type} '{boundary.name}'")

        elif alert.geom:
            # Regular alert with geometry - use spatial intersection
            intersecting_boundaries = db.session.query(Boundary).filter(
                ST_Intersects(Boundary.geom, alert.geom)
            ).all()

            logger.info(f"Alert {alert.identifier} intersects with {len(intersecting_boundaries)} boundaries")

            for boundary in intersecting_boundaries:
                # Check if intersection already exists
                existing_intersection = db.session.query(Intersection).filter_by(
                    cap_alert_id=alert.id,
                    boundary_id=boundary.id
                ).first()

                if existing_intersection:
                    continue

                # Calculate intersection area
                try:
                    intersection_area = db.session.scalar(
                        text("""
                             SELECT ST_Area(ST_Intersection(
                                     ST_Transform(b.geom, 3857),
                                     ST_Transform(a.geom, 3857)
                                            )) as area
                             FROM boundaries b,
                                  cap_alerts a
                             WHERE b.id = :boundary_id
                               AND a.id = :alert_id
                             """),
                        {'boundary_id': boundary.id, 'alert_id': alert.id}
                    )
                except Exception as e:
                    logger.warning(f"Could not calculate intersection area: {e}")
                    intersection_area = 0

                # Save intersection record
                intersection = Intersection(
                    cap_alert_id=alert.id,
                    boundary_id=boundary.id,
                    intersection_area=intersection_area or 0
                )

                db.session.add(intersection)
                logger.info(f"Alert {alert.identifier} intersects with {boundary.type} boundary '{boundary.name}'")

        db.session.commit()

    except Exception as e:
        db.session.rollback()
        logger.error(f"Error processing intersections: {str(e)}")


# Add the enhanced function to the admin routes section
@app.route('/admin/recalculate_intersections', methods=['POST'])
def recalculate_intersections():
    """Recalculate all intersections for existing alerts"""
    try:
        # Get all active alerts
        active_alerts = CAPAlert.query.filter(
            or_(CAPAlert.expires.is_(None), CAPAlert.expires > datetime.utcnow())
        ).all()

        total_processed = 0
        total_intersections = 0

        for alert in active_alerts:
            # Delete existing intersections for this alert
            Intersection.query.filter_by(cap_alert_id=alert.id).delete()

            # Reprocess intersections with enhanced logic
            process_intersections_enhanced(alert)

            # Count new intersections
            new_intersections = Intersection.query.filter_by(cap_alert_id=alert.id).count()
            total_intersections += new_intersections
            total_processed += 1

        db.session.commit()

        log_entry = SystemLog(
            level='INFO',
            message=f'Recalculated intersections for {total_processed} alerts, created {total_intersections} intersection records',
            module='admin'
        )
        db.session.add(log_entry)
        db.session.commit()

        return jsonify({
            'success': f'Recalculated intersections for {total_processed} alerts',
            'message': f'Created {total_intersections} boundary intersection records'
        })

    except Exception as e:
        db.session.rollback()
        logger.error(f"Error recalculating intersections: {str(e)}")
        return jsonify({'error': f'Failed to recalculate intersections: {str(e)}'}), 500


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
                module='admin'
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
            module='admin'
        )
        db.session.add(log_entry)
        db.session.commit()

        return jsonify({'success': f'Boundary "{boundary_name}" deleted successfully'})

    except Exception as e:
        db.session.rollback()
        logger.error(f"Error deleting boundary {boundary_id}: {str(e)}")
        return jsonify({'error': f'Failed to delete boundary: {str(e)}'}), 500


@app.route('/admin/delete_boundaries_by_type', methods=['DELETE'])
def delete_boundaries_by_type():
    """Delete all boundaries of a specific type"""
    try:
        data = request.get_json()
        boundary_type = data.get('boundary_type')

        if not boundary_type:
            return jsonify({'error': 'Boundary type is required'}), 400

        boundaries = Boundary.query.filter_by(type=boundary_type).all()
        count = len(boundaries)

        if count == 0:
            return jsonify({'message': f'No {boundary_type} boundaries found to delete'})

        for boundary in boundaries:
            db.session.delete(boundary)

        db.session.commit()

        log_entry = SystemLog(
            level='INFO',
            message=f'Deleted all {count} {boundary_type} boundaries',
            module='admin'
        )
        db.session.add(log_entry)
        db.session.commit()

        return jsonify({'success': f'Deleted {count} {boundary_type} boundaries'})

    except Exception as e:
        db.session.rollback()
        logger.error(f"Error deleting boundaries by type: {str(e)}")
        return jsonify({'error': f'Failed to delete boundaries: {str(e)}'}), 500


@app.route('/admin/clear_all_boundaries', methods=['DELETE'])
def clear_all_boundaries():
    """Delete ALL boundaries from the system"""
    try:
        count = Boundary.query.count()

        if count == 0:
            return jsonify({'message': 'No boundaries found to delete'})

        db.session.execute(text('DELETE FROM boundaries'))
        db.session.commit()

        log_entry = SystemLog(
            level='WARNING',
            message=f'Cleared ALL {count} boundaries from system',
            module='admin'
        )
        db.session.add(log_entry)
        db.session.commit()

        return jsonify({'success': f'Cleared all {count} boundaries from the system'})

    except Exception as e:
        db.session.rollback()
        logger.error(f"Error clearing all boundaries: {str(e)}")
        return jsonify({'error': f'Failed to clear boundaries: {str(e)}'}), 500


@app.route('/admin/trigger_poll', methods=['POST'])
def trigger_poll():
    """Manually trigger CAP alert polling"""
    try:
        log_entry = SystemLog(
            level='INFO',
            message='Manual CAP poll triggered',
            module='admin'
        )
        db.session.add(log_entry)
        db.session.commit()

        return jsonify({'message': 'CAP poll triggered successfully'})
    except Exception as e:
        logger.error(f"Error triggering poll: {str(e)}")
        return jsonify({'error': str(e)}), 500


@app.route('/admin/clear_expired', methods=['POST'])
def clear_expired():
    """Clear expired alerts from database"""
    try:
        now = datetime.utcnow()
        expired_alerts = CAPAlert.query.filter(CAPAlert.expires < now).all()
        count = len(expired_alerts)

        for alert in expired_alerts:
            db.session.delete(alert)

        db.session.commit()

        log_entry = SystemLog(
            level='INFO',
            message=f'Cleared {count} expired alerts',
            module='admin'
        )
        db.session.add(log_entry)
        db.session.commit()

        return jsonify({'message': f'Cleared {count} expired alerts'})
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error clearing expired alerts: {str(e)}")
        return jsonify({'error': str(e)}), 500


@app.route('/admin/optimize_db', methods=['POST'])
def optimize_db():
    """Run database optimization"""
    try:
        db.session.execute(text('VACUUM ANALYZE'))
        db.session.commit()

        log_entry = SystemLog(
            level='INFO',
            message='Database optimization completed',
            module='admin'
        )
        db.session.add(log_entry)
        db.session.commit()

        return jsonify({'message': 'Database optimization completed'})
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error optimizing database: {str(e)}")
        return jsonify({'error': str(e)}), 500


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