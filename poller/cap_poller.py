#!/usr/bin/env python3
"""
NOAA CAP Alert Poller with configurable location filtering
Docker-safe DB defaults, strict jurisdiction filtering, PostGIS geometry/intersections,
optional LED sign integration.

Defaults for Docker (override with env or --database-url):
  POSTGRES_HOST=postgresql   # service/container name (NOT localhost)
  POSTGRES_PORT=5432
  POSTGRES_DB=casaos
  POSTGRES_USER=casaos
  POSTGRES_PASSWORD=casaos
  DATABASE_URL=postgresql+psycopg2://casaos:casaos@postgresql:5432/casaos
"""

import os
import sys
import time
import json
import requests
import logging
import hashlib
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple
import argparse

import pytz
from dotenv import load_dotenv

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(CURRENT_DIR, os.pardir))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

load_dotenv()
from sqlalchemy import create_engine, text, func, or_
from sqlalchemy.orm import sessionmaker
from sqlalchemy.exc import SQLAlchemyError, OperationalError

# =======================================================================================
# Timezones and helpers
# =======================================================================================

from app_utils import (
    format_local_datetime as util_format_local_datetime,
    local_now as util_local_now,
    parse_nws_datetime as util_parse_nws_datetime,
    set_location_timezone,
    utc_now as util_utc_now,
)
from app_utils.location_settings import DEFAULT_LOCATION_SETTINGS, ensure_list, normalise_upper
from app_utils.eas import EASBroadcaster, load_eas_config

UTC_TZ = pytz.UTC


def utc_now():
    return util_utc_now()


def local_now():
    return util_local_now()


def parse_nws_datetime(dt_string):
    return util_parse_nws_datetime(dt_string, logger=logging.getLogger(__name__))


def format_local_datetime(dt, include_utc=True):
    return util_format_local_datetime(dt, include_utc=include_utc)

# =======================================================================================
# Optional LED controller import
# =======================================================================================

LED_AVAILABLE = False
LEDSignController = None
try:
    from led_sign_controller import LEDSignController as _LED
    LEDSignController = _LED
    LED_AVAILABLE = True
except Exception as e:
    # Use logger later; stdout here to ensure visibility even before logging config
    print(f"Warning: LED sign controller not available ({e})")

# =======================================================================================
# Fall-back ORM model definitions if app models aren't importable
# =======================================================================================

FLASK_MODELS_AVAILABLE = False
USE_EXISTING_DB = True

try:
    # Try to pull models from your main app if present in the image
    project_root = os.path.dirname(os.path.abspath(__file__))
    if project_root.endswith('/poller'):
        project_root = os.path.dirname(project_root)
    sys.path.insert(0, project_root)
    from app import db, CAPAlert, SystemLog, Boundary, Intersection, LocationSettings, EASMessage  # type: ignore
    from sqlalchemy import Column, Integer, String, DateTime, Text, JSON  # noqa: F401

    class PollHistory(db.Model):  # type: ignore
        __tablename__ = 'poll_history'
        __table_args__ = {'extend_existing': True}
        id = db.Column(db.Integer, primary_key=True)
        timestamp = db.Column(db.DateTime, default=utc_now)
        alerts_fetched = db.Column(db.Integer, default=0)
        alerts_new = db.Column(db.Integer, default=0)
        alerts_updated = db.Column(db.Integer, default=0)
        execution_time_ms = db.Column(db.Integer)
        status = db.Column(db.String(20))
        error_message = db.Column(db.Text)

    FLASK_MODELS_AVAILABLE = True

