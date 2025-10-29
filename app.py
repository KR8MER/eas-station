#!/usr/bin/env python3
"""
NOAA CAP Alerts and GIS Boundary Mapping System
Flask Web Application with Enhanced Boundary Management and Alerts History

Author: KR8MER Amateur Radio Emergency Communications
Description: Emergency alert system with configurable U.S. jurisdiction support and proper timezone handling
Version: 2.1.7 - Removes legacy artifacts and unused assets from the repository
"""

# =============================================================================
# IMPORTS AND DEPENDENCIES
# =============================================================================

import base64
import os
import json
import re
import psutil
from typing import Any, Dict, List, Optional, Tuple, Union
from datetime import datetime, timedelta, timezone
from collections import defaultdict
from urllib.parse import quote, urljoin, urlparse
from types import SimpleNamespace

from dotenv import load_dotenv
import requests
import pytz

# Application utilities
from app_utils import (
    UTC_TZ,
    build_system_health_snapshot,
    format_bytes,
    format_local_date,
    format_local_datetime,
    format_local_time,
    format_uptime,
    get_location_timezone,
    get_location_timezone_name,
    is_alert_expired,
    local_now,
    parse_nws_datetime as _parse_nws_datetime,
    set_location_timezone,
    utc_now,
)
from app_utils.eas import (
    P_DIGIT_MEANINGS,
    EASAudioGenerator,
    ORIGINATOR_DESCRIPTIONS,
    PRIMARY_ORIGINATORS,
    SAME_HEADER_FIELD_DESCRIPTIONS,
    build_same_header,
    describe_same_header,
    load_eas_config,
    manual_default_same_codes,
    samples_to_wav_bytes,
)
from app_utils.event_codes import EVENT_CODE_REGISTRY
from app_utils.fips_codes import get_same_lookup, get_us_state_county_tree

# Flask and extensions
from flask import (
    Flask,
    request,
    jsonify,
    render_template,
    flash,
    redirect,
    url_for,
    render_template_string,
    has_app_context,
    session,
    g,
)
from geoalchemy2.functions import ST_GeomFromGeoJSON, ST_Intersects, ST_AsGeoJSON
from sqlalchemy import text, func, or_, desc
from sqlalchemy.exc import OperationalError

# Logging
import logging
import click

from app_core.alerts import (
    assign_alert_geometry,
    calculate_alert_intersections,
    ensure_multipolygon,
    get_active_alerts_query,
    get_expired_alerts_query,
    parse_noaa_cap_alert,
)
from app_core.boundaries import (
    BOUNDARY_GROUP_LABELS,
    BOUNDARY_TYPE_CONFIG,
    calculate_geometry_length_miles,
    describe_mtfcc,
    extract_name_and_description,
    get_boundary_color,
    get_boundary_display_label,
    get_boundary_group,
    get_field_mappings,
    normalize_boundary_type,
)
from app_core.extensions import db
from app_core.led import (
    Color,
    Effect,
    DisplayMode,
    Font,
    FontSize,
    LED_AVAILABLE,
    LED_SIGN_IP,
    LED_SIGN_PORT,
    MessagePriority,
    SpecialFunction,
    Speed,
    ensure_led_tables,
    initialise_led_controller,
    led_controller,
    led_module,
)
from app_core.location import get_location_settings, update_location_settings
from app_core.models import (
    AdminUser,
    Boundary,
    CAPAlert,
    EASMessage,
    Intersection,
    LEDMessage,
    LEDSignStatus,
    LocationSettings,
    PollHistory,
    SystemLog,
)

# =============================================================================
# CONFIGURATION AND SETUP
# =============================================================================

# Load environment variables early for local CLI usage
load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Create Flask app
app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'dev-key-change-in-production')

# Application versioning (exposed via templates for quick deployment verification)
SYSTEM_VERSION = os.environ.get('APP_BUILD_VERSION', '2.1.7')

# NOAA API configuration for manual alert import workflows
NOAA_API_BASE_URL = 'https://api.weather.gov/alerts'
# Allowed query parameters documented at
# https://www.weather.gov/documentation/services-web-api#/default/get_alerts
NOAA_ALLOWED_QUERY_PARAMS = frozenset({
    'area',
    'zone',
    'region',
    'region_type',
    'point',
    'start',
    'end',
    'event',
    'status',
    'message_type',
    'urgency',
    'severity',
    'certainty',
    'limit',
    'cursor',
})
NOAA_USER_AGENT = os.environ.get(
    'NOAA_USER_AGENT',
    'KR8MER CAP Alert System/2.1 (+https://github.com/KR8MER/noaa_alerts_systems)'
)


def _build_database_url() -> str:
    url = os.getenv('DATABASE_URL')
    if url:
        return url

    user = os.getenv('POSTGRES_USER', 'postgres') or 'postgres'
    password = os.getenv('POSTGRES_PASSWORD', '')
    host = os.getenv('POSTGRES_HOST', 'postgres') or 'postgres'
    port = os.getenv('POSTGRES_PORT', '5432') or '5432'
    database = os.getenv('POSTGRES_DB', user) or user

    user_part = quote(user, safe='')
    if password:
        auth_part = f"{user_part}:{quote(password, safe='')}"
    else:
        auth_part = user_part

    return f"postgresql+psycopg2://{auth_part}@{host}:{port}/{database}"


# Database configuration
DATABASE_URL = _build_database_url()
os.environ.setdefault('DATABASE_URL', DATABASE_URL)
app.config['SQLALCHEMY_DATABASE_URI'] = DATABASE_URL
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Initialize database
db.init_app(app)

# Configure EAS output integration
EAS_CONFIG = load_eas_config(app.root_path)
app.config['EAS_BROADCAST_ENABLED'] = bool(EAS_CONFIG.get('enabled'))
app.config['EAS_OUTPUT_DIR'] = EAS_CONFIG.get('output_dir')
app.config['EAS_OUTPUT_WEB_SUBDIR'] = EAS_CONFIG.get('web_subdir', 'eas_messages')

# Guard database schema preparation so we only attempt it once per process.
_db_initialized = False
_db_initialization_error = None
logger.info("NOAA Alerts System startup")

# =============================================================================
# BOUNDARY TYPE METADATA
# =============================================================================

USERNAME_PATTERN = re.compile(r'^[A-Za-z0-9_.-]{3,64}$')

# =============================================================================
# TIMEZONE AND DATETIME UTILITIES
# =============================================================================


def parse_nws_datetime(dt_string):
    """Parse NWS datetime strings while reusing the shared utility logger."""

    return _parse_nws_datetime(dt_string, logger=logger)



# =============================================================================
# SYSTEM MONITORING UTILITIES
# =============================================================================


def get_system_health():
    """Get comprehensive system health information."""

    return build_system_health_snapshot(db, logger)


def _led_enums_available() -> bool:
    return all(enum is not None for enum in (Color, Font, DisplayMode, Speed))


# =============================================================================
# TEMPLATE FILTERS AND GLOBALS
# =============================================================================

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


# =============================================================================
# MAIN PAGE ROUTES
# =============================================================================

@app.route('/')
def index():
    """Main dashboard with interactive map"""
    try:
        return render_template('index.html')
    except Exception as e:
        logger.error(f"Error rendering index template: {str(e)}")
        return f"<h1>NOAA CAP Alerts System</h1><p>Map interface loading...</p><p><a href='/stats'>📊 Statistics</a> | <a href='/alerts'>📝 Alerts History</a> | <a href='/admin'>⚙️ Admin</a></p>"


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

        # Alert analytics dataset for interactive dashboard features
        try:
            now = utc_now()
            year_ago = now - timedelta(days=365)

            alert_rows = db.session.query(
                CAPAlert.identifier,
                CAPAlert.sent,
                CAPAlert.expires,
                CAPAlert.severity,
                CAPAlert.status,
                CAPAlert.event
            ).filter(
                CAPAlert.sent.isnot(None),
                CAPAlert.sent >= year_ago
            ).order_by(CAPAlert.sent).all()

            def _ensure_local(dt):
                if dt is None:
                    return None
                if dt.tzinfo is None:
                    dt = UTC_TZ.localize(dt)
                return dt.astimezone(get_location_timezone())

            alert_events = []
            severity_set = set()
            status_set = set()
            event_set = set()
            dow_hour_matrix = [[0] * 24 for _ in range(7)]
            daily_counts = defaultdict(int)
            timeline_rows = []

            for identifier, sent, expires, severity, status, event in alert_rows:
                local_sent = _ensure_local(sent)
                if local_sent is None:
                    continue
                local_expires = _ensure_local(expires)

                severity_label = severity or 'Unknown'
                status_label = status or 'Unknown'
                event_label = event or 'Unknown'

                severity_set.add(severity_label)
                status_set.add(status_label)
                event_set.add(event_label)

                dow_index = (local_sent.weekday() + 1) % 7
                dow_hour_matrix[dow_index][local_sent.hour] += 1
                daily_counts[local_sent.date()] += 1

                alert_events.append({
                    'id': identifier,
                    'sent': local_sent.isoformat(),
                    'expires': local_expires.isoformat() if local_expires else None,
                    'severity': severity_label,
                    'status': status_label,
                    'event': event_label
                })

                timeline_rows.append((
                    identifier,
                    event_label,
                    severity_label,
                    status_label,
                    local_sent,
                    local_expires
                ))

            timeline_rows.sort(key=lambda row: row[4], reverse=True)
            stats_data['lifecycle_timeline'] = [
                {
                    'id': row[0],
                    'event': row[1],
                    'severity': row[2],
                    'status': row[3],
                    'start': row[4].isoformat(),
                    'end': row[5].isoformat() if row[5] else None,
                    'duration_hours': round(((row[5] - row[4]).total_seconds() / 3600), 2) if row[5] else None
                }
                for row in timeline_rows[:30]
            ]
            stats_data['alert_events'] = alert_events
            stats_data['filter_options'] = {
                'severities': sorted(severity_set),
                'statuses': sorted(status_set),
                'events': sorted(event_set)
            }
            stats_data['dow_hour_matrix'] = dow_hour_matrix
            stats_data['daily_alerts'] = [
                {'date': date.isoformat(), 'count': count}
                for date, count in sorted(daily_counts.items())
            ]
        except Exception as e:
            logger.error(f"Error preparing analytics dataset: {str(e)}")
            stats_data.setdefault('lifecycle_timeline', [])
            stats_data.setdefault('alert_events', [])
            stats_data.setdefault('filter_options', {
                'severities': [],
                'statuses': [],
                'events': []
            })
            stats_data.setdefault('dow_hour_matrix', [[0] * 24 for _ in range(7)])
            stats_data.setdefault('daily_alerts', [])

        # Add utility functions to template context
        stats_data['format_bytes'] = format_bytes
        stats_data['format_uptime'] = format_uptime

        return render_template('stats.html', **stats_data)

    except Exception as e:
        logger.error(f"Error loading statistics: {str(e)}")
        return f"<h1>Error loading statistics</h1><p>{str(e)}</p><p><a href='/'>← Back to Main</a></p>"


@app.route('/about')
def about_page():
    """Present project background information within the web UI."""
    try:
        return render_template('about.html')
    except Exception as exc:
        logger.error(f"Error rendering about page: {exc}")
        return (
            "<h1>About</h1><p>Project documentation is available in ABOUT.md on the server.</p>"
        )


@app.route('/help')
def help_page():
    """Provide quick-start and troubleshooting guidance for operators."""
    try:
        return render_template('help.html')
    except Exception as exc:
        logger.error(f"Error rendering help page: {exc}")
        return (
            "<h1>Help</h1><p>Refer to HELP.md in the repository for the full operations guide.</p>"
        )


@app.route('/system_health')
def system_health_page():
    """Dedicated system health monitoring page"""
    try:
        health_data = get_system_health()
        template_context = dict(health_data)
        template_context['format_bytes'] = format_bytes
        template_context['format_uptime'] = format_uptime
        template_context['health_data_json'] = json.dumps(health_data)
        return render_template('system_health.html', **template_context)
    except Exception as e:
        logger.error(f"Error loading system health page: {str(e)}")
        return f"<h1>Error loading system health</h1><p>{str(e)}</p><p><a href='/'>← Back to Main</a></p>"


# =============================================================================
# ALERT MANAGEMENT ROUTES
# =============================================================================