except Exception as e:
    print(f"Warning: Could not import app models: {e}")
    from sqlalchemy import Column, Integer, String, DateTime, Text, JSON, Boolean, Float, ForeignKey
    from sqlalchemy.ext.declarative import declarative_base
    from sqlalchemy.orm import relationship  # noqa: F401
    from geoalchemy2 import Geometry

    Base = declarative_base()

    class CAPAlert(Base):
        __tablename__ = 'cap_alerts'
        __table_args__ = {'extend_existing': True}
        id = Column(Integer, primary_key=True)
        identifier = Column(String(255), unique=True, nullable=False)
        sent = Column(DateTime, nullable=False)
        expires = Column(DateTime)
        status = Column(String(50))
        message_type = Column(String(50))
        scope = Column(String(50))
        category = Column(String(50))
        event = Column(String(100))
        urgency = Column(String(50))
        severity = Column(String(50))
        certainty = Column(String(50))
        area_desc = Column(Text)
        headline = Column(Text)
        description = Column(Text)
        instruction = Column(Text)
        raw_json = Column(JSON)
        geom = Column(Geometry('POLYGON', srid=4326))
        created_at = Column(DateTime, default=utc_now)
        updated_at = Column(DateTime, default=utc_now)

    class Boundary(Base):
        __tablename__ = 'boundaries'
        __table_args__ = {'extend_existing': True}
        id = Column(Integer, primary_key=True)
        name = Column(String(255), nullable=False)
        type = Column(String(50), nullable=False)
        description = Column(Text)
        geom = Column(Geometry('MULTIPOLYGON', srid=4326))
        created_at = Column(DateTime, default=utc_now)
        updated_at = Column(DateTime, default=utc_now)

    class Intersection(Base):
        __tablename__ = 'intersections'
        __table_args__ = {'extend_existing': True}
        id = Column(Integer, primary_key=True)
        cap_alert_id = Column(Integer, ForeignKey('cap_alerts.id'))
        boundary_id = Column(Integer, ForeignKey('boundaries.id'))
        intersection_area = Column(Float)
        created_at = Column(DateTime, default=utc_now)

    class SystemLog(Base):
        __tablename__ = 'system_log'  # singular matches schema
        __table_args__ = {'extend_existing': True}
        id = Column(Integer, primary_key=True)
        timestamp = Column(DateTime, default=utc_now)
        level = Column(String(20))
        message = Column(Text)
        module = Column(String(50))
        details = Column(JSON)

    class PollHistory(Base):
        __tablename__ = 'poll_history'
        __table_args__ = {'extend_existing': True}
        id = Column(Integer, primary_key=True)
        timestamp = Column(DateTime, default=utc_now)
        alerts_fetched = Column(Integer, default=0)
        alerts_new = Column(Integer, default=0)
        alerts_updated = Column(Integer, default=0)
        execution_time_ms = Column(Integer)
        status = Column(String(20))
        error_message = Column(Text)

    class LocationSettings(Base):
        __tablename__ = 'location_settings'
        __table_args__ = {'extend_existing': True}
        id = Column(Integer, primary_key=True)
        county_name = Column(String(255))
        state_code = Column(String(2))
        timezone = Column(String(64))
        zone_codes = Column(JSON)
        area_terms = Column(JSON)
        map_center_lat = Column(Float)
        map_center_lng = Column(Float)
        map_default_zoom = Column(Integer)
        led_default_lines = Column(JSON)
        updated_at = Column(DateTime, default=utc_now)

    class EASMessage(Base):
        __tablename__ = 'eas_messages'
        __table_args__ = {'extend_existing': True}
        id = Column(Integer, primary_key=True)
        cap_alert_id = Column(Integer, ForeignKey('cap_alerts.id'))
        same_header = Column(String(255))
        audio_filename = Column(String(255))
        text_filename = Column(String(255))
        created_at = Column(DateTime, default=utc_now)
        metadata_payload = Column('metadata', JSON)

# =======================================================================================
# Poller
# =======================================================================================