@app.route('/alerts')
def alerts():
    """Alerts history page - list all alerts"""
    try:
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 25, type=int)
        per_page = min(max(per_page, 10), 100)

        search = request.args.get('search', '').strip()
        status_filter = request.args.get('status', '').strip()
        severity_filter = request.args.get('severity', '').strip()
        event_filter = request.args.get('event', '').strip()
        show_expired = request.args.get('show_expired') == 'true'

        query = CAPAlert.query

        if search:
            search_term = f'%{search}%'
            query = query.filter(
                or_(
                    CAPAlert.headline.ilike(search_term),
                    CAPAlert.description.ilike(search_term),
                    CAPAlert.event.ilike(search_term),
                    CAPAlert.area_desc.ilike(search_term)
                )
            )

        if status_filter:
            query = query.filter(CAPAlert.status == status_filter)
        if severity_filter:
            query = query.filter(CAPAlert.severity == severity_filter)
        if event_filter:
            query = query.filter(CAPAlert.event == event_filter)

        if not show_expired:
            query = query.filter(
                or_(
                    CAPAlert.expires.is_(None),
                    CAPAlert.expires > utc_now()
                )
            ).filter(CAPAlert.status != 'Expired')

        query = query.order_by(CAPAlert.sent.desc())

        try:
            pagination = query.paginate(
                page=page,
                per_page=per_page,
                error_out=False
            )
            alerts_list = pagination.items

        except Exception as paginate_error:
            logger.warning(f"Pagination error: {str(paginate_error)}")

            total_count = query.count()
            offset = (page - 1) * per_page
            alerts_list = query.offset(offset).limit(per_page).all()

            class MockPagination:
                def __init__(self, page, per_page, total, items):
                    self.page = page
                    self.per_page = per_page
                    self.total = total
                    self.items = items
                    self.pages = (total + per_page - 1) // per_page if per_page > 0 else 1
                    self.has_prev = page > 1
                    self.has_next = page < self.pages
                    self.prev_num = page - 1 if self.has_prev else None
                    self.next_num = page + 1 if self.has_next else None

                def iter_pages(self, left_edge=2, left_current=2, right_current=3, right_edge=2):
                    last = self.pages
                    for num in range(1, last + 1):
                        if num <= left_edge or \
                                (self.page - left_current - 1 < num < self.page + right_current) or \
                                num > last - right_edge:
                            yield num
                        elif num == left_edge + 1 or num == self.page + right_current:
                            yield None

            pagination = MockPagination(page, per_page, total_count, alerts_list)

        try:
            total_alerts = CAPAlert.query.count()
            active_alerts = get_active_alerts_query().count()
            expired_alerts = get_expired_alerts_query().count()
        except Exception as stats_error:
            logger.warning(f"Error getting stats: {str(stats_error)}")
            total_alerts = 0
            active_alerts = 0
            expired_alerts = 0

        try:
            statuses = db.session.query(CAPAlert.status).distinct().order_by(CAPAlert.status).all()
            statuses = [s[0] for s in statuses if s[0]]

            severities = db.session.query(CAPAlert.severity).filter(
                CAPAlert.severity.isnot(None)
            ).distinct().order_by(CAPAlert.severity).all()
            severities = [s[0] for s in severities if s[0]]

            events = db.session.query(CAPAlert.event).distinct().order_by(CAPAlert.event).limit(50).all()
            events = [e[0] for e in events if e[0]]

        except Exception as filter_error:
            logger.warning(f"Error getting filter options: {str(filter_error)}")
            statuses = []
            severities = []
            events = []

        current_filters = {
            'search': search,
            'status': status_filter,
            'severity': severity_filter,
            'event': event_filter,
            'per_page': per_page,
            'show_expired': show_expired
        }

        return render_template('alerts.html',
                               alerts=alerts_list,
                               pagination=pagination,
                               total_alerts=total_alerts,
                               active_alerts=active_alerts,
                               expired_alerts=expired_alerts,
                               statuses=statuses,
                               severities=severities,
                               events=events,
                               current_filters=current_filters)

    except Exception as e:
        logger.error(f"Error loading alerts page: {str(e)}")
        import traceback
        logger.error(f"Full traceback: {traceback.format_exc()}")

        return render_template_string("""
        <h1>Error Loading Alerts</h1>
        <div class="alert alert-danger">
            <strong>Error:</strong> {{ error }}
        </div>
        <p><a href="/" class="btn btn-primary">← Back to Main</a></p>
        {% if debug %}
        <details class="mt-3">
            <summary>Debug Information</summary>
            <pre>{{ debug }}</pre>
        </details>
        {% endif %}
        """, error=str(e), debug=traceback.format_exc() if app.debug else None)

@app.route('/api/alerts/<int:alert_id>/geometry')
def get_alert_geometry(alert_id):
    """Get specific alert geometry and intersecting boundaries as GeoJSON"""
    try:
        # Get the alert with geometry
        alert = db.session.query(
            CAPAlert.id, CAPAlert.identifier, CAPAlert.event, CAPAlert.severity,
            CAPAlert.urgency, CAPAlert.headline, CAPAlert.description, CAPAlert.expires,
            CAPAlert.sent, CAPAlert.area_desc, CAPAlert.status,
            func.ST_AsGeoJSON(CAPAlert.geom).label('geometry')
        ).filter(CAPAlert.id == alert_id).first()

        if not alert:
            return jsonify({'error': 'Alert not found'}), 404

        # Get county boundary for fallback
        county_boundary = None
        try:
            county_geom = db.session.query(
                func.ST_AsGeoJSON(Boundary.geom).label('geometry')
            ).filter(Boundary.type == 'county').first()

            if county_geom and county_geom.geometry:
                county_boundary = json.loads(county_geom.geometry)
        except Exception as e:
            logger.warning(f"Could not get county boundary: {str(e)}")

        # Determine geometry and county-wide status
        geometry = None
        is_county_wide = False

        if alert.geometry:
            geometry = json.loads(alert.geometry)
        elif alert.area_desc:
            area_lower = alert.area_desc.lower()
            if any(county_term in area_lower for county_term in ['county', 'putnam', 'ohio']):
                if county_boundary:
                    geometry = county_boundary
                    is_county_wide = True

        # Get intersecting boundaries
        intersecting_boundaries = []
        if geometry:
            intersections = db.session.query(Intersection, Boundary).join(
                Boundary, Intersection.boundary_id == Boundary.id
            ).filter(Intersection.cap_alert_id == alert_id).all()

            # Convert intersecting boundaries to GeoJSON features
            for intersection, boundary in intersections:
                boundary_geom = db.session.query(
                    func.ST_AsGeoJSON(Boundary.geom).label('geometry')
                ).filter(Boundary.id == boundary.id).first()

                if boundary_geom and boundary_geom.geometry:
                    intersecting_boundaries.append({
                        'type': 'Feature',
                        'properties': {
                            'id': boundary.id,
                            'name': boundary.name,
                            'type': boundary.type,
                            'description': boundary.description,
                            'intersection_area': intersection.intersection_area
                        },
                        'geometry': json.loads(boundary_geom.geometry)
                    })

        # Format dates
        expires_iso = None
        if alert.expires:
            if alert.expires.tzinfo is None:
                expires_dt = alert.expires.replace(tzinfo=UTC_TZ)
            else:
                expires_dt = alert.expires.astimezone(UTC_TZ)
            expires_iso = expires_dt.isoformat()

        sent_iso = None
        if alert.sent:
            if alert.sent.tzinfo is None:
                sent_dt = alert.sent.replace(tzinfo=UTC_TZ)
            else:
                sent_dt = alert.sent.astimezone(UTC_TZ)
            sent_iso = sent_dt.isoformat()

        # Build response
        response_data = {
            'alert': {
                'type': 'Feature',
                'properties': {
                    'id': alert.id,
                    'identifier': alert.identifier,
                    'event': alert.event,
                    'severity': alert.severity,
                    'urgency': alert.urgency,
                    'headline': alert.headline,
                    'description': alert.description,
                    'sent': sent_iso,
                    'expires': expires_iso,
                    'area_desc': alert.area_desc,
                    'status': alert.status,
                    'is_county_wide': is_county_wide
                },
                'geometry': geometry
            } if geometry else None,
            'intersecting_boundaries': {
                'type': 'FeatureCollection',
                'features': intersecting_boundaries
            }
        }

        return jsonify(response_data)

    except Exception as e:
        logger.error(f"Error getting alert geometry: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/alerts/<int:alert_id>')
def alert_detail(alert_id):
    """Show detailed information about a specific alert with accurate coverage calculation"""
    try:
        alert = CAPAlert.query.get_or_404(alert_id)

        # Get intersections
        intersections = db.session.query(Intersection, Boundary).join(
            Boundary, Intersection.boundary_id == Boundary.id
        ).filter(Intersection.cap_alert_id == alert_id).all()

        # Determine if this should be considered county-wide based on area description
        is_county_wide = False
        if alert.area_desc:
            area_lower = alert.area_desc.lower()
            is_county_wide = (
                'putnam county' in area_lower or
                'entire county' in area_lower or
                ('county' in area_lower and 'ohio' in area_lower) or
                ('putnam' in area_lower and (area_lower.count(';') >= 2 or area_lower.count(',') >= 2))
            )

        # Calculate actual coverage percentages
        coverage_data = calculate_coverage_percentages(alert_id, intersections)

        # Determine actual coverage status
        county_coverage = coverage_data.get('county', {}).get('coverage_percentage', 0)
        is_actually_county_wide = county_coverage >= 95.0  # Consider 95%+ as county-wide

        return render_template('alert_detail.html',
                             alert=alert,
                             intersections=intersections,
                             is_county_wide=is_county_wide,
                             is_actually_county_wide=is_actually_county_wide,
                             coverage_data=coverage_data)

    except Exception as e:
        logger.error(f"Error in alert_detail route: {str(e)}")
        flash(f'Error loading alert details: {str(e)}', 'error')
        return redirect(url_for('index'))


# =============================================================================
# API ROUTES
# =============================================================================

@app.route('/api/alerts')
def get_alerts():
    """Get CAP alerts as GeoJSON with optional inclusion of expired alerts"""
    try:
        # Check if we should include expired alerts
        include_expired = request.args.get('include_expired', 'false').lower() == 'true'

        # Use different query based on whether expired alerts are requested
        if include_expired:
            # Get ALL alerts (active and expired)
            alerts_query = CAPAlert.query
            logger.info("Including expired alerts in API response")
        else:
            # Get only active alerts (existing behavior)
            alerts_query = get_active_alerts_query()
            logger.info("Including only active alerts in API response")

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

            # Check if this should be marked as county-wide based on area description
            if not is_county_wide and alert.area_desc:
                area_lower = alert.area_desc.lower()

                # Multi-county alerts that include the configured county should be treated as county-wide
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
                        'description': alert.description[:500] + '...' if len(
                            alert.description) > 500 else alert.description,
                        'area_desc': alert.area_desc,
                        'expires_iso': expires_iso,
                        'is_county_wide': is_county_wide,
                        'is_expired': is_alert_expired(alert.expires)  # Add expiration status
                    },
                    'geometry': geometry
                })

        logger.info(f"Returning {len(features)} alerts (include_expired={include_expired})")

        return jsonify({
            'type': 'FeatureCollection',
            'features': features,
            'metadata': {
                'total_features': len(features),
                'include_expired': include_expired,
                'generated_at': utc_now().isoformat()
            }
        })

    except Exception as e:
        logger.error(f"Error getting alerts: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/alerts/historical')
def get_historical_alerts():
    """Get historical alerts as GeoJSON with date filtering"""
    try:
        # Get query parameters
        start_date = request.args.get('start_date')
        end_date = request.args.get('end_date')
        include_active = request.args.get('include_active', 'false').lower() == 'true'

        # Base query - all alerts or just expired
        if include_active:
            query = CAPAlert.query
        else:
            query = get_expired_alerts_query()

        # Apply date filters
        if start_date:
            start_dt = datetime.fromisoformat(start_date).replace(tzinfo=UTC_TZ)
            query = query.filter(CAPAlert.sent >= start_dt)

        if end_date:
            end_dt = datetime.fromisoformat(end_date).replace(tzinfo=UTC_TZ)
            query = query.filter(CAPAlert.sent <= end_dt)

        # Get alerts with geometry
        alerts = db.session.query(
            CAPAlert.id, CAPAlert.identifier, CAPAlert.event, CAPAlert.severity,
            CAPAlert.urgency, CAPAlert.headline, CAPAlert.description, CAPAlert.expires,
            CAPAlert.sent, CAPAlert.area_desc, func.ST_AsGeoJSON(CAPAlert.geom).label('geometry')
        ).filter(
            CAPAlert.id.in_(query.with_entities(CAPAlert.id).subquery())
        ).all()

        # Get county boundary for fallback
        county_boundary = None
        try:
            county_geom = db.session.query(
                func.ST_AsGeoJSON(Boundary.geom).label('geometry')
            ).filter(Boundary.type == 'county').first()

            if county_geom and county_geom.geometry:
                county_boundary = json.loads(county_geom.geometry)
        except Exception as e:
            logger.warning(f"Could not get county boundary: {str(e)}")

        # Build GeoJSON features
        features = []
        for alert in alerts:
            geometry = None
            is_county_wide = False

            if alert.geometry:
                geometry = json.loads(alert.geometry)
            elif alert.area_desc and any(county_term in alert.area_desc.lower()
                                         for county_term in ['county', 'putnam', 'ohio']):
                if county_boundary:
                    geometry = county_boundary
                    is_county_wide = True

            if geometry:
                expires_iso = None
                if alert.expires:
                    if alert.expires.tzinfo is None:
                        expires_dt = alert.expires.replace(tzinfo=UTC_TZ)
                    else:
                        expires_dt = alert.expires.astimezone(UTC_TZ)
                    expires_iso = expires_dt.isoformat()

                sent_iso = None
                if alert.sent:
                    if alert.sent.tzinfo is None:
                        sent_dt = alert.sent.replace(tzinfo=UTC_TZ)
                    else:
                        sent_dt = alert.sent.astimezone(UTC_TZ)
                    sent_iso = sent_dt.isoformat()

                features.append({
                    'type': 'Feature',
                    'properties': {
                        'id': alert.id,
                        'identifier': alert.identifier,
                        'event': alert.event,
                        'severity': alert.severity,
                        'urgency': alert.urgency,
                        'headline': alert.headline,
                        'description': alert.description[:500] + '...' if len(
                            alert.description) > 500 else alert.description,
                        'sent': sent_iso,
                        'expires': expires_iso,
                        'area_desc': alert.area_desc,
                        'is_historical': True,
                        'is_county_wide': is_county_wide
                    },
                    'geometry': geometry
                })

        return jsonify({
            'type': 'FeatureCollection',
            'features': features
        })

    except Exception as e:
        logger.error(f"Error getting historical alerts: {str(e)}")
        return jsonify({'error': str(e)}), 500

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
            normalized_type = normalize_boundary_type(boundary_type)
            query = query.filter(func.lower(Boundary.type) == normalized_type)

        if search:
            query = query.filter(Boundary.name.ilike(f'%{search}%'))

        boundaries = query.paginate(
            page=page, per_page=per_page, error_out=False
        ).items

        features = []
        for boundary in boundaries:
            if boundary.geometry:
                normalized_type = normalize_boundary_type(boundary.type)
                features.append({
                    'type': 'Feature',
                    'properties': {
                        'id': boundary.id,
                        'name': boundary.name,
                        'type': normalized_type,
                        'raw_type': boundary.type,
                        'display_type': get_boundary_display_label(boundary.type),
                        'group': get_boundary_group(boundary.type),
                        'color': get_boundary_color(boundary.type),
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

        location_tz = get_location_timezone()
        return jsonify({
            'status': 'online',
            'timestamp': current_utc.isoformat(),
            'local_timestamp': current_local.isoformat(),
            'timezone': get_location_timezone_name(),
            'boundaries_count': total_boundaries,
            'active_alerts_count': active_alerts,
            'database_status': 'connected',
            'last_poll': {
                'timestamp': last_poll.timestamp.isoformat() if last_poll else None,
                'local_timestamp': last_poll.timestamp.astimezone(location_tz).isoformat() if last_poll else None,
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


# =============================================================================
# ADMINISTRATIVE ROUTES
# =============================================================================

# =============================================================================
# AUTHENTICATION ROUTES
# =============================================================================


def _is_safe_redirect_target(target: Optional[str]) -> bool:
    if not target:
        return False
    ref_url = urlparse(request.host_url)
    test_url = urlparse(urljoin(request.host_url, target))
    return (
        test_url.scheme in ('http', 'https')
        and ref_url.netloc == test_url.netloc
    )


@app.route('/login', methods=['GET', 'POST'])
def login():
    next_param = request.args.get('next') if request.method == 'GET' else request.form.get('next')
    if g.current_user:
        target = next_param if _is_safe_redirect_target(next_param) else url_for('admin')
        return redirect(target)

    error = None
    if request.method == 'POST':
        username = (request.form.get('username') or '').strip()
        password = request.form.get('password') or ''

        if not username or not password:
            error = 'Username and password are required.'
        else:
            user = AdminUser.query.filter(
                func.lower(AdminUser.username) == username.lower()
            ).first()
            if user and user.is_active and user.check_password(password):
                session['user_id'] = user.id
                session.permanent = True
                user.last_login_at = utc_now()
                log_entry = SystemLog(
                    level='INFO',
                    message='Administrator logged in',
                    module='auth',
                    details={
                        'username': user.username,
                        'remote_addr': request.remote_addr,
                    },
                )
                db.session.add(user)
                db.session.add(log_entry)
                db.session.commit()

                target = next_param if _is_safe_redirect_target(next_param) else url_for('admin')
                return redirect(target)

            db.session.add(SystemLog(
                level='WARNING',
                message='Failed administrator login attempt',
                module='auth',
                details={
                    'username': username,
                    'remote_addr': request.remote_addr,
                },
            ))
            db.session.commit()
            error = 'Invalid username or password.'

    show_setup = AdminUser.query.count() == 0

    return render_template(
        'login.html',
        error=error,
        next=next_param or url_for('admin'),
        show_setup=show_setup,
    )


@app.route('/logout')
def logout():
    user = g.current_user
    if user:
        db.session.add(SystemLog(
            level='INFO',
            message='Administrator logged out',
            module='auth',
            details={
                'username': user.username,
                'remote_addr': request.remote_addr,
            },
        ))
        db.session.commit()
    session.pop('user_id', None)
    flash('You have been signed out.')
    return redirect(url_for('login'))


@app.route('/admin')
def admin():
    """Admin interface"""
    try:
        setup_mode = getattr(g, 'admin_setup_mode', None)
        if setup_mode is None:
            setup_mode = AdminUser.query.count() == 0
        total_boundaries = Boundary.query.count()
        total_alerts = CAPAlert.query.count()
        active_alerts = get_active_alerts_query().count()
        expired_alerts = get_expired_alerts_query().count()

        boundary_stats = db.session.query(
            Boundary.type, func.count(Boundary.id).label('count')
        ).group_by(Boundary.type).all()

        location_settings = get_location_settings()
        manual_same_defaults = manual_default_same_codes()
        location_settings_view = dict(location_settings)
        location_settings_view.setdefault('same_codes', manual_same_defaults)

        eas_enabled = app.config.get('EAS_BROADCAST_ENABLED', False)
        total_eas_messages = EASMessage.query.count() if eas_enabled else 0
        recent_eas_messages = []
        if eas_enabled:
            recent_eas_messages = (
                EASMessage.query.order_by(EASMessage.created_at.desc()).limit(10).all()
            )

        eas_event_options = [
            {'code': code, 'name': entry.get('name', code)}
            for code, entry in EVENT_CODE_REGISTRY.items()
            if '?' not in code
        ]
        eas_event_options.sort(key=lambda item: item['code'])

        eas_state_tree = get_us_state_county_tree()
        eas_lookup = get_same_lookup()
        originator_choices = [
            {
                'code': code,
                'description': ORIGINATOR_DESCRIPTIONS.get(code, ''),
            }
            for code in PRIMARY_ORIGINATORS
        ]

        return render_template('admin.html',
                               total_boundaries=total_boundaries,
                               total_alerts=total_alerts,
                               active_alerts=active_alerts,
                               expired_alerts=expired_alerts,
                               boundary_stats=boundary_stats,
                               location_settings=location_settings_view,
                               eas_enabled=eas_enabled,
                               eas_total_messages=total_eas_messages,
                               eas_recent_messages=recent_eas_messages,
                               eas_web_subdir=app.config.get('EAS_OUTPUT_WEB_SUBDIR', 'eas_messages'),
                               eas_event_codes=eas_event_options,
                               eas_originator=EAS_CONFIG.get('originator', 'WXR'),
                               eas_station_id=EAS_CONFIG.get('station_id', 'EASNODES'),
                               eas_attention_seconds=EAS_CONFIG.get('attention_tone_seconds', 8),
                               eas_sample_rate=EAS_CONFIG.get('sample_rate', 44100),
                               eas_tts_provider=(EAS_CONFIG.get('tts_provider') or '').strip().lower(),
                               eas_fips_states=eas_state_tree,
                               eas_fips_lookup=eas_lookup,
                               eas_originator_descriptions=ORIGINATOR_DESCRIPTIONS,
                               eas_originator_choices=originator_choices,
                               eas_header_fields=SAME_HEADER_FIELD_DESCRIPTIONS,
                               eas_p_digit_meanings=P_DIGIT_MEANINGS,
                               eas_default_same_codes=manual_same_defaults,
                               setup_mode=setup_mode,
                               )
    except Exception as e:
        logger.error(f"Error rendering admin template: {str(e)}")
        return f"<h1>Admin Interface</h1><p>Admin panel loading...</p><p><a href='/'>← Back to Main</a></p>"


@app.route('/admin/users', methods=['GET', 'POST'])
def admin_users():
    if request.method == 'GET':
        users = AdminUser.query.order_by(AdminUser.username.asc()).all()
        return jsonify({'users': [user.to_safe_dict() for user in users]})

    payload = request.get_json(silent=True) or {}
    username = (payload.get('username') or '').strip()
    password = payload.get('password') or ''

    creating_first_user = AdminUser.query.count() == 0
    if g.current_user is None and not creating_first_user:
        return jsonify({'error': 'Authentication required.'}), 401

    if not username or not password:
        return jsonify({'error': 'Username and password are required.'}), 400

    if not USERNAME_PATTERN.match(username):
        return jsonify({'error': 'Usernames must be 3-64 characters and may include letters, numbers, dots, underscores, and hyphens.'}), 400

    if len(password) < 8:
        return jsonify({'error': 'Password must be at least 8 characters long.'}), 400

    existing = AdminUser.query.filter(func.lower(AdminUser.username) == username.lower()).first()
    if existing:
        return jsonify({'error': 'Username already exists.'}), 400

    new_user = AdminUser(username=username)
    new_user.set_password(password)
    db.session.add(new_user)
    db.session.add(SystemLog(
        level='INFO',
        message='Administrator account created',
        module='auth',
        details={
            'username': new_user.username,
            'created_by': g.current_user.username if g.current_user else 'initial_setup',
        },
    ))
    db.session.commit()

    return jsonify({'message': 'User created successfully.', 'user': new_user.to_safe_dict()}), 201


@app.route('/admin/users/<int:user_id>', methods=['PATCH', 'DELETE'])
def admin_user_detail(user_id: int):
    user = AdminUser.query.get_or_404(user_id)

    if request.method == 'PATCH':
        payload = request.get_json(silent=True) or {}
        password = payload.get('password') or ''
        if len(password) < 8:
            return jsonify({'error': 'Password must be at least 8 characters long.'}), 400

        user.set_password(password)
        db.session.add(user)
        db.session.add(SystemLog(
            level='INFO',
            message='Administrator password reset',
            module='auth',
            details={
                'username': user.username,
                'updated_by': g.current_user.username if g.current_user else None,
            },
        ))
        db.session.commit()
        return jsonify({'message': 'Password updated successfully.', 'user': user.to_safe_dict()})

    if user.id == getattr(g.current_user, 'id', None):
        return jsonify({'error': 'You cannot delete your own account while logged in.'}), 400

    active_users = AdminUser.query.filter(AdminUser.is_active.is_(True)).count()
    if user.is_active and active_users <= 1:
        return jsonify({'error': 'At least one active administrator account is required.'}), 400

    db.session.delete(user)
    db.session.add(SystemLog(
        level='WARNING',
        message='Administrator account deleted',
        module='auth',
        details={
            'username': user.username,
            'deleted_by': g.current_user.username if g.current_user else None,
        },
    ))
    db.session.commit()
    return jsonify({'message': 'User deleted successfully.'})


@app.route('/admin/eas_messages', methods=['GET'])
def admin_eas_messages():
    if not app.config.get('EAS_BROADCAST_ENABLED', False):
        return jsonify({'messages': [], 'total': 0})

    try:
        limit = request.args.get('limit', type=int) or 50
        limit = min(max(limit, 1), 500)
        base_query = EASMessage.query.order_by(EASMessage.created_at.desc())
        messages = base_query.limit(limit).all()
        total = base_query.count()

        static_prefix = app.config.get('EAS_OUTPUT_WEB_SUBDIR', 'eas_messages').strip('/')
        items = []
        for message in messages:
            data = message.to_dict()
            audio_path = '/'.join(part for part in [static_prefix, message.audio_filename] if part)
            text_path = '/'.join(part for part in [static_prefix, message.text_filename] if part)
            items.append({
                **data,
                'audio_url': url_for('static', filename=audio_path),
                'text_url': url_for('static', filename=text_path),
            })

        return jsonify({'messages': items, 'total': total})
    except Exception as exc:
        logger.error(f"Failed to list EAS messages: {exc}")
        return jsonify({'error': 'Unable to load EAS messages'}), 500


@app.route('/admin/eas/manual_generate', methods=['POST'])
def admin_manual_eas_generate():
    creating_first_user = AdminUser.query.count() == 0
    if g.current_user is None and not creating_first_user:
        return jsonify({'error': 'Authentication required.'}), 401

    payload = request.get_json(silent=True) or {}

    def _validation_error(message: str, status: int = 400):
        return jsonify({'error': message}), status

    identifier = (payload.get('identifier') or '').strip()[:120]
    if not identifier:
        identifier = f"MANUAL-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}"

    event_code = (payload.get('event_code') or '').strip().upper()
    if not event_code or len(event_code) != 3 or not event_code.isalnum():
        return _validation_error('Event code must be a three-character SAME identifier.')
    if event_code not in EVENT_CODE_REGISTRY or '?' in event_code:
        return _validation_error('Select a recognised SAME event code.')

    event_name = (payload.get('event_name') or '').strip()
    if not event_name:
        registry_entry = EVENT_CODE_REGISTRY.get(event_code)
        event_name = registry_entry.get('name', event_code) if registry_entry else event_code

    same_input = payload.get('same_codes')
    if isinstance(same_input, str):
        raw_codes = re.split(r'[^0-9]+', same_input)
    elif isinstance(same_input, list):
        raw_codes = []
        for item in same_input:
            if item is None:
                continue
            raw_codes.extend(re.split(r'[^0-9]+', str(item)))
    else:
        raw_codes = []

    location_codes: List[str] = []
    for code in raw_codes:
        digits = ''.join(ch for ch in str(code) if ch.isdigit())
        if not digits:
            continue
        location_codes.append(digits.zfill(6)[:6])

    if not location_codes:
        return _validation_error('At least one SAME/FIPS location code is required.')

    try:
        duration_minutes = float(payload.get('duration_minutes', 15) or 15)
    except (TypeError, ValueError):
        return _validation_error('Duration must be a numeric value representing minutes.')
    if duration_minutes <= 0:
        return _validation_error('Duration must be greater than zero minutes.')

    tone_seconds = payload.get('tone_seconds')
    try:
        tone_seconds = float(tone_seconds) if tone_seconds is not None else None
    except (TypeError, ValueError):
        return _validation_error('Tone duration must be numeric.')

    tone_profile = (payload.get('tone_profile') or 'attention').strip().lower()
    include_tts = bool(payload.get('include_tts', True))

    allowed_originators = set(PRIMARY_ORIGINATORS)
    originator = (payload.get('originator') or EAS_CONFIG.get('originator', 'WXR')).strip().upper() or 'WXR'
    if originator not in allowed_originators:
        return _validation_error('Originator must be one of the authorised SAME senders.')

    station_id = (payload.get('station_id') or EAS_CONFIG.get('station_id', 'EASNODES')).strip() or 'EASNODES'

    status = (payload.get('status') or 'Actual').strip() or 'Actual'
    message_type = (payload.get('message_type') or 'Alert').strip() or 'Alert'

    try:
        sample_rate = int(payload.get('sample_rate') or EAS_CONFIG.get('sample_rate', 44100) or 44100)
    except (TypeError, ValueError):
        return _validation_error('Sample rate must be an integer value.')
    if sample_rate < 8000 or sample_rate > 48000:
        return _validation_error('Sample rate must be between 8000 and 48000 Hz.')

    sent_dt = datetime.now(timezone.utc)
    expires_dt = sent_dt + timedelta(minutes=duration_minutes)

    manual_config = dict(EAS_CONFIG)
    manual_config['enabled'] = True
    manual_config['originator'] = originator[:3].upper()
    manual_config['station_id'] = station_id.upper().ljust(8)[:8]
    manual_config['attention_tone_seconds'] = tone_seconds if tone_seconds is not None else manual_config.get('attention_tone_seconds', 8)
    manual_config['sample_rate'] = sample_rate

    alert_object = SimpleNamespace(
        identifier=identifier,
        event=event_name or event_code,
        headline=(payload.get('headline') or '').strip(),
        description=(payload.get('message') or '').strip(),
        instruction=(payload.get('instruction') or '').strip(),
        sent=sent_dt,
        expires=expires_dt,
        status=status,
        message_type=message_type,
    )

    payload_wrapper: Dict[str, Any] = {
        'identifier': identifier,
        'sent': sent_dt,
        'expires': expires_dt,
        'status': status,
        'message_type': message_type,
        'raw_json': {
            'properties': {
                'geocode': {
                    'SAME': location_codes,
                }
            }
        },
    }

    try:
        header, formatted_locations, resolved_event_code = build_same_header(
            alert_object,
            payload_wrapper,
            manual_config,
            location_settings=None,
        )
        generator = EASAudioGenerator(manual_config, logger)
        components = generator.build_manual_components(
            alert_object,
            header,
            repeats=3,
            tone_profile=tone_profile,
            tone_duration=tone_seconds,
            include_tts=include_tts,
        )
    except Exception as exc:  # pragma: no cover - defensive
        logger.error(f"Failed to build manual EAS package: {exc}")
        return jsonify({'error': 'Unable to generate EAS audio components.'}), 500

    def _safe_base(value: str) -> str:
        cleaned = re.sub(r'[^A-Za-z0-9]+', '_', value).strip('_')
        return cleaned or 'manual_eas'

    base_name = _safe_base(identifier)
    sample_rate = components.get('sample_rate', sample_rate)

    def _package_audio(samples: List[int], suffix: str) -> Optional[Dict[str, Any]]:
        if not samples:
            return None
        wav_bytes = samples_to_wav_bytes(samples, sample_rate)
        data_url = f"data:audio/wav;base64,{base64.b64encode(wav_bytes).decode('ascii')}"
        duration = round(len(samples) / sample_rate, 3)
        return {
            'filename': f"{base_name}_{suffix}.wav",
            'data_url': data_url,
            'duration_seconds': duration,
            'size_bytes': len(wav_bytes),
        }

    state_tree = get_us_state_county_tree()
    state_index = {
        state.get('state_fips'): {'abbr': state.get('abbr'), 'name': state.get('name')}
        for state in state_tree
        if state.get('state_fips')
    }
    same_lookup = get_same_lookup()
    header_detail = describe_same_header(header, lookup=same_lookup, state_index=state_index)

    response_payload: Dict[str, Any] = {
        'identifier': identifier,
        'event_code': resolved_event_code,
        'event_name': event_name,
        'same_header': header,
        'same_locations': formatted_locations,
        'eom_header': components.get('eom_header'),
        'tone_profile': components.get('tone_profile'),
        'tone_seconds': components.get('tone_seconds'),
        'message_text': components.get('message_text'),
        'tts_warning': components.get('tts_warning'),
        'tts_provider': components.get('tts_provider'),
        'duration_minutes': duration_minutes,
        'sent_at': sent_dt.isoformat(),
        'expires_at': expires_dt.isoformat(),
        'components': {
            'same': _package_audio(components.get('same_samples') or [], 'same'),
            'attention': _package_audio(components.get('attention_samples') or [], 'attention'),
            'tts': _package_audio(components.get('tts_samples') or [], 'tts'),
            'eom': _package_audio(components.get('eom_samples') or [], 'eom'),
            'composite': _package_audio(components.get('composite_samples') or [], 'full'),
        },
        'sample_rate': sample_rate,
        'same_header_detail': header_detail,
    }

    try:
        db.session.add(SystemLog(
            level='INFO',
            message='Manual EAS package generated',
            module='admin',
            details={
                'identifier': identifier,
                'event_code': resolved_event_code,
                'location_count': len(formatted_locations),
                'tone_profile': response_payload['tone_profile'],
                'tts_included': bool(response_payload['components']['tts']),
            },
        ))
        db.session.commit()
    except Exception as exc:  # pragma: no cover - logging failures should not break response
        db.session.rollback()
        logger.warning(f"Failed to persist manual EAS generation log: {exc}")

    return jsonify(response_payload)


@app.route('/logs')
def logs():
    """View system logs"""
    try:
        logs = SystemLog.query.order_by(SystemLog.timestamp.desc()).limit(100).all()
        return render_template('logs.html', logs=logs)
    except Exception as e:
        logger.error(f"Error loading logs: {str(e)}")
        return f"<h1>Error loading logs</h1><p>{str(e)}</p><p><a href='/'>← Back to Main</a></p>"


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


@app.route('/admin/location_settings', methods=['GET', 'PUT'])
def admin_location_settings():
    """Retrieve or update the configurable location settings."""
    try:
        if request.method == 'GET':
            settings = get_location_settings()
            return jsonify({'settings': settings})

        payload = request.get_json(silent=True) or {}
        updated = update_location_settings({
            'county_name': payload.get('county_name'),
            'state_code': payload.get('state_code'),
            'timezone': payload.get('timezone'),
            'zone_codes': payload.get('zone_codes'),
            'area_terms': payload.get('area_terms'),
            'led_default_lines': payload.get('led_default_lines'),
            'map_center_lat': payload.get('map_center_lat'),
            'map_center_lng': payload.get('map_center_lng'),
            'map_default_zoom': payload.get('map_default_zoom'),
        })
        return jsonify({'success': 'Location settings updated', 'settings': updated})
    except Exception as e:
        logger.error("Error processing location settings update: %s", e)
        return jsonify({'error': f'Failed to process location settings: {str(e)}'}), 500


class NOAAImportError(Exception):
    """Raised when manual NOAA alert retrieval fails."""

    def __init__(
        self,
        message: str,
        *,
        status_code: Optional[int] = None,
        query_url: Optional[str] = None,
        params: Optional[Dict[str, Union[str, int]]] = None,
        detail: Optional[str] = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.query_url = query_url
        self.params = params
        self.detail = detail


def normalize_manual_import_datetime(value: Union[str, datetime, None]) -> Optional[datetime]:
    """Normalize manual import datetimes to UTC for consistent NOAA queries."""
    if value is None:
        return None
    if isinstance(value, datetime):
        dt_value = value
    else:
        raw_value = str(value).strip()
        if not raw_value:
            return None
        try:
            dt_value = datetime.fromisoformat(raw_value)
        except ValueError:
            try:
                dt_value = datetime.fromisoformat(raw_value.replace('Z', '+00:00'))
            except ValueError:
                logger.warning("Manual import received unrecognized datetime format: %s", raw_value)
                return None
    if dt_value.tzinfo is None:
        dt_value = get_location_timezone().localize(dt_value)
    return dt_value.astimezone(UTC_TZ)


def format_noaa_timestamp(dt_value: Optional[datetime]) -> Optional[str]:
    """Render UTC timestamps in the NOAA API's preferred ISO format."""
    if not dt_value:
        return None
    return dt_value.astimezone(UTC_TZ).strftime('%Y-%m-%dT%H:%M:%SZ')


def build_noaa_alert_request(
    *,
    identifier: Optional[str] = None,
    start: Optional[datetime] = None,
    end: Optional[datetime] = None,
    area: Optional[str] = None,
    event: Optional[str] = None,
    limit: int = 10,
) -> Tuple[str, Optional[Dict[str, Union[str, int]]]]:
    """Construct the NOAA alerts endpoint and query parameters for manual imports."""
    query_url = NOAA_API_BASE_URL
    params: Optional[Dict[str, Union[str, int]]] = None

    if identifier:
        encoded_identifier = quote(identifier.strip(), safe=':.')
        query_url = f"{NOAA_API_BASE_URL}/{encoded_identifier}.json"
    else:
        params = {}
        if start:
            formatted_start = format_noaa_timestamp(start)
            if formatted_start:
                params['start'] = formatted_start
        if end:
            formatted_end = format_noaa_timestamp(end)
            if formatted_end:
                params['end'] = formatted_end
        if area:
            params['area'] = area
        if event:
            params['event'] = event

        if params:
            params = {
                key: value
                for key, value in params.items()
                if key in NOAA_ALLOWED_QUERY_PARAMS and value is not None
            } or None
        else:
            params = None

    return query_url, params


def _alert_datetime_to_iso(dt_value: Optional[datetime]) -> Optional[str]:
    """Render alert datetimes in ISO8601 with UTC timezone."""

    if not dt_value:
        return None
    if dt_value.tzinfo is None:
        aware_value = dt_value.replace(tzinfo=UTC_TZ)
    else:
        aware_value = dt_value.astimezone(UTC_TZ)
    return aware_value.isoformat()


def serialize_admin_alert(alert: CAPAlert) -> Dict[str, Any]:
    """Return a JSON-serializable representation of an alert for admin tooling."""

    return {
        'id': alert.id,
        'identifier': alert.identifier,
        'event': alert.event,
        'headline': alert.headline,
        'description': alert.description,
        'instruction': alert.instruction,
        'area_desc': alert.area_desc,
        'status': alert.status,
        'message_type': alert.message_type,
        'scope': alert.scope,
        'category': alert.category,
        'severity': alert.severity,
        'urgency': alert.urgency,
        'certainty': alert.certainty,
        'sent': _alert_datetime_to_iso(alert.sent),
        'expires': _alert_datetime_to_iso(alert.expires),
        'updated_at': _alert_datetime_to_iso(alert.updated_at),
        'created_at': _alert_datetime_to_iso(alert.created_at),
    }


def retrieve_noaa_alerts(
    *,
    identifier: Optional[str] = None,
    start: Optional[datetime] = None,
    end: Optional[datetime] = None,
    area: Optional[str] = None,
    event: Optional[str] = None,
    limit: int = 10,
) -> Tuple[List[dict], str, Optional[Dict[str, Union[str, int]]]]:
    """Execute a NOAA alerts query and return parsed features."""
    query_url, params = build_noaa_alert_request(
        identifier=identifier,
        start=start,
        end=end,
        area=area,
        event=event,
        limit=limit,
    )

    headers = {
        'Accept': 'application/geo+json, application/json;q=0.9',
        'User-Agent': NOAA_USER_AGENT,
    }

    try:
        response = requests.get(query_url, params=params, headers=headers, timeout=20)
    except requests.RequestException as exc:
        logger.error("NOAA alert import request failed: %s", exc)
        raise NOAAImportError(
            f'Failed to retrieve NOAA alert data: {exc}',
            query_url=query_url,
            params=params,
        ) from exc

    final_url = response.url

    if response.status_code == 404:
        raise NOAAImportError(
            'No alert was found for the supplied identifier or filters.',
            status_code=404,
            query_url=final_url,
            params=params,
        )

    if response.status_code >= 400:
        error_detail: Optional[str] = None
        parameter_errors: Optional[List[str]] = None
        try:
            error_payload = response.json()
            if isinstance(error_payload, dict):
                error_detail = error_payload.get('detail') or error_payload.get('title')
                raw_parameter_errors = error_payload.get('parameterErrors')
                if isinstance(raw_parameter_errors, list):
                    formatted_errors = []
                    for item in raw_parameter_errors:
                        if isinstance(item, dict):
                            name = item.get('parameter')
                            message = item.get('message')
                            if name and message:
                                formatted_errors.append(f"{name}: {message}")
                    if formatted_errors:
                        parameter_errors = formatted_errors
        except ValueError:
            error_detail = response.text.strip() or None

        logger.error(
            "NOAA manual import returned %s for %s with params %s: %s",
            response.status_code,
            final_url,
            params,
            error_detail or 'no error payload provided'
        )

        message = f'Failed to retrieve NOAA alert data: {response.status_code} {response.reason}'
        if error_detail:
            message = f"{message} ({error_detail})"
        if parameter_errors:
            message = f"{message} — {'; '.join(parameter_errors)}"

        raise NOAAImportError(
            message,
            status_code=response.status_code,
            query_url=final_url,
            params=params,
            detail=error_detail,
        )

    try:
        payload = response.json()
    except ValueError as exc:
        logger.error("NOAA alert import returned invalid JSON: %s", exc)
        raise NOAAImportError(
            'NOAA API response could not be decoded as JSON.',
            query_url=final_url,
            params=params,
        ) from exc

    if identifier:
        if isinstance(payload, dict) and 'features' in payload:
            alerts_payloads = payload.get('features', []) or []
        else:
            alerts_payloads = [payload]
    else:
        alerts_payloads = payload.get('features', []) if isinstance(payload, dict) else []

    if not identifier:
        try:
            effective_limit = max(1, min(int(limit or 10), 50))
        except (TypeError, ValueError):
            effective_limit = 10
        alerts_payloads = alerts_payloads[:effective_limit]

    if not alerts_payloads:
        raise NOAAImportError(
            'NOAA API did not return any alerts for the provided criteria.',
            status_code=404,
            query_url=final_url,
            params=params,
        )

    return alerts_payloads, final_url, params


@app.route('/admin/import_alert', methods=['POST'])
def import_specific_alert():
    """Manually import NOAA alerts (including expired) by identifier or date range."""
    data = request.get_json(silent=True) or request.form or {}

    identifier = (data.get('identifier') or '').strip()
    start_raw = (data.get('start') or '').strip()
    end_raw = (data.get('end') or '').strip()
    area = (data.get('area') or '').strip()
    event_filter = (data.get('event') or '').strip()

    try:
        limit_value = int(data.get('limit', 10))
    except (TypeError, ValueError):
        limit_value = 10
    limit_value = max(1, min(limit_value, 50))

    start_dt = normalize_manual_import_datetime(start_raw)
    end_dt = normalize_manual_import_datetime(end_raw)

    if start_raw and start_dt is None:
        return jsonify({'error': 'Could not parse the provided start timestamp. Use ISO 8601 format (e.g., 2025-01-15T13:00:00-05:00).'}), 400

    if end_raw and end_dt is None:
        return jsonify({'error': 'Could not parse the provided end timestamp. Use ISO 8601 format (e.g., 2025-01-15T18:00:00-05:00).'}), 400

    if not identifier and not (start_dt and end_dt):
        return jsonify({
            'error': 'Provide an alert identifier or both start and end timestamps.'
        }), 400

    now_utc = utc_now()
    if end_dt and end_dt > now_utc:
        logger.info(
            "Clamping manual NOAA import end time %s to current UTC %s", end_dt.isoformat(), now_utc.isoformat()
        )
        end_dt = now_utc

    if start_dt and end_dt and start_dt > end_dt:
        return jsonify({'error': 'The start time must be before the end time.'}), 400

    cleaned_area = ''.join(ch for ch in area.upper() if ch.isalpha()) if area else ''
    normalized_area = cleaned_area[:2] if cleaned_area else None

    if identifier:
        if area and (not normalized_area or len(normalized_area) != 2):
            return jsonify({'error': 'State filters must use the two-letter postal abbreviation.'}), 400
    else:
        if not normalized_area or len(normalized_area) != 2:
            return jsonify({'error': 'Provide the two-letter state code when searching without an identifier.'}), 400

    try:
        alerts_payloads, query_url, params = retrieve_noaa_alerts(
            identifier=identifier or None,
            start=start_dt,
            end=end_dt,
            area=normalized_area,
            event=event_filter or None,
            limit=limit_value,
        )
    except NOAAImportError as exc:
        status_code = exc.status_code or 502
        response_payload = {
            'error': str(exc),
            'status_code': exc.status_code,
            'query_url': exc.query_url,
            'params': exc.params,
        }
        if exc.detail:
            response_payload['detail'] = exc.detail
        if status_code == 404 and identifier:
            response_payload['identifier'] = identifier
        return jsonify(response_payload), status_code

    start_iso = format_noaa_timestamp(start_dt)
    end_iso = format_noaa_timestamp(end_dt)

    inserted = 0
    updated = 0
    skipped = 0
    identifiers: List[str] = []

    try:
        for feature in alerts_payloads:
            parsed_result = parse_noaa_cap_alert(feature)
            if not parsed_result:
                skipped += 1
                continue

            parsed, geometry = parsed_result
            alert_identifier = parsed['identifier']
            if alert_identifier not in identifiers:
                identifiers.append(alert_identifier)

            existing = CAPAlert.query.filter_by(identifier=alert_identifier).first()

            if existing:
                for key, value in parsed.items():
                    setattr(existing, key, value)
                existing.updated_at = utc_now()
                assign_alert_geometry(existing, geometry)
                db.session.flush()
                try:
                    if existing.geom:
                        calculate_alert_intersections(existing)
                except Exception as intersection_error:
                    logger.warning(
                        "Intersection recalculation failed for alert %s: %s",
                        alert_identifier,
                        intersection_error
                    )
                updated += 1
            else:
                new_alert = CAPAlert(**parsed)
                new_alert.created_at = utc_now()
                new_alert.updated_at = utc_now()
                assign_alert_geometry(new_alert, geometry)
                db.session.add(new_alert)
                db.session.flush()
                try:
                    if new_alert.geom:
                        calculate_alert_intersections(new_alert)
                except Exception as intersection_error:
                    logger.warning(
                        "Intersection calculation failed for new alert %s: %s",
                        alert_identifier,
                        intersection_error
                    )
                inserted += 1

        log_entry = SystemLog(
            level='INFO',
            message='Manual NOAA alert import executed',
            module='admin',
            details={
                'identifiers': identifiers,
                'inserted': inserted,
                'updated': updated,
                'skipped': skipped,
                'query_url': query_url,
                'params': params,
                'requested_filters': {
                    'identifier': identifier or None,
                    'start': start_iso,
                    'end': end_iso,
                    'area': normalized_area,
                    'event': event_filter or None,
                    'limit': limit_value,
                },
                'requested_at_utc': utc_now().isoformat(),
                'requested_at_local': local_now().isoformat()
            }
        )
        db.session.add(log_entry)
        db.session.commit()

    except Exception as exc:
        db.session.rollback()
        logger.error("Manual NOAA alert import failed: %s", exc)
        return jsonify({'error': f'Failed to import NOAA alert data: {exc}'}), 500

    return jsonify({
        'message': f'Imported {inserted} alert(s) and updated {updated} existing alert(s).',
        'inserted': inserted,
        'updated': updated,
        'skipped': skipped,
        'identifiers': identifiers,
        'query_url': query_url,
        'params': params
    })


@app.route('/admin/alerts', methods=['GET'])
def admin_list_alerts():
    """List alerts for the admin UI with optional search and expiration filters."""

    try:
        include_expired = request.args.get('include_expired', 'false').lower() == 'true'
        search_term = (request.args.get('search') or '').strip()
        limit_param = request.args.get('limit', type=int)
        limit = 100 if not limit_param else max(1, min(limit_param, 200))

        base_query = CAPAlert.query

        if not include_expired:
            now = utc_now()
            base_query = base_query.filter(
                or_(CAPAlert.expires.is_(None), CAPAlert.expires > now)
            )

        if search_term:
            like_pattern = f"%{search_term}%"
            base_query = base_query.filter(
                or_(
                    CAPAlert.identifier.ilike(like_pattern),
                    CAPAlert.event.ilike(like_pattern),
                    CAPAlert.headline.ilike(like_pattern)
                )
            )

        total_count = base_query.order_by(None).count()
        alerts = (
            base_query
            .order_by(desc(CAPAlert.sent))
            .limit(limit)
            .all()
        )

        serialized_alerts = [serialize_admin_alert(alert) for alert in alerts]

        return jsonify({
            'alerts': serialized_alerts,
            'returned': len(serialized_alerts),
            'total': total_count,
            'include_expired': include_expired,
            'limit': limit,
            'search': search_term or None,
        })
    except Exception as exc:
        logger.error("Failed to load alerts for admin listing: %s", exc)
        return jsonify({'error': 'Failed to load alerts.'}), 500


@app.route('/admin/alerts/<int:alert_id>', methods=['GET', 'PATCH', 'DELETE'])
def admin_alert_detail(alert_id: int):
    """Retrieve, update, or delete a single alert from the admin interface."""

    alert = CAPAlert.query.get(alert_id)
    if not alert:
        return jsonify({'error': 'Alert not found.'}), 404

    if request.method == 'GET':
        return jsonify({'alert': serialize_admin_alert(alert)})

    if request.method == 'DELETE':
        identifier = alert.identifier
        try:
            Intersection.query.filter_by(cap_alert_id=alert.id).delete(synchronize_session=False)

            try:
                if ensure_led_tables():
                    LEDMessage.query.filter_by(alert_id=alert.id).delete(synchronize_session=False)
            except Exception as led_cleanup_error:
                logger.warning(
                    "Failed to clean LED messages for alert %s during deletion: %s",
                    identifier,
                    led_cleanup_error,
                )
                db.session.rollback()
                return jsonify({'error': 'Failed to remove LED sign entries linked to this alert.'}), 500

            db.session.delete(alert)

            log_entry = SystemLog(
                level='WARNING',
                message='Alert deleted from admin interface',
                module='admin',
                details={
                    'alert_id': alert_id,
                    'identifier': identifier,
                    'deleted_at_utc': utc_now().isoformat(),
                },
            )
            db.session.add(log_entry)
            db.session.commit()

            logger.info("Admin deleted alert %s (%s)", identifier, alert_id)
            return jsonify({'message': f'Alert {identifier} deleted.', 'identifier': identifier})
        except Exception as exc:
            db.session.rollback()
            logger.error("Failed to delete alert %s (%s): %s", identifier, alert_id, exc)
            return jsonify({'error': 'Failed to delete alert.'}), 500

    payload = request.get_json(silent=True) or {}
    if not payload:
        return jsonify({'error': 'No update payload provided.'}), 400

    allowed_fields = {
        'event',
        'headline',
        'description',
        'instruction',
        'area_desc',
        'status',
        'severity',
        'urgency',
        'certainty',
        'category',
        'expires',
    }
    required_non_empty = {'event', 'status'}

    updates: Dict[str, Any] = {}
    change_details: Dict[str, Dict[str, Optional[str]]] = {}

    for field in allowed_fields:
        if field not in payload:
            continue

        value = payload[field]

        if field == 'expires':
            if value in (None, '', []):
                updates[field] = None
            else:
                normalized = normalize_manual_import_datetime(value)
                if not normalized:
                    return jsonify({'error': 'Could not parse the provided expiration time.'}), 400
                updates[field] = normalized
        else:
            if isinstance(value, str):
                value = value.strip()
            if field in required_non_empty and not value:
                return jsonify({'error': f'{field.replace("_", " ").title()} is required.'}), 400
            updates[field] = value or None

        previous_value = getattr(alert, field)
        if isinstance(previous_value, datetime):
            previous_rendered = _alert_datetime_to_iso(previous_value)
        else:
            previous_rendered = previous_value

        new_value = updates[field]
        if isinstance(new_value, datetime):
            new_rendered: Optional[str] = new_value.isoformat()
        else:
            new_rendered = new_value

        change_details[field] = {
            'old': previous_rendered,
            'new': new_rendered,
        }

    if not updates:
        return jsonify({'message': 'No changes detected.', 'alert': serialize_admin_alert(alert)})

    try:
        for field, value in updates.items():
            setattr(alert, field, value)

        alert.updated_at = utc_now()

        log_entry = SystemLog(
            level='INFO',
            message='Alert updated from admin interface',
            module='admin',
            details={
                'alert_id': alert.id,
                'identifier': alert.identifier,
                'changes': change_details,
                'updated_at_utc': alert.updated_at.isoformat(),
            },
        )
        db.session.add(log_entry)
        db.session.commit()

        logger.info(
            "Admin updated alert %s fields: %s",
            alert.identifier,
            ', '.join(sorted(updates.keys())),
        )

        db.session.refresh(alert)
        return jsonify({'message': 'Alert updated successfully.', 'alert': serialize_admin_alert(alert)})
    except Exception as exc:
        db.session.rollback()
        logger.error("Failed to update alert %s (%s): %s", alert.identifier, alert.id, exc)
        return jsonify({'error': 'Failed to update alert.'}), 500


@app.route('/admin/mark_expired', methods=['POST'])
def mark_expired():
    """Mark expired alerts as inactive without deleting them (SAFE OPTION)"""
    try:
        now = utc_now()

        expired_alerts = CAPAlert.query.filter(
            CAPAlert.expires < now,
            CAPAlert.status != 'Expired'
        ).all()

        count = len(expired_alerts)

        if count == 0:
            return jsonify({'message': 'No alerts need to be marked as expired'})

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


# =============================================================================
# INTERSECTION CALCULATION ROUTES
# =============================================================================

@app.route('/admin/fix_county_intersections', methods=['POST'])
def fix_county_intersections():
    """Recalculate intersection areas for all active alerts"""
    try:
        active_alerts = get_active_alerts_query().all()
        total_updated = 0

        for alert in active_alerts:
            if not alert.geom:
                continue

            # Delete existing intersections
            Intersection.query.filter_by(cap_alert_id=alert.id).delete()

            # Find all intersecting boundaries
            intersecting_boundaries = db.session.query(
                Boundary.id,
                func.ST_Area(func.ST_Intersection(alert.geom, Boundary.geom)).label('intersection_area')
            ).filter(
                func.ST_Intersects(alert.geom, Boundary.geom),
                func.ST_Area(func.ST_Intersection(alert.geom, Boundary.geom)) > 0
            ).all()

            # Create new intersection records
            for boundary_id, intersection_area in intersecting_boundaries:
                intersection = Intersection(
                    cap_alert_id=alert.id,
                    boundary_id=boundary_id,
                    intersection_area=intersection_area
                )
                db.session.add(intersection)
                total_updated += 1

        db.session.commit()

        return jsonify({
            'success': f'Successfully recalculated intersections for {len(active_alerts)} alerts. Updated {total_updated} intersection records.',
            'alerts_processed': len(active_alerts),
            'intersections_updated': total_updated
        })

    except Exception as e:
        db.session.rollback()
        logger.error(f"Error fixing county intersections: {str(e)}")
        return jsonify({'error': f'Failed to fix intersections: {str(e)}'}), 500


@app.route('/admin/recalculate_intersections', methods=['POST'])
def recalculate_intersections():
    """Recalculate all alert-boundary intersections"""
    try:
        logger.info("Starting full intersection recalculation")

        deleted_count = db.session.query(Intersection).delete()
        logger.info(f"Cleared {deleted_count} existing intersections")

        alerts_with_geometry = db.session.query(CAPAlert).filter(
            CAPAlert.geom.isnot(None)
        ).all()

        stats = {
            'alerts_processed': 0,
            'intersections_created': 0,
            'errors': 0,
            'deleted_intersections': deleted_count
        }

        for alert in alerts_with_geometry:
            try:
                intersections_created = calculate_alert_intersections(alert)
                stats['alerts_processed'] += 1
                stats['intersections_created'] += intersections_created
            except Exception as e:
                stats['errors'] += 1
                logger.error(f"Error processing alert {alert.identifier}: {str(e)}")

        db.session.commit()

        message = f"Recalculated intersections for {stats['alerts_processed']} alerts, created {stats['intersections_created']} new intersections"
        if stats['errors'] > 0:
            message += f" ({stats['errors']} errors)"

        logger.info(message)
        return jsonify({
            'success': message,
            'stats': stats
        })

    except Exception as e:
        logger.error(f"Error in recalculate_intersections: {str(e)}")
        db.session.rollback()
        return jsonify({'error': f'Failed to recalculate intersections: {str(e)}'}), 500


@app.route('/admin/calculate_intersections/<int:alert_id>', methods=['POST'])
def calculate_intersections_for_alert(alert_id):
    """Calculate and store intersections for a specific alert"""
    try:
        alert = CAPAlert.query.get_or_404(alert_id)

        if not alert.geom:
            return jsonify({'error': f'Alert {alert_id} has no geometry'}), 400

        # Remove existing intersections for this alert
        existing_count = Intersection.query.filter_by(cap_alert_id=alert_id).count()
        if existing_count > 0:
            Intersection.query.filter_by(cap_alert_id=alert_id).delete()
            logger.info(f"Removed {existing_count} existing intersections for alert {alert_id}")

        # Get all boundaries
        boundaries = Boundary.query.all()

        intersections_created = 0
        intersections_with_area = 0

        for boundary in boundaries:
            if not boundary.geom:
                continue

            # Calculate intersection using PostGIS
            intersection_result = db.session.query(
                func.ST_Intersects(alert.geom, boundary.geom).label('intersects'),
                func.ST_Area(func.ST_Intersection(alert.geom, boundary.geom)).label('intersection_area')
            ).first()

            if intersection_result.intersects:
                # Create intersection record
                intersection = Intersection(
                    cap_alert_id=alert_id,
                    boundary_id=boundary.id,
                    intersection_area=intersection_result.intersection_area or 0
                )
                db.session.add(intersection)
                intersections_created += 1

                if intersection_result.intersection_area and intersection_result.intersection_area > 0:
                    intersections_with_area += 1

        db.session.commit()

        # Log the operation
        log_entry = SystemLog(
            level='INFO',
            message=f'Calculated intersections for alert {alert_id}',
            module='admin',
            details={
                'alert_id': alert_id,
                'alert_event': alert.event,
                'intersections_created': intersections_created,
                'intersections_with_area': intersections_with_area,
                'boundaries_checked': len(boundaries),
                'calculated_at': utc_now().isoformat()
            }
        )
        db.session.add(log_entry)
        db.session.commit()

        return jsonify({
            'success': f'Calculated intersections for alert {alert_id}',
            'intersections_created': intersections_created,
            'intersections_with_area': intersections_with_area,
            'boundaries_checked': len(boundaries),
            'alert_event': alert.event
        })

    except Exception as e:
        db.session.rollback()
        logger.error(f"Error calculating intersections for alert {alert_id}: {str(e)}")
        return jsonify({'error': str(e)}), 500


@app.route('/admin/calculate_all_intersections', methods=['POST'])
def calculate_all_intersections():
    """Calculate intersections for all alerts"""
    try:
        # Get all alerts with geometry
        alerts_with_geom = CAPAlert.query.filter(CAPAlert.geom.isnot(None)).all()

        total_alerts = len(alerts_with_geom)
        total_intersections = 0
        processed_alerts = 0

        for alert in alerts_with_geom:
            # Remove existing intersections for this alert
            Intersection.query.filter_by(cap_alert_id=alert.id).delete()

            # Get all boundaries
            boundaries = Boundary.query.all()

            alert_intersections = 0
            for boundary in boundaries:
                if not boundary.geom:
                    continue

                # Calculate intersection using PostGIS
                intersection_result = db.session.query(
                    func.ST_Intersects(alert.geom, boundary.geom).label('intersects'),
                    func.ST_Area(func.ST_Intersection(alert.geom, boundary.geom)).label('intersection_area')
                ).first()

                if intersection_result.intersects:
                    intersection = Intersection(
                        cap_alert_id=alert.id,
                        boundary_id=boundary.id,
                        intersection_area=intersection_result.intersection_area or 0
                    )
                    db.session.add(intersection)
                    alert_intersections += 1

            total_intersections += alert_intersections
            processed_alerts += 1

            # Commit every 10 alerts to avoid memory issues
            if processed_alerts % 10 == 0:
                db.session.commit()
                logger.info(f"Processed {processed_alerts}/{total_alerts} alerts")

        # Final commit
        db.session.commit()

        # Log the operation
        log_entry = SystemLog(
            level='INFO',
            message=f'Calculated intersections for all alerts',
            module='admin',
            details={
                'total_alerts_processed': processed_alerts,
                'total_intersections_created': total_intersections,
                'calculated_at': utc_now().isoformat()
            }
        )
        db.session.add(log_entry)
        db.session.commit()

        return jsonify({
            'success': f'Calculated intersections for all alerts',
            'alerts_processed': processed_alerts,
            'total_intersections_created': total_intersections
        })

    except Exception as e:
        db.session.rollback()
        logger.error(f"Error calculating all intersections: {str(e)}")
        return jsonify({'error': str(e)}), 500


def calculate_coverage_percentages(alert_id, intersections):
    """
    Calculate actual coverage percentages for each boundary type and overall county coverage
    """
    coverage_data = {}

    try:
        # Get the alert polygon
        alert = CAPAlert.query.get(alert_id)
        if not alert or not alert.geom:
            return coverage_data

        # Group intersections by boundary type
        boundary_types = {}
        for intersection, boundary in intersections:
            if boundary.type not in boundary_types:
                boundary_types[boundary.type] = []
            boundary_types[boundary.type].append((intersection, boundary))

        # Calculate coverage for each boundary type
        for boundary_type, boundaries in boundary_types.items():
            # Get all boundaries of this type in the county
            all_boundaries_of_type = Boundary.query.filter_by(type=boundary_type).all()

            if not all_boundaries_of_type:
                continue

            # Calculate total area for this boundary type
            total_area_query = db.session.query(
                func.sum(func.ST_Area(Boundary.geom)).label('total_area')
            ).filter(Boundary.type == boundary_type).first()

            total_area = total_area_query.total_area if total_area_query.total_area else 0

            # Calculate intersected area
            intersected_area = sum(
                intersection.intersection_area or 0
                for intersection, boundary in boundaries
            )

            # Calculate coverage percentage
            coverage_percentage = 0.0
            if total_area > 0:
                coverage_percentage = (intersected_area / total_area) * 100
                coverage_percentage = min(100.0, max(0.0, coverage_percentage))  # Clamp to 0-100%

            coverage_data[boundary_type] = {
                'total_boundaries': len(all_boundaries_of_type),
                'affected_boundaries': len(boundaries),
                'coverage_percentage': round(coverage_percentage, 1),
                'total_area_sqm': total_area,
                'intersected_area_sqm': intersected_area
            }

        # Calculate overall county coverage
        county_boundary = Boundary.query.filter_by(type='county').first()
        if county_boundary and county_boundary.geom:
            # Calculate intersection area between alert and county
            county_intersection_query = db.session.query(
                func.ST_Area(
                    func.ST_Intersection(alert.geom, county_boundary.geom)
                ).label('intersection_area'),
                func.ST_Area(county_boundary.geom).label('total_county_area')
            ).first()

            if county_intersection_query:
                county_coverage = 0.0
                if county_intersection_query.total_county_area > 0:
                    county_coverage = (
                                              county_intersection_query.intersection_area /
                                              county_intersection_query.total_county_area
                                      ) * 100
                    county_coverage = min(100.0, max(0.0, county_coverage))

                coverage_data['county'] = {
                    'coverage_percentage': round(county_coverage, 1),
                    'total_area_sqm': county_intersection_query.total_county_area,
                    'intersected_area_sqm': county_intersection_query.intersection_area
                }

    except Exception as e:
        logger.error(f"Error calculating coverage percentages: {str(e)}")

    return coverage_data


@app.route('/admin/calculate_single_alert/<int:alert_id>', methods=['POST'])
def calculate_single_alert(alert_id):
    """Calculate intersections for a single alert"""
    try:
        alert = CAPAlert.query.get_or_404(alert_id)

        if not alert.geom:
            return jsonify({'error': 'Alert has no geometry data'}), 400

        deleted_count = Intersection.query.filter_by(cap_alert_id=alert_id).delete()

        boundaries = Boundary.query.all()

        if not boundaries:
            return jsonify({'error': 'No boundaries found in database. Upload some boundary files first.'}), 400

        intersections_created = 0
        errors = []

        for boundary in boundaries:
            try:
                intersection_query = db.session.query(
                    func.ST_Area(
                        func.ST_Intersection(alert.geom, boundary.geom)
                    ).label('intersection_area')
                ).filter(
                    func.ST_Intersects(alert.geom, boundary.geom)
                ).first()

                if intersection_query and intersection_query.intersection_area > 0:
                    intersection = Intersection(
                        cap_alert_id=alert_id,
                        boundary_id=boundary.id,
                        intersection_area=intersection_query.intersection_area
                    )
                    db.session.add(intersection)
                    intersections_created += 1

            except Exception as boundary_error:
                error_msg = f"Boundary {boundary.id}: {str(boundary_error)}"
                errors.append(error_msg)
                logger.warning(error_msg)

        db.session.commit()

        return jsonify({
            'success': f'Successfully calculated {intersections_created} boundary intersections',
            'intersections_created': intersections_created,
            'boundaries_tested': len(boundaries),
            'deleted_intersections': deleted_count,
            'errors': errors
        })

    except Exception as e:
        db.session.rollback()
        logger.error(f"Error calculating single alert: {str(e)}")
        return jsonify({'error': f'Failed to calculate intersections: {str(e)}'}), 500


# =============================================================================
# BOUNDARY MANAGEMENT ROUTES
# =============================================================================

def ensure_boundary_geometry_column():
    """Ensure the boundaries table accepts any geometry subtype with SRID 4326."""
    engine = db.engine
    if engine.dialect.name != 'postgresql':
        logger.debug(
            "Skipping boundaries.geom verification for non-PostgreSQL database (%s)",
            engine.dialect.name,
        )
        return True

    try:
        result = db.session.execute(
            text(
                """
                SELECT type
                FROM geometry_columns
                WHERE f_table_name = :table
                  AND f_geometry_column = :column
                ORDER BY (f_table_schema = current_schema()) DESC
                LIMIT 1
                """
            ),
            {'table': 'boundaries', 'column': 'geom'}
        ).scalar()

        if result and result.upper() == 'MULTIPOLYGON':
            logger.info("Updating boundaries.geom column to support multiple geometry types")
            db.session.execute(
                text(
                    """
                    ALTER TABLE boundaries
                    ALTER COLUMN geom TYPE geometry(GEOMETRY, 4326)
                    USING ST_SetSRID(geom, 4326)
                    """
                )
            )
            db.session.commit()
        elif not result:
            logger.debug("geometry_columns entry for boundaries.geom not found; skipping type verification")
        return True
    except Exception as exc:
        logger.warning("Could not ensure boundaries.geom column configuration: %s", exc)
        db.session.rollback()
        return False


def ensure_postgis_extension() -> bool:
    """Enable the PostGIS extension when running against PostgreSQL."""

    engine = db.engine
    if engine.dialect.name != 'postgresql':
        return True

    try:
        db.session.execute(text('CREATE EXTENSION IF NOT EXISTS postgis'))
        db.session.commit()
    except OperationalError as exc:
        logger.error('Failed to enable PostGIS extension: %s', exc)
        db.session.rollback()
        return False
    except Exception as exc:  # pragma: no cover - defensive
        logger.error('Unexpected error enabling PostGIS extension: %s', exc)
        db.session.rollback()
        raise
    else:
        logger.info('PostGIS extension ensured for the active database')
        return True


@app.route('/admin/check_db_health', methods=['GET'])
def check_db_health():
    """Provide a quick health check of the database connection and size."""
    try:
        db.session.execute(text('SELECT 1'))
        connectivity_status = 'Connected'
    except OperationalError as exc:
        logger.error("Database connectivity check failed: %s", exc)
        return jsonify({'error': 'Database connectivity check failed.'}), 500
    except Exception as exc:
        logger.error("Unexpected error during database health check: %s", exc)
        return jsonify({'error': 'Database health check encountered an unexpected error.'}), 500

    database_size = 'Unavailable'
    try:
        size_bytes = db.session.execute(
            text('SELECT pg_database_size(current_database())')
        ).scalar()
        if size_bytes is not None:
            database_size = format_bytes(size_bytes)
    except Exception as exc:
        logger.warning("Could not determine database size: %s", exc)

    active_connections: Union[str, int] = 'Unavailable'
    try:
        connection_count = db.session.execute(
            text('SELECT count(*) FROM pg_stat_activity WHERE datname = current_database()')
        ).scalar()
        if connection_count is not None:
            active_connections = int(connection_count)
    except Exception as exc:
        logger.warning("Could not determine active connection count: %s", exc)

    return jsonify({
        'connectivity': connectivity_status,
        'database_size': database_size,
        'active_connections': active_connections,
        'checked_at': utc_now().isoformat()
    })


@app.route('/admin/preview_geojson', methods=['POST'])
def preview_geojson():
    """Preview GeoJSON contents and extract useful metadata without persisting."""
    try:
        if 'file' not in request.files:
            return jsonify({'error': 'No file provided'}), 400

        file = request.files['file']
        raw_boundary_type = request.form.get('boundary_type', 'unknown')
        boundary_type = normalize_boundary_type(raw_boundary_type)
        boundary_label = get_boundary_display_label(raw_boundary_type)

        if file.filename == '':
            return jsonify({'error': 'No file selected'}), 400

        if not file.filename.lower().endswith('.geojson'):
            return jsonify({'error': 'File must be a GeoJSON file'}), 400

        try:
            file_contents = file.read().decode('utf-8')
        except UnicodeDecodeError:
            return jsonify({'error': 'Unable to decode file. Please ensure it is UTF-8 encoded.'}), 400

        try:
            geojson_data = json.loads(file_contents)
        except json.JSONDecodeError:
            return jsonify({'error': 'Invalid GeoJSON format'}), 400

        features = geojson_data.get('features')
        if not isinstance(features, list) or not features:
            return jsonify({
                'error': 'GeoJSON file does not contain any features.',
                'boundary_type': boundary_label,
                'total_features': 0
            }), 400

        preview_limit = 5
        previews: List[Dict[str, Any]] = []
        all_fields = set()
        owner_fields = set()
        line_id_fields = set()
        recommended_fields = set()

        for feature in features:
            properties = feature.get('properties', {}) or {}
            all_fields.update(properties.keys())

        for feature in features[:preview_limit]:
            properties = feature.get('properties', {}) or {}
            name, description = extract_name_and_description(properties, boundary_type)
            metadata = extract_feature_metadata(feature)

            preview_entry = {
                'name': name,
                'description': description,
                'owner': metadata.get('owner'),
                'line_id': metadata.get('line_id'),
                'mtfcc': metadata.get('mtfcc'),
                'classification': metadata.get('classification'),
                'length_label': metadata.get('length_label'),
                'additional_details': metadata.get('additional_details'),
            }
            previews.append(preview_entry)

            if metadata.get('owner_field'):
                owner_fields.add(metadata['owner_field'])
            if metadata.get('line_id_field'):
                line_id_fields.add(metadata['line_id_field'])
            recommended_fields.update(metadata.get('recommended_fields', set()))

        response_data = {
            'boundary_type': boundary_label,
            'normalized_type': boundary_type,
            'total_features': len(features),
            'preview_count': len(previews),
            'all_fields': sorted(all_fields),
            'previews': previews,
            'owner_fields': sorted(owner_fields),
            'line_id_fields': sorted(line_id_fields),
            'recommended_additional_fields': sorted(recommended_fields),
            'field_mappings': get_field_mappings().get(boundary_type, {}),
        }

        return jsonify(response_data)

    except Exception as exc:
        logger.error("Error previewing GeoJSON: %s", exc)
        return jsonify({'error': f'Failed to preview GeoJSON: {str(exc)}'}), 500


@app.route('/admin/upload_boundaries', methods=['POST'])
def upload_boundaries():
    """Upload GeoJSON boundary file with enhanced processing"""
    try:
        if 'file' not in request.files:
            return jsonify({'error': 'No file provided'}), 400

        file = request.files['file']
        raw_boundary_type = request.form.get('boundary_type', 'unknown')
        boundary_type = normalize_boundary_type(raw_boundary_type)
        boundary_label = get_boundary_display_label(raw_boundary_type)

        if file.filename == '':
            return jsonify({'error': 'No file selected'}), 400

        if not file.filename.lower().endswith('.geojson'):
            return jsonify({'error': 'File must be a GeoJSON file'}), 400

        try:
            geojson_data = json.loads(file.read().decode('utf-8'))
        except json.JSONDecodeError:
            return jsonify({'error': 'Invalid GeoJSON format'}), 400

        features = geojson_data.get('features', [])
        boundaries_added = 0
        errors = []

        for i, feature in enumerate(features):
            try:
                properties = feature.get('properties', {})
                geometry = feature.get('geometry')

                if not geometry:
                    errors.append(f"Feature {i + 1}: No geometry")
                    continue

                name, description = extract_name_and_description(properties, boundary_type)

                geometry_json = json.dumps(geometry)

                boundary = Boundary(
                    name=name,
                    type=boundary_type,
                    description=description,
                    created_at=utc_now(),
                    updated_at=utc_now()
                )

                boundary.geom = db.session.execute(
                    text("SELECT ST_SetSRID(ST_GeomFromGeoJSON(:geom), 4326)"),
                    {"geom": geometry_json}
                ).scalar()

                db.session.add(boundary)
                boundaries_added += 1

            except Exception as e:
                errors.append(f"Feature {i + 1}: {str(e)}")

        try:
            db.session.commit()
            logger.info(
                "Successfully uploaded %s %s boundaries",
                boundaries_added,
                boundary_label,
            )
        except Exception as e:
            db.session.rollback()
            return jsonify({'error': f'Database error: {str(e)}'}), 500

        response_data = {
            'success': f'Successfully uploaded {boundaries_added} {boundary_label} boundaries',
            'boundaries_added': boundaries_added,
            'total_features': len(features),
            'errors': errors[:10] if errors else [],
            'normalized_type': boundary_type,
            'display_label': boundary_label,
        }

        if errors:
            response_data['warning'] = f'{len(errors)} features had errors'

        return jsonify(response_data)

    except Exception as e:
        logger.error(f"Error uploading boundaries: {str(e)}")
        return jsonify({'error': f'Upload failed: {str(e)}'}), 500


@app.route('/admin/clear_boundaries/<boundary_type>', methods=['DELETE'])
def clear_boundaries(boundary_type):
    """Clear all boundaries of a specific type"""
    try:
        normalized_type = None

        if boundary_type == 'all':
            deleted_count = Boundary.query.delete()
            message = f'Deleted all {deleted_count} boundaries'
        else:
            normalized_type = normalize_boundary_type(boundary_type)
            deleted_count = Boundary.query.filter(
                func.lower(Boundary.type) == normalized_type
            ).delete(synchronize_session=False)
            message = (
                f"Deleted {deleted_count} {get_boundary_display_label(boundary_type)} boundaries"
            )

        db.session.commit()

        log_entry = SystemLog(
            level='WARNING',
            message=message,
            module='admin',
            details={
                'boundary_type': boundary_type,
                'normalized_type': normalized_type if boundary_type != 'all' else 'all',
                'deleted_count': deleted_count,
                'deleted_at_utc': utc_now().isoformat(),
                'deleted_at_local': local_now().isoformat()
            }
        )
        db.session.add(log_entry)
        db.session.commit()

        return jsonify({'success': message, 'deleted_count': deleted_count})

    except Exception as e:
        db.session.rollback()
        logger.error(f"Error clearing boundaries: {str(e)}")
        return jsonify({'error': f'Failed to clear boundaries: {str(e)}'}), 500


@app.route('/admin/clear_all_boundaries', methods=['DELETE'])
def clear_all_boundaries():
    """Clear all boundaries (requires confirmation)"""
    try:
        data = request.get_json() or {}

        confirmation_level = data.get('confirmation_level', 0)
        text_confirmation = data.get('text_confirmation', '')

        if confirmation_level < 2 or text_confirmation != 'DELETE ALL BOUNDARIES':
            return jsonify({'error': 'Invalid confirmation. This action requires proper confirmation.'}), 400

        deleted_count = Boundary.query.delete()
        db.session.commit()

        log_entry = SystemLog(
            level='CRITICAL',
            message=f'DELETED ALL BOUNDARIES: {deleted_count} boundaries permanently removed',
            module='admin',
            details={
                'deleted_count': deleted_count,
                'confirmation_level': confirmation_level,
                'deleted_at_utc': utc_now().isoformat(),
                'deleted_at_local': local_now().isoformat()
            }
        )
        db.session.add(log_entry)
        db.session.commit()

        return jsonify({
            'success': f'Successfully deleted all {deleted_count} boundaries',
            'deleted_count': deleted_count
        })

    except Exception as e:
        db.session.rollback()
        logger.error(f"Error clearing all boundaries: {str(e)}")
        return jsonify({'error': f'Failed to clear all boundaries: {str(e)}'}), 500


# =============================================================================
# DEBUG AND TESTING ROUTES
# =============================================================================

@app.route('/debug/alert/<int:alert_id>')
def debug_alert(alert_id):
    """Debug route to inspect alert geometry and intersections"""
    try:
        alert = CAPAlert.query.get_or_404(alert_id)

        geometry_info = None
        if alert.geom:
            geom_result = db.session.execute(
                text("""
                    SELECT 
                        ST_GeometryType(:geom) as type,
                        ST_SRID(:geom) as srid,
                        ST_Area(:geom) as area
                """),
                {"geom": alert.geom}
            ).fetchone()

            geometry_info = {
                'type': geom_result.type,
                'srid': geom_result.srid,
                'area': float(geom_result.area)
            }

        intersection_results = []
        if alert.geom:
            boundaries = Boundary.query.all()
            for boundary in boundaries:
                if boundary.geom:
                    try:
                        intersection_result = db.session.execute(
                            text("""
                                SELECT ST_Intersects(:alert_geom, :boundary_geom) as intersects,
                                       ST_Area(ST_Intersection(:alert_geom, :boundary_geom)) as area
                            """),
                            {
                                'alert_geom': alert.geom,
                                'boundary_geom': boundary.geom
                            }
                        ).fetchone()

                        intersection_results.append({
                            'boundary_id': boundary.id,
                            'boundary_name': boundary.name,
                            'boundary_type': boundary.type,
                            'intersects': bool(intersection_result.intersects),
                            'intersection_area': float(intersection_result.area) if intersection_result.area else 0
                        })
                    except Exception as e:
                        logger.error(f"Error checking intersection with boundary {boundary.id}: {e}")

        existing_intersections = db.session.query(Intersection).filter_by(cap_alert_id=alert_id).count()
        boundaries_in_db = Boundary.query.count()

        debug_info = {
            'alert_id': alert_id,
            'alert_event': alert.event,
            'alert_area_desc': alert.area_desc,
            'has_geometry': alert.geom is not None,
            'geometry_info': geometry_info,
            'boundaries_in_db': boundaries_in_db,
            'existing_intersections': existing_intersections,
            'intersection_results': intersection_results,
            'intersections_found': len([r for r in intersection_results if r['intersects']]),
            'errors': []
        }

        return jsonify(debug_info)

    except Exception as e:
        logger.error(f"Error debugging alert {alert_id}: {str(e)}")
        return jsonify({'error': f'Debug failed: {str(e)}'}), 500


@app.route('/debug/boundaries/<int:alert_id>')
def debug_boundaries(alert_id):
    """Debug boundary intersections for a specific alert"""
    try:
        alert = CAPAlert.query.get_or_404(alert_id)

        debug_info = {
            'alert_id': alert_id,
            'alert_event': alert.event,
            'alert_area_desc': alert.area_desc,
            'has_geometry': alert.geom is not None,
            'boundaries_in_db': Boundary.query.count(),
            'existing_intersections': Intersection.query.filter_by(cap_alert_id=alert_id).count(),
            'errors': []
        }

        if not alert.geom:
            debug_info['errors'].append('Alert has no geometry data')
            return jsonify(debug_info)

        boundaries = Boundary.query.all()
        intersection_results = []

        for boundary in boundaries:
            try:
                intersection_test = db.session.query(
                    func.ST_Intersects(alert.geom, boundary.geom).label('intersects'),
                    func.ST_Area(func.ST_Intersection(alert.geom, boundary.geom)).label('area')
                ).first()

                intersection_results.append({
                    'boundary_id': boundary.id,
                    'boundary_name': boundary.name,
                    'boundary_type': boundary.type,
                    'intersects': bool(
                        intersection_test.intersects) if intersection_test.intersects is not None else False,
                    'intersection_area': float(intersection_test.area) if intersection_test.area else 0
                })

            except Exception as boundary_error:
                debug_info['errors'].append(f'Error testing boundary {boundary.id}: {str(boundary_error)}')

        debug_info['intersection_results'] = intersection_results
        debug_info['intersections_found'] = len([r for r in intersection_results if r['intersects']])

        try:
            geom_info = db.session.query(
                func.ST_GeometryType(alert.geom).label('geom_type'),
                func.ST_SRID(alert.geom).label('srid'),
                func.ST_Area(alert.geom).label('area')
            ).first()

            debug_info['geometry_info'] = {
                'type': geom_info.geom_type if geom_info else 'Unknown',
                'srid': geom_info.srid if geom_info else 'Unknown',
                'area': float(geom_info.area) if geom_info and geom_info.area else 0
            }
        except Exception as geom_error:
            debug_info['errors'].append(f'Error getting geometry info: {str(geom_error)}')

        return jsonify(debug_info)

    except Exception as e:
        logger.error(f"Error in debug_boundaries: {str(e)}")
        return jsonify({'error': str(e), 'alert_id': alert_id}), 500


# =============================================================================
# LED CONTROL ROUTES
# =============================================================================

@app.route('/led')
def led_redirect():
    """Maintain legacy /led URL by redirecting to the control dashboard."""
    return redirect(url_for('led_control'))
@app.route('/led_control')
def led_control():
    """LED sign control interface"""
    try:
        ensure_led_tables()

        led_status = None
        if led_controller:
            led_status = led_controller.get_status()

        recent_messages = []
        try:
            recent_messages = LEDMessage.query.order_by(
                LEDMessage.created_at.desc()
            ).limit(10).all()
        except OperationalError as db_error:
            if 'led_messages' in str(db_error.orig):
                logger.warning("LED messages table missing; creating tables now")
                db.create_all()
                recent_messages = LEDMessage.query.order_by(
                    LEDMessage.created_at.desc()
                ).limit(10).all()
            else:
                raise

        canned_messages = []
        if led_controller:
            for name, config in led_controller.canned_messages.items():
                lines = config.get('lines') or config.get('text') or []
                if isinstance(lines, str):
                    lines = [lines]

                canned_messages.append({
                    'name': name,
                    'lines': lines,
                    'color': getattr(config.get('color'), 'name', str(config.get('color'))),
                    'font': getattr(config.get('font'), 'name', str(config.get('font'))),
                    'mode': getattr(config.get('mode'), 'name', str(config.get('mode'))),
                    'speed': getattr(config.get('speed'), 'name', str(config.get('speed', Speed.SPEED_3))),
                    'hold_time': config.get('hold_time', 5),
                    'priority': getattr(config.get('priority'), 'name', str(config.get('priority', MessagePriority.NORMAL)))
                })

        return render_template('led_control.html',
                               led_status=led_status,
                               recent_messages=recent_messages,
                               canned_messages=canned_messages,
                               led_available=LED_AVAILABLE)

    except Exception as e:
        logger.error(f"Error loading LED control page: {e}")
        return f"<h1>LED Control Error</h1><p>{str(e)}</p><p><a href='/'>← Back to Main</a></p>"


# =============================================================================
# LED SIGN API ROUTES
# =============================================================================

@app.route('/api/led/send_message', methods=['POST'])
def api_led_send_message():
    """Send custom message to LED sign"""
    try:
        ensure_led_tables()

        data = request.get_json()

        if not led_controller:
            return jsonify({'success': False, 'error': 'LED controller not available'})

        if not _led_enums_available():
            return jsonify({'success': False, 'error': 'LED library enums unavailable'})

        lines = data.get('lines')
        if isinstance(lines, str):
            lines = [line for line in lines.splitlines() if line.strip()]

        if not lines:
            return jsonify({'success': False, 'error': 'At least one line of text is required'})

        color_name = data.get('color', 'GREEN')
        font_name = data.get('font', 'FONT_7x9')
        mode_name = data.get('mode', 'HOLD')
        speed_name = data.get('speed', 'SPEED_3')
        hold_time = int(data.get('hold_time', 5))
        priority_value = int(data.get('priority', MessagePriority.NORMAL.value))

        try:
            color = Color[color_name.upper()]
            font = Font[font_name.upper()]
            mode = DisplayMode[mode_name.upper()]
            speed = Speed[speed_name.upper()]
            priority = MessagePriority(priority_value)
        except (KeyError, ValueError) as e:
            return jsonify({'success': False, 'error': f'Invalid parameter: {str(e)}'})

        special_functions_raw = data.get('special_functions', []) or []
        special_functions = []
        special_enum = getattr(led_module, 'SpecialFunction', None) if led_module else None
        if special_enum:
            for func_name in special_functions_raw:
                try:
                    special_functions.append(special_enum[func_name.upper()])
                except KeyError:
                    logger.warning("Ignoring unknown special function: %s", func_name)

        led_message = LEDMessage(
            message_type='custom',
            content='\n'.join(lines),
            priority=priority.value,
            color=color.name,
            font_size=font.name,
            effect=mode.name,
            speed=speed.name,
            display_time=hold_time,
            scheduled_time=utc_now()
        )
        db.session.add(led_message)
        db.session.commit()

        result = led_controller.send_message(
            lines=lines,
            color=color,
            font=font,
            mode=mode,
            speed=speed,
            hold_time=hold_time,
            special_functions=special_functions or None,
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
        ensure_led_tables()

        data = request.get_json()
        message_name = data.get('message_name')
        parameters = data.get('parameters', {})

        if not message_name:
            return jsonify({'success': False, 'error': 'Message name is required'})

        if not led_controller:
            return jsonify({'success': False, 'error': 'LED controller not available'})

        led_message = LEDMessage(
            message_type='canned',
            content=message_name,
            priority=2,
            scheduled_time=utc_now()
        )
        db.session.add(led_message)
        db.session.commit()

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
        ensure_led_tables()

        if not led_controller:
            return jsonify({'success': False, 'error': 'LED controller not available'})

        result = led_controller.clear_display()

        if result:
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
        ensure_led_tables()

        data = request.get_json()
        brightness = int(data.get('brightness', 10))

        if not 1 <= brightness <= 16:
            return jsonify({'success': False, 'error': 'Brightness must be between 1 and 16'})

        if not led_controller:
            return jsonify({'success': False, 'error': 'LED controller not available'})

        result = led_controller.set_brightness(brightness)

        if result:
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

        led_message = LEDMessage(
            message_type='emergency',
            content=message,
            priority=0,
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
        ensure_led_tables()

        status = {
            'controller_available': led_controller is not None,
            'sign_ip': LED_SIGN_IP,
            'sign_port': LED_SIGN_PORT,
            'led_library_available': LED_AVAILABLE
        }

        if led_controller:
            status.update(led_controller.get_status())

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
        ensure_led_tables()

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
            lines = config.get('lines') or config.get('text') or []
            if isinstance(lines, str):
                lines = [lines]

            canned_messages.append({
                'name': name,
                'lines': lines,
                'color': getattr(config.get('color'), 'name', str(config.get('color'))),
                'font': getattr(config.get('font'), 'name', str(config.get('font'))),
                'mode': getattr(config.get('mode'), 'name', str(config.get('mode'))),
                'speed': getattr(config.get('speed'), 'name', str(config.get('speed', Speed.SPEED_3))),
                'hold_time': config.get('hold_time', 5),
                'priority': getattr(config.get('priority'), 'name', str(config.get('priority', MessagePriority.NORMAL)))
            })

        return jsonify({'canned_messages': canned_messages})

    except Exception as e:
        logger.error(f"Error getting canned messages: {e}")
        return jsonify({'error': str(e)})


# =============================================================================
# DATA EXPORT ROUTES
# =============================================================================

@app.route('/export/alerts')
def export_alerts():
    """Export alerts data to Excel with proper timezone formatting"""
    try:
        alerts = CAPAlert.query.order_by(CAPAlert.sent.desc()).all()

        alerts_data = []
        for alert in alerts:
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
            'timezone': get_location_timezone_name()
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
            'timezone': get_location_timezone_name()
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
            'timezone': get_location_timezone_name()
        })

    except Exception as e:
        logger.error(f"Error exporting statistics: {str(e)}")
        return jsonify({'error': 'Failed to export statistics data'}), 500


@app.route('/export/intersections')
def export_intersections():
    """Export intersection data with full details"""
    try:
        intersections = db.session.query(
            Intersection, CAPAlert, Boundary
        ).join(
            CAPAlert, Intersection.cap_alert_id == CAPAlert.id
        ).join(
            Boundary, Intersection.boundary_id == Boundary.id
        ).all()

        intersection_data = []
        for intersection, alert, boundary in intersections:
            created_local = format_local_datetime(intersection.created_at,
                                                  include_utc=False) if intersection.created_at else ''
            alert_sent_local = format_local_datetime(alert.sent, include_utc=False) if alert.sent else ''

            intersection_data.append({
                'Intersection_ID': intersection.id,
                'Alert_ID': alert.id,
                'Alert_Identifier': alert.identifier,
                'Alert_Event': alert.event,
                'Alert_Severity': alert.severity or '',
                'Alert_Sent_Local': alert_sent_local,
                'Boundary_ID': boundary.id,
                'Boundary_Name': boundary.name,
                'Boundary_Type': boundary.type,
                'Intersection_Area': intersection.intersection_area or 0,
                'Created_Local_Time': created_local,
                'Created_UTC': intersection.created_at.isoformat() if intersection.created_at else ''
            })

        return jsonify({
            'data': intersection_data,
            'total': len(intersection_data),
            'exported_at': utc_now().isoformat(),
            'exported_at_local': local_now().isoformat(),
            'timezone': get_location_timezone_name()
        })

    except Exception as e:
        logger.error(f"Error exporting intersections: {str(e)}")
        return jsonify({'error': 'Failed to export intersection data'}), 500


# =============================================================================
# ERROR HANDLERS
# =============================================================================

@app.errorhandler(404)
def not_found_error(error):
    """Enhanced 404 error page"""
    return render_template_string("""
    <h1>404 - Page Not Found</h1>
    <p>The page you're looking for doesn't exist.</p>
    <p><a href='/'>← Back to Main</a> | <a href='/admin'>Admin</a> | <a href='/alerts'>Alerts</a></p>
    """), 404


@app.errorhandler(500)
def internal_error(error):
    """Enhanced 500 error page"""
    if hasattr(db, 'session') and db.session:
        db.session.rollback()

    return render_template_string("""
    <h1>500 - Internal Server Error</h1>
    <p>Something went wrong on our end. Please try again later.</p>
    <p><a href='/'>← Back to Main</a> | <a href='/admin'>Admin</a></p>
    """), 500


@app.errorhandler(403)
def forbidden_error(error):
    """403 Forbidden error page"""
    return render_template_string("""
    <h1>403 - Forbidden</h1>
    <p>You don't have permission to access this resource.</p>
    <p><a href='/'>← Back to Main</a></p>
    """), 403


@app.errorhandler(400)
def bad_request_error(error):
    """400 Bad Request error page"""
    return render_template_string("""
    <h1>400 - Bad Request</h1>
    <p>The request was malformed or invalid.</p>
    <p><a href='/'>← Back to Main</a></p>
    """), 400


# =============================================================================
# HEALTH CHECK AND MONITORING ROUTES
# =============================================================================

@app.route('/health')
def health_check():
    """Simple health check endpoint"""
    try:
        # Test database connection
        db.session.execute(text('SELECT 1')).fetchone()

        return jsonify({
            'status': 'healthy',
            'timestamp': utc_now().isoformat(),
            'local_timestamp': local_now().isoformat(),
            'version': SYSTEM_VERSION,
            'database': 'connected',
            'led_available': LED_AVAILABLE
        })
    except Exception as e:
        return jsonify({
            'status': 'unhealthy',
            'error': str(e),
            'timestamp': utc_now().isoformat(),
            'local_timestamp': local_now().isoformat()
        }), 500


@app.route('/ping')
def ping():
    """Simple ping endpoint"""
    return jsonify({
        'pong': True,
        'timestamp': utc_now().isoformat(),
        'local_timestamp': local_now().isoformat()
    })


@app.route('/version')
def version():
    """Version information endpoint"""
    location = get_location_settings()
    return jsonify({
        'version': SYSTEM_VERSION,
        'name': 'NOAA CAP Alerts System',
        'author': 'KR8MER Amateur Radio Emergency Communications',
        'description': f"Emergency alert system for {location['county_name']}, {location['state_code']}",
        'timezone': get_location_timezone_name(),
        'led_available': LED_AVAILABLE,
        'timestamp': utc_now().isoformat(),
        'local_timestamp': local_now().isoformat()
    })


# =============================================================================
# ADDITIONAL UTILITY ROUTES
# =============================================================================

@app.route('/favicon.ico')
def favicon():
    """Serve favicon"""
    return '', 204


@app.route('/robots.txt')
def robots():
    """Robots.txt for web crawlers"""
    return """User-agent: *
Disallow: /admin/
Disallow: /api/
Disallow: /debug/
Allow: /
""", 200, {'Content-Type': 'text/plain'}


# =============================================================================
# CONTEXT PROCESSORS FOR TEMPLATES
# =============================================================================

@app.context_processor
def inject_global_vars():
    """Inject global variables into all templates"""
    location_settings = get_location_settings()
    return {
        'current_utc_time': utc_now(),
        'current_local_time': local_now(),
        'timezone_name': get_location_timezone_name(),
        'led_available': LED_AVAILABLE,
        'system_version': SYSTEM_VERSION,
        'location_settings': location_settings,
        'boundary_type_config': BOUNDARY_TYPE_CONFIG,
        'boundary_group_labels': BOUNDARY_GROUP_LABELS,
        'current_user': getattr(g, 'current_user', None),
        'eas_broadcast_enabled': app.config.get('EAS_BROADCAST_ENABLED', False),
        'eas_output_web_subdir': app.config.get('EAS_OUTPUT_WEB_SUBDIR', 'eas_messages'),
    }


# =============================================================================
# REQUEST HOOKS
# =============================================================================

@app.before_request
def before_request():
    """Before request hook for logging and setup"""
    # Log API requests for debugging
    if request.path.startswith('/api/') and request.method in ['POST', 'PUT', 'DELETE']:
        logger.info(f"{request.method} {request.path} from {request.remote_addr}")

    # Ensure the database schema exists before handling the request.
    initialize_database()

    # Load the current user from the session for downstream use.
    g.current_user = None
    user_id = session.get('user_id')
    if user_id is not None:
        user = AdminUser.query.get(user_id)
        if user and user.is_active:
            g.current_user = user
        else:
            session.pop('user_id', None)

    try:
        g.admin_setup_mode = AdminUser.query.count() == 0
    except Exception:
        g.admin_setup_mode = False

    # Allow authentication endpoints without additional checks.
    if request.endpoint in {'login', 'static'}:
        return

    protected_prefixes = ('/admin', '/logs')
    if any(request.path.startswith(prefix) for prefix in protected_prefixes):
        if g.current_user is None:
            if g.admin_setup_mode and request.endpoint in {'admin', 'admin_users'}:
                if request.method == 'GET' or (request.method == 'POST' and request.endpoint == 'admin_users'):
                    return
            accept_header = request.headers.get('Accept', '')
            next_url = request.full_path if request.query_string else request.path
            if request.method != 'GET' or 'application/json' in accept_header or request.is_json:
                return jsonify({'error': 'Authentication required'}), 401
            return redirect(url_for('login', next=next_url))


@app.after_request
def after_request(response):
    """After request hook for headers and cleanup"""
    # Add CORS headers for API endpoints
    if request.path.startswith('/api/'):
        response.headers.add('Access-Control-Allow-Origin', '*')
        response.headers.add('Access-Control-Allow-Headers', 'Content-Type,Authorization')
        response.headers.add('Access-Control-Allow-Methods', 'GET,PUT,POST,DELETE,OPTIONS')

    # Add security headers
    response.headers.add('X-Content-Type-Options', 'nosniff')
    response.headers.add('X-Frame-Options', 'DENY')
    response.headers.add('X-XSS-Protection', '1; mode=block')

    return response


# Flask 3 removed the ``before_first_request`` hook in favour of
# ``before_serving``.  Older Flask releases (including the one bundled with
# this project) do not provide ``before_serving`` though, so we register the
# handler dynamically depending on which hook is available.  If neither hook is
# present we fall back to running the initialization immediately within an
# application context.
def initialize_database():
    """Create all database tables, logging any initialization failure."""
    global _db_initialized, _db_initialization_error

    if _db_initialized:
        return

    try:
        if not ensure_postgis_extension():
            _db_initialization_error = RuntimeError("PostGIS extension could not be ensured")
            return False
        db.create_all()
        ensure_boundary_geometry_column()
        settings = get_location_settings(force_reload=True)
        timezone_name = settings.get('timezone')
        if timezone_name:
            set_location_timezone(timezone_name)
        if not LED_AVAILABLE:
            initialise_led_controller(logger)
            ensure_led_tables()
    except OperationalError as db_error:
        _db_initialization_error = db_error
        logger.error("Database initialization failed: %s", db_error)
        return False
    except Exception as db_error:
        _db_initialization_error = db_error
        logger.error("Database initialization failed: %s", db_error)
        raise
    else:
        _db_initialized = True
        _db_initialization_error = None
        logger.info("Database tables ensured on startup")
        return True


if hasattr(app, "before_serving"):
    app.before_serving(initialize_database)
elif hasattr(app, "before_first_request"):
    app.before_first_request(initialize_database)
else:
    with app.app_context():
        initialize_database()


# =============================================================================
# CLI COMMANDS (for future use with Flask CLI)
# =============================================================================

@app.cli.command()
def init_db():
    """Initialize the database tables"""
    initialize_database()
    logger.info("Database tables created successfully")


@app.cli.command()
def test_led():
    """Test LED controller connection"""
    if led_controller:
        try:
            status = led_controller.get_status()
            logger.info(f"LED Status: {status}")

            # Send test message
            result = led_controller.send_message("TEST MESSAGE")
            logger.info(f"Test message sent: {result}")
        except Exception as e:
            logger.error(f"LED test failed: {e}")
    else:
        logger.warning("LED controller not available")


@app.cli.command('create-admin-user')
@click.option('--username', prompt=True)
@click.option('--password', prompt=True, hide_input=True, confirmation_prompt=True)
def create_admin_user_cli(username: str, password: str):
    """Create a new administrator user account."""
    initialize_database()

    username = username.strip()
    if not USERNAME_PATTERN.match(username):
        raise click.ClickException('Usernames must be 3-64 characters and may include letters, numbers, dots, underscores, and hyphens.')

    if len(password) < 8:
        raise click.ClickException('Password must be at least 8 characters long.')

    existing = AdminUser.query.filter(func.lower(AdminUser.username) == username.lower()).first()
    if existing:
        raise click.ClickException('That username already exists.')

    user = AdminUser(username=username)
    user.set_password(password)
    db.session.add(user)
    db.session.add(SystemLog(
        level='INFO',
        message='Administrator account created via CLI',
        module='auth',
        details={'username': username},
    ))
    db.session.commit()

    click.echo(f'Created administrator account for {username}.')


@app.cli.command()
def cleanup_expired():
    """Mark expired alerts as expired (safe cleanup)"""
    try:
        now = utc_now()
        expired_alerts = CAPAlert.query.filter(
            CAPAlert.expires < now,
            CAPAlert.status != 'Expired'
        ).all()

        count = 0
        for alert in expired_alerts:
            alert.status = 'Expired'
            alert.updated_at = now
            count += 1

        db.session.commit()
        logger.info(f"Marked {count} alerts as expired")

    except Exception as e:
        logger.error(f"Error in cleanup: {e}")
        db.session.rollback()


# =============================================================================
# APPLICATION STARTUP AND CONFIGURATION
# =============================================================================

def create_app(config=None):
    """Application factory pattern for testing"""
    if config:
        app.config.update(config)

    with app.app_context():
        initialize_database()

    return app


# =============================================================================
# APPLICATION STARTUP
# =============================================================================

if __name__ == '__main__':
    with app.app_context():
        initialize_database()

    app.run(debug=True, host='0.0.0.0', port=5000)