class CAPPoller:
    """CAP alert poller with strict location filtering, PostGIS, optional LED."""

    def __init__(self, database_url: str, led_sign_ip: str = None, led_sign_port: int = 10001):
        self.database_url = database_url
        self.led_sign_ip = led_sign_ip
        self.led_sign_port = led_sign_port

        self.logger = logging.getLogger(__name__)

        # Create engine with retry (Docker race with Postgres)
        self.engine = self._make_engine_with_retry(self.database_url)
        Session = sessionmaker(bind=self.engine)
        self.db_session = Session()

        # Verify tables exist (don’t crash if missing)
        try:
            self.db_session.execute(text("SELECT 1 FROM cap_alerts LIMIT 1"))
            self.logger.info("Database tables verified successfully")
        except Exception as e:
            self.logger.warning(f"Database table verification failed: {e}")

        self.location_settings = self._load_location_settings()
        self.location_name = f"{self.location_settings['county_name']}, {self.location_settings['state_code']}".strip(', ')
        self.county_upper = self.location_settings['county_name'].upper()
        self.state_code = self.location_settings['state_code']

        # EAS broadcaster
        self.eas_broadcaster = None
        try:
            eas_config = load_eas_config(PROJECT_ROOT)
            self.eas_broadcaster = EASBroadcaster(
                self.db_session, EASMessage, eas_config, self.logger, self.location_settings
            )
        except Exception as exc:
            self.logger.warning(f"EAS broadcaster unavailable: {exc}")
            self.eas_broadcaster = None

        # HTTP Session
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': f"NOAA CAP Alert System/1.0 ({self.location_name})"
        })

        # LED
        self.led_controller = None
        if led_sign_ip and LED_AVAILABLE:
            try:
                self.led_controller = LEDSignController(led_sign_ip, led_sign_port, location_settings=self.location_settings)
                self.logger.info(f"LED sign controller initialized for {led_sign_ip}:{led_sign_port}")
            except Exception as e:
                self.logger.error(f"Failed to initialize LED controller: {e}")
        elif led_sign_ip:
            self.logger.warning("LED sign IP provided but controller not available")

        # Endpoints
        self.cap_endpoints = [
            f"https://api.weather.gov/alerts/active?zone={code}"
            for code in self.location_settings['zone_codes']
        ] or [
            f"https://api.weather.gov/alerts/active?zone={code}"
            for code in DEFAULT_LOCATION_SETTINGS['zone_codes']
        ]

        # Strict location terms
        base_identifiers = self.location_settings['area_terms'] or list(DEFAULT_LOCATION_SETTINGS['area_terms'])
        derived_identifiers = {self.county_upper}
        if 'COUNTY' not in self.county_upper:
            derived_identifiers.add(f"{self.county_upper} COUNTY")
        derived_identifiers.add(self.county_upper.replace(' COUNTY', ''))
        self.putnam_county_identifiers = list({term for term in base_identifiers if term} | derived_identifiers)
        self.zone_codes = set(self.location_settings['zone_codes'])

    # ---------- Engine with retry ----------
    def _load_location_settings(self) -> Dict[str, Any]:
        defaults = dict(DEFAULT_LOCATION_SETTINGS)
        settings: Dict[str, Any] = dict(defaults)

        try:
            record = self.db_session.query(LocationSettings).order_by(LocationSettings.id).first()
            if record:
                settings.update({
                    'county_name': record.county_name or defaults['county_name'],
                    'state_code': (record.state_code or defaults['state_code']).upper(),
                    'timezone': record.timezone or defaults['timezone'],
                    'zone_codes': normalise_upper(record.zone_codes) or list(defaults['zone_codes']),
                    'area_terms': normalise_upper(record.area_terms) or list(defaults['area_terms']),
                    'map_center_lat': record.map_center_lat or defaults['map_center_lat'],
                    'map_center_lng': record.map_center_lng or defaults['map_center_lng'],
                    'map_default_zoom': record.map_default_zoom or defaults['map_default_zoom'],
                    'led_default_lines': ensure_list(record.led_default_lines) or list(defaults['led_default_lines']),
                })
            else:
                self.logger.info("No location settings found; using defaults")
        except Exception as exc:  # pragma: no cover - defensive logging
            self.logger.warning("Falling back to default location settings: %s", exc)

        if not settings['zone_codes']:
            settings['zone_codes'] = list(defaults['zone_codes'])
        if not settings['area_terms']:
            settings['area_terms'] = list(defaults['area_terms'])

        set_location_timezone(settings['timezone'])
        return settings

    # ---------- Engine with retry ----------
    def _make_engine_with_retry(self, url: str, retries: int = 30, delay: float = 2.0):
        last_err = None
        for attempt in range(1, retries + 1):
            try:
                engine = create_engine(url, pool_pre_ping=True, pool_recycle=3600, future=True)
                with engine.connect() as conn:
                    conn.execute(text("SELECT 1"))
                self.logger.info("Connected to database")
                return engine
            except OperationalError as e:
                last_err = e
                self.logger.warning("Database not ready (attempt %d/%d): %s", attempt, retries, str(e).strip())
                time.sleep(delay)
        raise last_err

    # ---------- Fetch ----------
    def fetch_cap_alerts(self, timeout: int = 30) -> List[Dict]:
        unique_alerts = []
        seen_identifiers = set()

        for endpoint in self.cap_endpoints:
            try:
                self.logger.info(f"Fetching alerts from: {endpoint}")
                r = self.session.get(endpoint, timeout=timeout)
                r.raise_for_status()
                data = r.json()
                features = data.get('features', [])
                self.logger.info(f"Retrieved {len(features)} alerts from {endpoint}")
                for alert in features:
                    props = alert.get('properties', {})
                    identifier = props.get('identifier')
                    if identifier and identifier not in seen_identifiers:
                        seen_identifiers.add(identifier)
                        unique_alerts.append(alert)
                    elif not identifier:
                        self.logger.warning("Alert has no identifier, including anyway")
                        unique_alerts.append(alert)
            except requests.exceptions.RequestException as e:
                self.logger.error(f"Error fetching from {endpoint}: {str(e)}")
            except json.JSONDecodeError as e:
                self.logger.error(f"JSON decode error from {endpoint}: {str(e)}")
            except Exception as e:
                self.logger.error(f"Unexpected error fetching from {endpoint}: {str(e)}")

        self.logger.info(f"Total unique alerts collected: {len(unique_alerts)}")
        return unique_alerts

    # ---------- Relevance ----------
    def is_relevant_alert(self, alert_data: Dict) -> bool:
        try:
            properties = alert_data.get('properties', {})
            event = properties.get('event', 'Unknown')
            geocode = properties.get('geocode', {})
            ugc_codes = geocode.get('UGC', []) or []

            for ugc in ugc_codes:
                if str(ugc).upper() in self.zone_codes:
                    self.logger.info(f"✓ Alert ACCEPTED by UGC: {event} ({ugc})")
                    return True

            area_desc = (properties.get('areaDesc') or '').upper()
            matched_terms = [term for term in self.putnam_county_identifiers if term and term in area_desc]
            if matched_terms:
                self.logger.info(f"✓ Alert ACCEPTED by area match: {event} ({matched_terms[0]})")
                return True

            self.logger.info(f"✗ REJECT (not specific enough for {self.county_upper}): {event} - {area_desc}")
            return False
        except Exception as e:
            self.logger.error(f"Error checking relevance: {e}")
            return False

    # ---------- Parse ----------
    def parse_cap_alert(self, alert_data: Dict) -> Optional[Dict]:
        try:
            properties = alert_data.get('properties', {})
            geometry = alert_data.get('geometry')
            identifier = properties.get('identifier')
            if not identifier:
                event = properties.get('event', 'Unknown')
                sent = properties.get('sent', str(time.time()))
                identifier = f"temp_{hashlib.md5((event + sent).encode()).hexdigest()[:16]}"

            sent = parse_nws_datetime(properties.get('sent')) if properties.get('sent') else None
            expires = parse_nws_datetime(properties.get('expires')) if properties.get('expires') else None

            area_desc = properties.get('areaDesc', '')
            if isinstance(area_desc, list):
                area_desc = '; '.join(area_desc)

            parsed = {
                'identifier': identifier,
                'sent': sent or utc_now(),
                'expires': expires,
                'status': properties.get('status', 'Unknown'),
                'message_type': properties.get('messageType', 'Unknown'),
                'scope': properties.get('scope', 'Unknown'),
                'category': properties.get('category', 'Unknown'),
                'event': properties.get('event', 'Unknown'),
                'urgency': properties.get('urgency', 'Unknown'),
                'severity': properties.get('severity', 'Unknown'),
                'certainty': properties.get('certainty', 'Unknown'),
                'area_desc': area_desc,
                'headline': properties.get('headline', ''),
                'description': properties.get('description', ''),
                'instruction': properties.get('instruction', ''),
                'raw_json': alert_data,
                '_geometry_data': geometry,
            }
            self.logger.info(f"Parsed alert: {identifier} - {parsed['event']}")
            return parsed
        except Exception as e:
            self.logger.error(f"Error parsing CAP alert: {e}")
            return None

    # ---------- Save / Geometry / Intersections ----------
    def _set_alert_geometry(self, alert: CAPAlert, geometry_data: Optional[Dict]):
        try:
            if geometry_data and isinstance(geometry_data, dict):
                geom_json = json.dumps(geometry_data)
                result = self.db_session.execute(
                    text("SELECT ST_SetSRID(ST_GeomFromGeoJSON(:g), 4326)"),
                    {"g": geom_json}
                ).scalar()
                alert.geom = result
                self.logger.debug(f"Geometry set for alert {alert.identifier}")
            else:
                alert.geom = None
                self.logger.debug(f"No geometry for alert {alert.identifier}")
        except Exception as e:
            self.logger.warning(f"Could not set geometry for alert {getattr(alert,'identifier','?')}: {e}")
            alert.geom = None

    def _needs_intersection_calculation(self, alert: CAPAlert) -> bool:
        if not alert.geom:
            return False
        try:
            cnt = self.db_session.query(Intersection).filter_by(cap_alert_id=alert.id).count()
            return cnt == 0
        except Exception:
            return True

    def process_intersections(self, alert: CAPAlert):
        try:
            if not alert.geom:
                return
            self.db_session.query(Intersection).filter_by(cap_alert_id=alert.id).delete()
            boundaries = self.db_session.query(Boundary).filter(Boundary.geom.isnot(None)).all()

            created = 0
            with_area = 0
            for boundary in boundaries:
                try:
                    res = self.db_session.query(
                        func.ST_Intersects(alert.geom, boundary.geom).label('intersects'),
                        func.ST_Area(func.ST_Intersection(alert.geom, boundary.geom)).label('ia')
                    ).first()
                    if res and res.intersects:
                        ia = float(res.ia or 0)
                        self.db_session.add(Intersection(
                            cap_alert_id=alert.id, boundary_id=boundary.id,
                            intersection_area=ia, created_at=utc_now()
                        ))
                        created += 1
                        if ia > 0:
                            with_area += 1
                except Exception as be:
                    self.logger.warning(f"Intersection error with boundary {boundary.id}: {be}")

            self.db_session.commit()
            if created:
                self.logger.info(f"Intersections for alert {alert.identifier}: {created} ({with_area} > 0 area)")
        except Exception as e:
            self.db_session.rollback()
            self.logger.error(f"Error processing intersections for alert {alert.id}: {e}")

    def save_cap_alert(self, alert_data: Dict) -> Tuple[bool, Optional[CAPAlert]]:
        try:
            payload = dict(alert_data)
            geometry_data = payload.pop('_geometry_data', None)
            existing = self.db_session.query(CAPAlert).filter_by(
                identifier=payload['identifier']
            ).first()

            if existing:
                for k, v in payload.items():
                    if k != 'raw_json' and hasattr(existing, k):
                        setattr(existing, k, v)
                old_geom = existing.geom
                self._set_alert_geometry(existing, geometry_data)
                existing.updated_at = utc_now()
                self.db_session.commit()
                if (existing.geom != old_geom) or self._needs_intersection_calculation(existing):
                    self.process_intersections(existing)
                if self.led_controller and not self.is_alert_expired(existing):
                    self.update_led_display()
                self.logger.info(f"Updated alert: {existing.event}")
                return False, existing

            new_alert = CAPAlert(**payload)
            new_alert.created_at = utc_now()
            new_alert.updated_at = utc_now()
            self._set_alert_geometry(new_alert, geometry_data)

            self.db_session.add(new_alert)
            self.db_session.commit()

            if new_alert.geom:
                self.process_intersections(new_alert)
            if self.led_controller and not self.is_alert_expired(new_alert):
                self.update_led_display()

            if self.eas_broadcaster:
                try:
                    self.eas_broadcaster.handle_alert(new_alert, payload)
                except Exception as exc:
                    self.logger.error(f"EAS broadcast failed for {new_alert.identifier}: {exc}")

            self.logger.info(f"Saved new alert: {new_alert.identifier} - {new_alert.event}")
            return True, new_alert

        except SQLAlchemyError as e:
            self.logger.error(f"Database error saving alert: {e}")
            self.db_session.rollback()
            return False, None
        except Exception as e:
            self.logger.error(f"Error saving CAP alert: {e}")
            self.db_session.rollback()
            return False, None

    # ---------- LED ----------
    def is_alert_expired(self, alert) -> bool:
        return bool(getattr(alert, 'expires', None) and alert.expires < utc_now())

    def update_led_display(self):
        if not self.led_controller:
            return
        try:
            active = self.db_session.query(CAPAlert).filter(
                or_(CAPAlert.expires.is_(None), CAPAlert.expires > utc_now())
            ).order_by(CAPAlert.severity.desc(), CAPAlert.sent.desc()).limit(5).all()

            if active:
                self.led_controller.display_alerts(active)
                self.logger.info(f"Updated LED with {len(active)} active alerts")
            else:
                self.led_controller.display_default_message()
                self.logger.info("Updated LED with default message (no active alerts)")
        except Exception as e:
            self.logger.error(f"LED update failed: {e}")

    # ---------- Maintenance ----------
    def fix_existing_geometry(self) -> Dict:
        stats = {'total_alerts': 0, 'alerts_with_raw_json': 0, 'geometry_extracted': 0,
                 'geometry_set': 0, 'intersections_calculated': 0, 'errors': 0}
        try:
            alerts = self.db_session.query(CAPAlert).filter(
                CAPAlert.raw_json.isnot(None), CAPAlert.geom.is_(None)
            ).all()
            stats['total_alerts'] = len(alerts)
            self.logger.info(f"Found {len(alerts)} alerts to fix")
            for alert in alerts:
                try:
                    stats['alerts_with_raw_json'] += 1
                    raw = alert.raw_json
                    if isinstance(raw, dict) and 'geometry' in raw:
                        stats['geometry_extracted'] += 1
                        self._set_alert_geometry(alert, raw['geometry'])
                        if alert.geom is not None:
                            stats['geometry_set'] += 1
                            self.process_intersections(alert)
                            cnt = self.db_session.query(Intersection).filter_by(cap_alert_id=alert.id).count()
                            stats['intersections_calculated'] += cnt
                except Exception as e:
                    stats['errors'] += 1
                    self.logger.error(f"Fix geometry error for {alert.identifier}: {e}")
            self.db_session.commit()
            self.logger.info(f"Geometry fix: {stats['geometry_set']} alerts fixed")
        except Exception as e:
            self.logger.error(f"fix_existing_geometry failed: {e}")
            self.db_session.rollback()
            stats['errors'] += 1
        return stats

    def cleanup_old_poll_history(self):
        try:
            # Ensure table exists
            try:
                self.db_session.execute(text("SELECT 1 FROM poll_history LIMIT 1"))
            except Exception:
                self.logger.debug("poll_history missing; skipping cleanup")
                return

            cutoff = utc_now() - timedelta(days=30)
            old_count = self.db_session.query(PollHistory).filter(PollHistory.timestamp < cutoff).count()
            if old_count > 100:
                subq = self.db_session.query(PollHistory.id).order_by(PollHistory.timestamp.desc()).limit(100).subquery()
                self.db_session.query(PollHistory).filter(
                    PollHistory.timestamp < cutoff, ~PollHistory.id.in_(subq)
                ).delete(synchronize_session=False)
                self.db_session.commit()
                self.logger.info("Cleaned old poll history")
        except Exception as e:
            self.logger.error(f"cleanup_old_poll_history error: {e}")
            try: self.db_session.rollback()
            except: pass

    def log_poll_history(self, stats):
        try:
            try:
                self.db_session.execute(text("SELECT 1 FROM poll_history LIMIT 1"))
            except Exception:
                self.logger.debug("poll_history missing; file-only log")
                return
            rec = PollHistory(
                timestamp=utc_now(),
                alerts_fetched=stats.get('alerts_fetched', 0),
                alerts_new=stats.get('alerts_new', 0),
                alerts_updated=stats.get('alerts_updated', 0),
                execution_time_ms=stats.get('execution_time_ms', 0),
                status=stats.get('status', 'UNKNOWN'),
                error_message=stats.get('error_message'),
            )
            self.db_session.add(rec)
            self.db_session.commit()
        except Exception as e:
            self.logger.error(f"log_poll_history error: {e}")
            try: self.db_session.rollback()
            except: pass

    def log_system_event(self, level: str, message: str, details: Dict = None):
        try:
            try:
                self.db_session.execute(text("SELECT 1 FROM system_log LIMIT 1"))
            except Exception:
                self.logger.debug("system_log missing; file-only log")
                return
            details = details or {}
            details.update({
                'logged_at_utc': utc_now().isoformat(),
                'logged_at_local': local_now().isoformat(),
                'timezone': self.location_settings['timezone']
            })
            entry = SystemLog(level=level, message=message, module='cap_poller',
                              details=details, timestamp=utc_now())
            self.db_session.add(entry)
            self.db_session.commit()
        except Exception as e:
            self.logger.error(f"log_system_event error: {e}")
            try: self.db_session.rollback()
            except: pass

    # ---------- Main poll ----------
    def poll_and_process(self) -> Dict:
        start = time.time()
        poll_start_utc = utc_now()
        poll_start_local = local_now()

        stats = {
            'alerts_fetched': 0, 'alerts_new': 0, 'alerts_updated': 0,
            'alerts_filtered': 0, 'alerts_accepted': 0, 'intersections_calculated': 0,
            'execution_time_ms': 0, 'status': 'SUCCESS', 'error_message': None,
            'zone': f"{'/'.join(self.location_settings['zone_codes'])} ({self.location_name}) - STRICT FILTERING",
            'poll_time_utc': poll_start_utc.isoformat(),
            'poll_time_local': poll_start_local.isoformat(),
            'timezone': self.location_settings['timezone'], 'led_updated': False
        }

        try:
            self.logger.info(
                f"Starting CAP alert polling cycle for {self.location_name} at {format_local_datetime(poll_start_utc)}"
            )

            alerts_data = self.fetch_cap_alerts()
            stats['alerts_fetched'] = len(alerts_data)

            for alert_data in alerts_data:
                props = alert_data.get('properties', {})
                event = props.get('event', 'Unknown')
                alert_id = props.get('identifier', 'No ID')

                self.logger.info(f"Processing alert: {event} (ID: {alert_id[:20] if alert_id!='No ID' else 'No ID'}...)")

                if not self.is_relevant_alert(alert_data):
                    self.logger.info(f"• Filtered out (not specific to {self.county_upper})")
                    stats['alerts_filtered'] += 1
                    continue

                stats['alerts_accepted'] += 1
                parsed = self.parse_cap_alert(alert_data)
                if not parsed:
                    self.logger.warning(f"Failed to parse: {event}")
                    continue

                is_new, alert = self.save_cap_alert(parsed)
                if is_new:
                    stats['alerts_new'] += 1
                    stats['led_updated'] = True
                    self.logger.info(
                        f"Saved new {self.location_name} alert: {alert.event if alert else parsed['event']} - Sent: {format_local_datetime(parsed.get('sent'))}"
                    )
                else:
                    stats['alerts_updated'] += 1
                    self.logger.info(
                        f"Updated {self.location_name} alert: {alert.event if alert else parsed['event']} - Sent: {format_local_datetime(parsed.get('sent'))}"
                    )

            self.cleanup_old_poll_history()
            self.log_poll_history(stats)

            if self.led_controller:
                self.update_led_display()
                stats['led_updated'] = True

            stats['execution_time_ms'] = int((time.time() - start) * 1000)
            self.logger.info(
                f"Polling cycle completed: {stats['alerts_accepted']} accepted, {stats['alerts_new']} new, {stats['alerts_updated']} updated, {stats['alerts_filtered']} filtered"
            )
            self.log_system_event('INFO', f"CAP polling successful: {stats['alerts_new']} new alerts", stats)

        except Exception as e:
            stats['status'] = 'ERROR'
            stats['error_message'] = str(e)
            stats['execution_time_ms'] = int((time.time() - start) * 1000)
            self.logger.error(f"Error in polling cycle: {e}")
            self.log_system_event('ERROR', f"CAP polling failed: {e}", stats)

        return stats

    def close(self):
        try:
            if hasattr(self, 'db_session'):
                self.db_session.close()
        finally:
            if hasattr(self, 'session'):
                self.session.close()
            if self.led_controller:
                try: self.led_controller.close()
                except: pass

# =======================================================================================
# Main
# =======================================================================================

def build_database_url_from_env() -> str:
    # Highest priority: DATABASE_URL
    url = os.getenv("DATABASE_URL")
    if url:
        return url
    # Else compose from parts (Docker-safe defaults)
    host = os.getenv("POSTGRES_HOST", "postgresql")       # IMPORTANT: service name, not localhost
    port = os.getenv("POSTGRES_PORT", "5432")
    db   = os.getenv("POSTGRES_DB", "casaos")
    user = os.getenv("POSTGRES_USER", "casaos")
    pw   = os.getenv("POSTGRES_PASSWORD", "casaos")
    # Use psycopg2 driver explicitly for SQLAlchemy
    return f"postgresql+psycopg2://{user}:{pw}@{host}:{port}/{db}"

def main():
    parser = argparse.ArgumentParser(description='NOAA CAP Alert Poller (configurable location)')
    parser.add_argument('--database-url',
                        default=build_database_url_from_env(),
                        help='SQLAlchemy DB URL (defaults from env POSTGRES_* or DATABASE_URL)')
    parser.add_argument('--led-ip', help='LED sign IP address')
    parser.add_argument('--led-port', type=int, default=10001, help='LED sign port (default: 10001)')
    parser.add_argument('--log-level', default=os.getenv('LOG_LEVEL', 'INFO'),
                        choices=['DEBUG', 'INFO', 'WARNING', 'ERROR'], help='Logging level')
    parser.add_argument('--continuous', action='store_true', help='Run continuously')
    parser.add_argument('--interval', type=int, default=int(os.getenv('POLL_INTERVAL_SEC', '300')),
                        help='Polling interval seconds (default: 300)')
    parser.add_argument('--fix-geometry', action='store_true', help='Fix geometry for existing alerts and exit')
    args = parser.parse_args()

    # Logging to stdout (container-friendly)
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[logging.StreamHandler(sys.stdout)]
    )
    logger = logging.getLogger(__name__)

    startup_utc = utc_now()
    logger.info("Starting NOAA CAP Alert Poller with LED Integration - PUTNAM COUNTY STRICT MODE")
    logger.info(f"Startup time: {format_local_datetime(startup_utc)}")
    if args.led_ip:
        logger.info(f"LED Sign: {args.led_ip}:{args.led_port}")

    poller = CAPPoller(args.database_url, args.led_ip, args.led_port)

    try:
        if args.fix_geometry:
            logger.info("Running geometry fix for existing alerts...")
            stats = poller.fix_existing_geometry()
            print(json.dumps(stats, indent=2))
        elif args.continuous:
            logger.info(f"Running continuously with {args.interval} second intervals")
            while True:
                try:
                    stats = poller.poll_and_process()
                    print(json.dumps(stats, indent=2))
                    time.sleep(args.interval)
                except KeyboardInterrupt:
                    logger.info("Received interrupt signal, shutting down")
                    break
                except Exception as e:
                    logger.error(f"Error in continuous polling: {e}")
                    time.sleep(60)
        else:
            stats = poller.poll_and_process()
            print(json.dumps(stats, indent=2))
    finally:
        poller.close()

if __name__ == '__main__':
    main()
