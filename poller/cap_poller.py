#!/usr/bin/env python3
"""
NOAA CAP Alert Poller with configurable location filtering
Docker-safe DB defaults, strict jurisdiction filtering, PostGIS geometry/intersections,
optional LED sign integration.

Database Configuration (via environment variables or --database-url):
  POSTGRES_HOST      - Database host (default: host.docker.internal; override for Docker services)
  POSTGRES_PORT      - Database port (default: 5432)
  POSTGRES_DB        - Database name (defaults to POSTGRES_USER)
  POSTGRES_USER      - Database user (default: postgres)
  POSTGRES_PASSWORD  - Database password (optional, recommended)
  DATABASE_URL       - Or provide full connection string to override individual vars

All database credentials should be explicitly configured via environment variables when available.
No default passwords are provided for security.
"""

import os
import sys
import time
import json
import re
import uuid
import requests
import logging
import hashlib
import math
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple
import argparse

import pytz
import certifi
from dotenv import load_dotenv
from urllib.parse import quote

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(CURRENT_DIR, os.pardir))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# Load from CONFIG_PATH if set (persistent volume), with override=True
_config_path = os.environ.get('CONFIG_PATH')
if _config_path:
    load_dotenv(_config_path, override=True)
else:
    load_dotenv(override=True)
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
from app_utils.alert_sources import (
    ALERT_SOURCE_IPAWS,
    ALERT_SOURCE_NOAA,
    ALERT_SOURCE_UNKNOWN,
    normalize_alert_source,
    summarise_sources,
)
from app_utils.location_settings import (
    DEFAULT_LOCATION_SETTINGS,
    ensure_list,
    normalise_upper,
    sanitize_fips_codes,
)
from app_utils.eas import EASBroadcaster, load_eas_config
from app_core.radio import RadioManager, ensure_radio_tables

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
    from scripts.led_sign_controller import LEDSignController as _LED
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
    from app import (
        db,
        CAPAlert,
        SystemLog,
        Boundary,
        Intersection,
        LocationSettings,
        EASMessage,
        PollDebugRecord,
        RadioReceiver,
        RadioReceiverStatus,
    )  # type: ignore
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
    from sqlalchemy import (
        Column,
        Integer,
        String,
        DateTime,
        Text,
        JSON,
        Boolean,
        Float,
        ForeignKey,
        LargeBinary,
    )
    from sqlalchemy.orm import declarative_base
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
        source = Column(String(32), nullable=False, default=ALERT_SOURCE_UNKNOWN)
        created_at = Column(DateTime, default=utc_now)
        updated_at = Column(DateTime, default=utc_now)

        def __setattr__(self, name, value):  # pragma: no cover
            if name == 'source':
                value = normalize_alert_source(value)
            super().__setattr__(name, value)

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
        data_source = Column(String(64))

    class PollDebugRecord(Base):
        __tablename__ = 'poll_debug_records'
        __table_args__ = {'extend_existing': True}
        id = Column(Integer, primary_key=True)
        created_at = Column(DateTime, default=utc_now)
        poll_run_id = Column(String(64), index=True)
        poll_started_at = Column(DateTime, nullable=False)
        poll_status = Column(String(20), default='UNKNOWN')
        data_source = Column(String(64))
        alert_identifier = Column(String(255))
        alert_event = Column(String(255))
        alert_sent = Column(DateTime)
        source = Column(String(64))
        is_relevant = Column(Boolean, default=False)
        relevance_reason = Column(String(255))
        relevance_matches = Column(JSON)
        ugc_codes = Column(JSON)
        area_desc = Column(Text)
        was_saved = Column(Boolean, default=False)
        was_new = Column(Boolean, default=False)
        alert_db_id = Column(Integer)
        parse_success = Column(Boolean, default=False)
        parse_error = Column(Text)
        polygon_count = Column(Integer)
        geometry_type = Column(String(64))
        geometry_geojson = Column(JSON)
        geometry_preview = Column(JSON)
        raw_properties = Column(JSON)
        raw_xml_present = Column(Boolean, default=False)
        notes = Column(Text)

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
        audio_data = Column(LargeBinary)
        eom_audio_data = Column(LargeBinary)
        text_payload = Column(JSON)
        created_at = Column(DateTime, default=utc_now)
        # Use metadata_payload column name to match the migration
        metadata_payload = Column(JSON)

    class RadioReceiver(Base):
        __tablename__ = 'radio_receivers'
        __table_args__ = {'extend_existing': True}

        id = Column(Integer, primary_key=True)
        identifier = Column(String(64), unique=True, nullable=False)
        display_name = Column(String(128), nullable=False)
        driver = Column(String(64), nullable=False)
        frequency_hz = Column(Float, nullable=False)
        sample_rate = Column(Integer, nullable=False)
        gain = Column(Float)
        channel = Column(Integer)
        serial = Column(String(128))
        auto_start = Column(Boolean, nullable=False, default=True)
        enabled = Column(Boolean, nullable=False, default=True)
        notes = Column(Text)
        created_at = Column(DateTime, default=utc_now)
        updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)

        def to_receiver_config(self):  # pragma: no cover - compatibility shim
            from app_core.radio import ReceiverConfig

            return ReceiverConfig(
                identifier=self.identifier,
                driver=self.driver,
                frequency_hz=float(self.frequency_hz),
                sample_rate=int(self.sample_rate),
                gain=self.gain,
                channel=self.channel,
                serial=self.serial,
                enabled=bool(self.enabled),
                auto_start=bool(self.auto_start),
            )

    class RadioReceiverStatus(Base):
        __tablename__ = 'radio_receiver_status'
        __table_args__ = {'extend_existing': True}

        id = Column(Integer, primary_key=True)
        receiver_id = Column(
            Integer,
            ForeignKey('radio_receivers.id', ondelete='CASCADE'),
            nullable=False,
        )
        reported_at = Column(DateTime, default=utc_now, nullable=False)
        locked = Column(Boolean, default=False, nullable=False)
        signal_strength = Column(Float)
        last_error = Column(Text)
        capture_mode = Column(String(16))
        capture_path = Column(String(255))


# =======================================================================================
# Poller
# =======================================================================================

class CAPPoller:
    """CAP alert poller with strict location filtering, PostGIS, optional LED."""

    def __init__(
        self,
        database_url: str,
        led_sign_ip: str = None,
        led_sign_port: int = 10001,
        cap_endpoints: Optional[List[str]] = None,
    ):
        self.database_url = database_url
        self.led_sign_ip = led_sign_ip
        self.led_sign_port = led_sign_port

        self.logger = logging.getLogger(__name__)

        # Create engine with retry (Docker race with Postgres)
        self.engine = self._make_engine_with_retry(self.database_url)
        Session = sessionmaker(bind=self.engine)
        self.db_session = Session()

        self.last_poll_sources: List[str] = []
        self.last_duplicates_filtered: int = 0

        # Verify tables exist (don’t crash if missing)
        try:
            self.db_session.execute(text("SELECT 1 FROM cap_alerts LIMIT 1"))
            self.logger.info("Database tables verified successfully")
        except Exception as e:
            self.logger.warning(f"Database table verification failed: {e}")

        self._ensure_source_columns()
        self._debug_table_checked = False
        self._ensure_debug_records_table()

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
        default_user_agent = os.getenv(
            'NOAA_USER_AGENT',
            'KR8MER Emergency Alert Hub/2.1 (+https://github.com/KR8MER/eas-station; NOAA+IPAWS)',
        )
        self.session.headers.update({
            'User-Agent': default_user_agent,
        })
        ca_bundle_override = os.getenv('REQUESTS_CA_BUNDLE') or os.getenv('CAP_POLLER_CA_BUNDLE')
        if ca_bundle_override:
            self.logger.debug('Using custom CA bundle for CAP polling: %s', ca_bundle_override)
            self.session.verify = ca_bundle_override
        else:
            self.session.verify = certifi.where()

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

        # Radio manager configuration
        self.radio_manager: Optional[RadioManager] = None
        self._radio_receiver_cache: Dict[str, RadioReceiver] = {}
        capture_dir_env = os.getenv("RADIO_CAPTURE_DIR", os.path.join(PROJECT_ROOT, "radio_captures"))
        self.radio_capture_dir = Path(capture_dir_env)
        try:
            self.radio_capture_dir.mkdir(parents=True, exist_ok=True)
        except Exception as exc:
            self.logger.warning("Unable to create radio capture directory %s: %s", self.radio_capture_dir, exc)

        capture_mode = (os.getenv("RADIO_CAPTURE_MODE", "iq") or "iq").lower()
        if capture_mode not in {"iq", "pcm"}:
            self.logger.warning("Unsupported RADIO_CAPTURE_MODE '%s'; defaulting to 'iq'", capture_mode)
            capture_mode = "iq"
        self.radio_capture_mode = capture_mode

        try:
            self.radio_capture_duration = max(1.0, float(os.getenv("RADIO_CAPTURE_DURATION", "30")))
        except ValueError:
            self.logger.warning("Invalid RADIO_CAPTURE_DURATION; defaulting to 30 seconds")
            self.radio_capture_duration = 30.0

        self._setup_radio_manager()

        # Endpoint configuration & defaults
        self.poller_mode = (os.getenv('CAP_POLLER_MODE', 'NOAA') or 'NOAA').strip().upper()

        configured_endpoints: List[str] = []

        def _extend_from_csv(csv_value: Optional[str]) -> None:
            if not csv_value:
                return
            for endpoint in csv_value.split(','):
                cleaned = endpoint.strip()
                if cleaned:
                    configured_endpoints.append(cleaned)

        _extend_from_csv(os.getenv('CAP_ENDPOINTS'))
        _extend_from_csv(os.getenv('IPAWS_CAP_FEED_URLS'))

        if cap_endpoints:
            configured_endpoints.extend([endpoint for endpoint in cap_endpoints if endpoint])

        if configured_endpoints:
            # Preserve order but remove duplicates
            seen: Set[str] = set()
            unique_endpoints: List[str] = []
            for endpoint in configured_endpoints:
                if endpoint not in seen:
                    unique_endpoints.append(endpoint)
                    seen.add(endpoint)
            self.cap_endpoints = unique_endpoints
        else:
            if self.poller_mode == 'IPAWS':
                lookback_hours = os.getenv('IPAWS_DEFAULT_LOOKBACK_HOURS', '12')
                try:
                    lookback_hours_int = max(1, int(lookback_hours))
                except ValueError:
                    lookback_hours_int = 12

                default_start = (utc_now() - timedelta(hours=lookback_hours_int)).strftime('%Y-%m-%dT%H:%M:%SZ')
                override_start = (os.getenv('IPAWS_DEFAULT_START') or '').strip()
                if override_start:
                    default_start = override_start

                endpoint_template = (
                    os.getenv(
                        'IPAWS_DEFAULT_ENDPOINT_TEMPLATE',
                        'https://tdl.apps.fema.gov/IPAWSOPEN_EAS_SERVICE/rest/public/recent/{timestamp}',
                    )
                    or 'https://tdl.apps.fema.gov/IPAWSOPEN_EAS_SERVICE/rest/public/recent/{timestamp}'
                )
                try:
                    default_endpoint = endpoint_template.format(timestamp=default_start)
                except Exception:
                    default_endpoint = endpoint_template

                self.cap_endpoints = [default_endpoint]
                self.logger.info(
                    "No CAP endpoints configured; defaulting to FEMA IPAWS public feed starting %s",
                    default_start,
                )
            else:
                self.cap_endpoints = [
                    f"https://api.weather.gov/alerts/active?zone={code}"
                    for code in self.location_settings['zone_codes']
                ] or [
                    f"https://api.weather.gov/alerts/active?zone={code}"
                    for code in DEFAULT_LOCATION_SETTINGS['zone_codes']
                ]

        self.zone_codes = set(self.location_settings['zone_codes'])
        fips_codes, _ = sanitize_fips_codes(self.location_settings.get('fips_codes'))
        self.same_codes = {code for code in fips_codes if code}

    # ---------- Engine with retry ----------
    def _ensure_source_columns(self):
        try:
            changed = False

            cap_alerts_has_source = self.db_session.execute(
                text(
                    """
                    SELECT 1
                    FROM information_schema.columns
                    WHERE table_name = 'cap_alerts'
                      AND column_name = 'source'
                      AND table_schema = current_schema()
                    """
                )
            ).scalar()

            if not cap_alerts_has_source:
                self.logger.info("Adding cap_alerts.source column for alert provenance tracking")
                self.db_session.execute(text("ALTER TABLE cap_alerts ADD COLUMN source VARCHAR(32)"))
                self.db_session.execute(
                    text("UPDATE cap_alerts SET source = :default WHERE source IS NULL"),
                    {"default": ALERT_SOURCE_NOAA},
                )
                self.db_session.execute(
                    text("ALTER TABLE cap_alerts ALTER COLUMN source SET DEFAULT :default"),
                    {"default": ALERT_SOURCE_UNKNOWN},
                )
                self.db_session.execute(text("ALTER TABLE cap_alerts ALTER COLUMN source SET NOT NULL"))
                changed = True

            poll_history_has_source = self.db_session.execute(
                text(
                    """
                    SELECT 1
                    FROM information_schema.columns
                    WHERE table_name = 'poll_history'
                      AND column_name = 'data_source'
                      AND table_schema = current_schema()
                    """
                )
            ).scalar()

            if not poll_history_has_source:
                self.logger.info("Adding poll_history.data_source column for polling metadata")
                self.db_session.execute(text("ALTER TABLE poll_history ADD COLUMN data_source VARCHAR(64)"))
                changed = True

            if changed:
                self.db_session.commit()
        except Exception as exc:
            self.logger.warning("Could not ensure source columns exist: %s", exc)
            try:
                self.db_session.rollback()
            except Exception as rollback_exc:
                self.logger.debug("Rollback failed during source column check: %s", rollback_exc)

    def _ensure_debug_records_table(self) -> bool:
        if getattr(self, "_debug_table_checked", False):
            return self._debug_table_checked
        try:
            PollDebugRecord.__table__.create(bind=self.engine, checkfirst=True)
            self._debug_table_checked = True
        except Exception as exc:
            self.logger.debug("Could not ensure poll_debug_records table: %s", exc)
            self._debug_table_checked = False
        return self._debug_table_checked

    def _setup_radio_manager(self) -> None:
        try:
            if not ensure_radio_tables(self.logger):
                self.logger.warning("Radio receiver tables unavailable; skipping capture orchestration")
                return
        except RuntimeError as exc:
            self.logger.debug("Falling back to manual radio table creation: %s", exc)
            try:
                RadioReceiver.__table__.create(bind=self.engine, checkfirst=True)
                RadioReceiverStatus.__table__.create(bind=self.engine, checkfirst=True)
            except Exception as table_exc:
                self.logger.warning("Unable to create radio tables manually: %s", table_exc)
                return
        except Exception as exc:
            self.logger.warning("Unable to verify radio tables: %s", exc)
            return

        try:
            manager = RadioManager()
            manager.register_builtin_drivers()
        except Exception as exc:
            self.logger.warning("Radio manager unavailable: %s", exc)
            return

        self.radio_manager = manager
        self._refresh_radio_configuration(initial=True)

    def _refresh_radio_configuration(self, initial: bool = False) -> None:
        if not self.radio_manager:
            return

        try:
            receivers = (
                self.db_session.query(RadioReceiver)
                .order_by(RadioReceiver.identifier)
                .all()
            )
        except Exception as exc:
            self.logger.error("Failed to load radio receivers: %s", exc)
            return

        cache: Dict[str, RadioReceiver] = {}
        configs = []
        for receiver in receivers:
            identifier = receiver.identifier
            if not identifier:
                continue
            cache[identifier] = receiver
            try:
                configs.append(receiver.to_receiver_config())
            except Exception as exc:
                self.logger.error("Invalid receiver %s: %s", identifier, exc)

        try:
            self.radio_manager.configure_receivers(configs)
            self._radio_receiver_cache = cache
            if configs:
                self.radio_manager.start_all()
        except Exception as exc:
            self.logger.error("Failed to configure radio manager: %s", exc)

    def _coordinate_radio_captures(self, alert: CAPAlert, broadcast_result: Dict[str, Any]) -> List[Dict[str, object]]:
        if not self.radio_manager or not self._radio_receiver_cache:
            return []

        capture_mode = broadcast_result.get("preferred_capture_mode") or self.radio_capture_mode
        prefix_parts = [
            broadcast_result.get("event_code"),
            getattr(alert, "identifier", None),
        ]
        prefix_raw = "-".join(part for part in prefix_parts if part)
        safe_prefix = re.sub(r"[^A-Za-z0-9_-]", "_", prefix_raw) or "capture"

        try:
            results = self.radio_manager.request_captures(
                self.radio_capture_duration,
                self.radio_capture_dir,
                prefix=safe_prefix,
                mode=capture_mode,
            )
            for entry in results:
                identifier = entry.get("identifier")
                if entry.get("path"):
                    self.logger.info(
                        "Captured %s data for receiver %s → %s",
                        (entry.get("mode") or "iq").upper(),
                        identifier,
                        entry.get("path"),
                    )
                else:
                    self.logger.warning(
                        "Radio capture failed for %s: %s",
                        identifier,
                        entry.get("error"),
                    )
            return results
        except Exception as exc:
            self.logger.error("Radio capture orchestration failed: %s", exc)
            return []

    def _record_receiver_statuses(self, capture_events: Optional[List[Dict[str, Any]]] = None) -> None:
        if not self.radio_manager or not self._radio_receiver_cache:
            return

        events = capture_events or []
        rows_written = 0

        try:
            for event in events:
                timestamp = event.get("timestamp") or utc_now()
                for capture in event.get("captures", []):
                    identifier = capture.get("identifier")
                    if not identifier:
                        continue
                    receiver = self._radio_receiver_cache.get(identifier)
                    if not receiver:
                        continue

                    status = capture.get("status")
                    reported_at = getattr(status, "reported_at", None) or timestamp
                    error_text = capture.get("error")
                    last_error = getattr(status, "last_error", None)
                    if last_error and error_text and error_text not in last_error:
                        last_error = f"{last_error}; {error_text}"
                    elif not last_error:
                        last_error = error_text

                    row = RadioReceiverStatus(
                        receiver_id=receiver.id,
                        reported_at=reported_at,
                        locked=bool(getattr(status, "locked", False)),
                        signal_strength=getattr(status, "signal_strength", None),
                        last_error=last_error,
                        capture_mode=capture.get("mode"),
                        capture_path=str(capture.get("path")) if capture.get("path") else None,
                    )
                    self.db_session.add(row)
                    rows_written += 1

            status_reports = self.radio_manager.get_status_reports()
            for report in status_reports:
                receiver = self._radio_receiver_cache.get(report.identifier)
                if not receiver:
                    continue
                row = RadioReceiverStatus(
                    receiver_id=receiver.id,
                    reported_at=report.reported_at or utc_now(),
                    locked=bool(report.locked),
                    signal_strength=report.signal_strength,
                    last_error=report.last_error,
                    capture_mode=report.capture_mode,
                    capture_path=report.capture_path,
                )
                self.db_session.add(row)
                rows_written += 1

            if rows_written:
                self.db_session.commit()
        except Exception as exc:
            self.logger.error("Failed to record radio receiver statuses: %s", exc)
            self.db_session.rollback()

    # ---------- Engine with retry ----------
    def _load_location_settings(self) -> Dict[str, Any]:
        defaults = dict(DEFAULT_LOCATION_SETTINGS)
        settings: Dict[str, Any] = dict(defaults)

        try:
            record = self.db_session.query(LocationSettings).order_by(LocationSettings.id).first()
            if record:
                fips_codes, _ = sanitize_fips_codes(record.fips_codes or defaults['fips_codes'])
                settings.update({
                    'county_name': record.county_name or defaults['county_name'],
                    'state_code': (record.state_code or defaults['state_code']).upper(),
                    'timezone': record.timezone or defaults['timezone'],
                    'zone_codes': normalise_upper(record.zone_codes) or list(defaults['zone_codes']),
                    'fips_codes': fips_codes or list(defaults['fips_codes']),
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
        if not settings.get('fips_codes'):
            settings['fips_codes'] = list(defaults['fips_codes'])
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
    def _parse_feed_payload(self, response: requests.Response) -> List[Dict]:
        try:
            data = response.json()
        except ValueError:
            alerts = self._parse_ipaws_xml_feed(response.text)
            if alerts:
                self.logger.debug("Parsed %d CAP alerts from XML feed", len(alerts))
            return alerts

        features = data.get('features', [])
        if isinstance(features, list):
            return features

        self.logger.warning("CAP feed JSON response missing 'features' array")
        return []

    def _parse_ipaws_xml_feed(self, xml_text: str) -> List[Dict]:
        alerts: List[Dict] = []
        if not xml_text:
            return alerts

        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError as exc:
            self.logger.error(f"XML parse error in CAP feed: {exc}")
            return alerts

        ns = {
            'feed': 'http://gov.fema.ipaws.services/feed',
            'cap': 'urn:oasis:names:tc:emergency:cap:1.2',
        }

        for alert_elem in root.findall('.//cap:alert', ns):
            feature = self._convert_cap_alert(alert_elem, ns)
            if feature:
                alerts.append(feature)

        return alerts

    def _convert_cap_alert(self, alert_elem: ET.Element, ns: Dict[str, str]) -> Optional[Dict]:
        def get_text(element: Optional[ET.Element], path: str, default: str = '') -> str:
            if element is None:
                return default
            value = element.findtext(path, default=default, namespaces=ns)
            return value.strip() if isinstance(value, str) else default

        identifier = get_text(alert_elem, 'cap:identifier')
        sent = get_text(alert_elem, 'cap:sent')
        info_elems = alert_elem.findall('cap:info', ns)
        info_elem = self._select_cap_info(info_elems, ns)

        parameters = self._extract_cap_parameters(info_elem, ns)
        geometry, area_desc, geocodes = self._extract_area_details(info_elem, ns)

        properties = {
            'identifier': identifier,
            'sender': get_text(alert_elem, 'cap:sender'),
            'sent': sent,
            'status': get_text(alert_elem, 'cap:status', 'Unknown') or 'Unknown',
            'messageType': get_text(alert_elem, 'cap:msgType', 'Unknown') or 'Unknown',
            'scope': get_text(alert_elem, 'cap:scope', 'Unknown') or 'Unknown',
            'category': get_text(info_elem, 'cap:category', 'Unknown') or 'Unknown',
            'event': get_text(info_elem, 'cap:event', 'Unknown') or 'Unknown',
            'responseType': get_text(info_elem, 'cap:responseType'),
            'urgency': get_text(info_elem, 'cap:urgency', 'Unknown') or 'Unknown',
            'severity': get_text(info_elem, 'cap:severity', 'Unknown') or 'Unknown',
            'certainty': get_text(info_elem, 'cap:certainty', 'Unknown') or 'Unknown',
            'effective': get_text(info_elem, 'cap:effective'),
            'expires': get_text(info_elem, 'cap:expires'),
            'senderName': get_text(info_elem, 'cap:senderName'),
            'headline': get_text(info_elem, 'cap:headline'),
            'description': get_text(info_elem, 'cap:description'),
            'instruction': get_text(info_elem, 'cap:instruction'),
            'web': get_text(info_elem, 'cap:web'),
            'areaDesc': area_desc,
            'geocode': geocodes,
            'parameters': parameters,
            'source': ALERT_SOURCE_IPAWS,
        }

        if not properties['identifier']:
            fallback = f"{properties.get('event', 'Unknown')}|{properties.get('sent', '')}"
            properties['identifier'] = f"ipaws_{hashlib.md5(fallback.encode()).hexdigest()[:16]}"

        feature = {
            'type': 'Feature',
            'properties': properties,
            'geometry': geometry,
            'raw_xml': ET.tostring(alert_elem, encoding='unicode'),
        }

        return feature

    def _select_cap_info(self, info_elements: List[ET.Element], ns: Dict[str, str]) -> Optional[ET.Element]:
        if not info_elements:
            return None

        preferred_langs = ['en-US', 'en-us', 'en']
        for preferred in preferred_langs:
            for info_elem in info_elements:
                language = info_elem.findtext('cap:language', default='', namespaces=ns)
                if language and language.lower().startswith(preferred.lower()):
                    return info_elem

        return info_elements[0]

    def _extract_cap_parameters(self, info_elem: Optional[ET.Element], ns: Dict[str, str]) -> Dict[str, List[str]]:
        parameters: Dict[str, List[str]] = {}
        if info_elem is None:
            return parameters

        for param in info_elem.findall('cap:parameter', ns):
            name = param.findtext('cap:valueName', default='', namespaces=ns)
            value = param.findtext('cap:value', default='', namespaces=ns)
            if not name:
                continue
            name = name.strip()
            if not name:
                continue
            value = (value or '').strip()
            parameters.setdefault(name, []).append(value)

        return parameters

    def _extract_area_details(self, info_elem: Optional[ET.Element], ns: Dict[str, str]) -> Tuple[Optional[Dict], str, Dict[str, List[str]]]:
        if info_elem is None:
            return None, '', {}

        polygons: List[List[List[float]]] = []
        area_descs: List[str] = []
        geocodes: Dict[str, List[str]] = {}

        for area in info_elem.findall('cap:area', ns):
            desc = area.findtext('cap:areaDesc', default='', namespaces=ns)
            if desc:
                desc = desc.strip()
                if desc and desc not in area_descs:
                    area_descs.append(desc)

            for polygon in area.findall('cap:polygon', ns):
                coords = self._parse_cap_polygon(polygon.text)
                if coords:
                    polygons.append(coords)

            for circle in area.findall('cap:circle', ns):
                coords = self._parse_cap_circle(circle.text)
                if coords:
                    polygons.append(coords)

            for geocode in area.findall('cap:geocode', ns):
                name = geocode.findtext('cap:valueName', default='', namespaces=ns)
                value = geocode.findtext('cap:value', default='', namespaces=ns)
                if not name or not value:
                    continue
                name = name.strip().upper()
                value = value.strip()
                if not name or not value:
                    continue
                geocodes.setdefault(name, []).append(value)

        geometry: Optional[Dict] = None
        if polygons:
            if len(polygons) == 1:
                geometry = {'type': 'Polygon', 'coordinates': [polygons[0]]}
            else:
                geometry = {'type': 'MultiPolygon', 'coordinates': [[coords] for coords in polygons]}

        area_desc = '; '.join(area_descs)
        return geometry, area_desc, geocodes

    def _coords_equal(self, p1: List[float], p2: List[float], epsilon: float = 1e-7) -> bool:
        """Check if two coordinate pairs are equal within floating-point tolerance."""
        if len(p1) < 2 or len(p2) < 2:
            return False
        return abs(p1[0] - p2[0]) < epsilon and abs(p1[1] - p2[1]) < epsilon

    def _parse_cap_polygon(self, polygon_text: Optional[str]) -> Optional[List[List[float]]]:
        if not polygon_text:
            return None

        coords: List[List[float]] = []
        for pair in polygon_text.strip().split():
            if ',' not in pair:
                continue
            try:
                lat_str, lon_str = pair.split(',', 1)
                lat = float(lat_str)
                lon = float(lon_str)
                coords.append([lon, lat])
            except ValueError:
                continue

        if len(coords) < 3:
            return None

        # Use epsilon tolerance for coordinate comparison to handle floating-point precision
        if not self._coords_equal(coords[0], coords[-1]):
            coords.append(coords[0])

        return coords

    def _parse_cap_circle(self, circle_text: Optional[str], points: int = 36) -> Optional[List[List[float]]]:
        if not circle_text:
            return None

        parts = circle_text.strip().split()
        if not parts:
            return None

        try:
            lat_str, lon_str = parts[0].split(',', 1)
            lat = float(lat_str)
            lon = float(lon_str)
        except ValueError:
            return None

        radius_km = 0.0
        if len(parts) > 1:
            try:
                radius_km = float(parts[1])
            except ValueError:
                radius_km = 0.0

        if radius_km <= 0:
            return None

        return self._approximate_circle_polygon(lat, lon, radius_km, points)

    def _approximate_circle_polygon(self, lat: float, lon: float, radius_km: float, points: int) -> List[List[float]]:
        coords: List[List[float]] = []
        radius_ratio = radius_km / 6371.0  # Earth radius in km
        center_lat = math.radians(lat)
        center_lon = math.radians(lon)

        for step in range(points):
            bearing = 2 * math.pi * (step / points)
            sin_lat = math.sin(center_lat)
            cos_lat = math.cos(center_lat)
            sin_radius = math.sin(radius_ratio)
            cos_radius = math.cos(radius_ratio)

            lat_rad = math.asin(
                sin_lat * cos_radius + cos_lat * sin_radius * math.cos(bearing)
            )
            lon_rad = center_lon + math.atan2(
                math.sin(bearing) * sin_radius * cos_lat,
                cos_radius - sin_lat * math.sin(lat_rad)
            )

            coords.append([math.degrees(lon_rad), math.degrees(lat_rad)])

        # Use epsilon tolerance for ring closure
        if coords and not self._coords_equal(coords[0], coords[-1]):
            coords.append(coords[0])

        return coords

    MESSAGE_TYPE_PRIORITIES = {
        'CANCEL': 4,
        'UPDATE': 3,
        'ALERT': 2,
        'ACK': 1,
    }

    def _message_type_priority(self, message_type: Optional[str]) -> int:
        if not message_type:
            return 0
        return self.MESSAGE_TYPE_PRIORITIES.get(str(message_type).strip().upper(), 0)

    def _alert_sort_key(self, alert: Dict) -> Tuple[datetime, int]:
        properties = alert.get('properties', {})
        sent_raw = properties.get('sent')
        sent_dt = parse_nws_datetime(sent_raw) if sent_raw else None
        if not sent_dt:
            sent_dt = datetime.min.replace(tzinfo=UTC_TZ)
        message_type_priority = self._message_type_priority(properties.get('messageType'))
        return sent_dt, message_type_priority

    def _should_replace_alert(self, existing_alert: Dict, candidate_alert: Dict) -> bool:
        """Determine if candidate alert should replace existing alert.

        CANCEL messages always supersede other message types for the same identifier,
        regardless of timestamp, as they represent authoritative cancellations.
        """
        existing_props = existing_alert.get('properties', {})
        candidate_props = candidate_alert.get('properties', {})

        existing_msg_type = (existing_props.get('messageType') or '').strip().upper()
        candidate_msg_type = (candidate_props.get('messageType') or '').strip().upper()

        # CANCEL always wins over non-CANCEL
        if candidate_msg_type == 'CANCEL' and existing_msg_type != 'CANCEL':
            return True
        if existing_msg_type == 'CANCEL' and candidate_msg_type != 'CANCEL':
            return False

        # Otherwise use timestamp and priority-based logic
        existing_sent, existing_priority = self._alert_sort_key(existing_alert)
        candidate_sent, candidate_priority = self._alert_sort_key(candidate_alert)

        if candidate_sent > existing_sent:
            return True
        if candidate_sent < existing_sent:
            return False
        if candidate_priority > existing_priority:
            return True
        if candidate_priority < existing_priority:
            return False

        # Prefer alerts with geometry over those without
        existing_geometry = existing_alert.get('geometry')
        candidate_geometry = candidate_alert.get('geometry')
        if candidate_geometry and not existing_geometry:
            return True

        return False

    def fetch_cap_alerts(self, timeout: int = 30) -> List[Dict]:
        unique_alerts: List[Dict] = []
        sources_seen: Set[str] = set()
        duplicates_filtered = 0
        duplicates_replaced = 0
        alerts_by_identifier: Dict[str, Dict] = {}
        alerts_without_identifier: List[Dict] = []

        for endpoint in self.cap_endpoints:
            try:
                self.logger.info(f"Fetching alerts from: {endpoint}")
                response = self.session.get(endpoint, timeout=timeout)
                response.raise_for_status()
                features = self._parse_feed_payload(response)
                self.logger.info(f"Retrieved {len(features)} alerts from {endpoint}")
                for alert in features:
                    props = alert.get('properties', {})

                    identifier = (props.get('identifier') or '').strip()
                    if identifier:
                        props['identifier'] = identifier

                    source_value = props.get('source')
                    if not source_value:
                        if alert.get('raw_xml') is not None or 'ipaws' in endpoint.lower():
                            source_value = ALERT_SOURCE_IPAWS
                        elif 'weather.gov' in endpoint.lower():
                            source_value = ALERT_SOURCE_NOAA
                        else:
                            source_value = ALERT_SOURCE_UNKNOWN
                    canonical_source = normalize_alert_source(source_value)
                    props['source'] = canonical_source
                    if canonical_source != ALERT_SOURCE_UNKNOWN:
                        sources_seen.add(canonical_source)

                    if identifier:
                        existing_alert = alerts_by_identifier.get(identifier)
                        if not existing_alert:
                            alerts_by_identifier[identifier] = alert
                        else:
                            duplicates_filtered += 1
                            if self._should_replace_alert(existing_alert, alert):
                                alerts_by_identifier[identifier] = alert
                                duplicates_replaced += 1
                                self.logger.debug(
                                    "Replacing alert %s with newer payload (sent=%s, type=%s)",
                                    identifier,
                                    props.get('sent'),
                                    props.get('messageType'),
                                )
                            else:
                                self.logger.debug(
                                    "Skipping older duplicate for %s (sent=%s, type=%s)",
                                    identifier,
                                    props.get('sent'),
                                    props.get('messageType'),
                                )
                    else:
                        self.logger.warning("Alert has no identifier, including anyway")
                        alerts_without_identifier.append(alert)
            except requests.exceptions.SSLError as exc:
                self.logger.error(
                    "TLS certificate verification failed for %s: %s. "
                    "Provide a CA bundle via REQUESTS_CA_BUNDLE or CAP_POLLER_CA_BUNDLE if your environment "
                    "uses custom certificates.",
                    endpoint,
                    exc,
                )
            except requests.exceptions.RequestException as exc:
                self.logger.error(f"Error fetching from {endpoint}: {str(exc)}")
            except Exception as exc:
                self.logger.error(f"Unexpected error fetching from {endpoint}: {str(exc)}")

        unique_alerts.extend(alerts_by_identifier.values())
        unique_alerts.extend(alerts_without_identifier)

        self.last_poll_sources = sorted(sources_seen)
        self.last_duplicates_filtered = duplicates_filtered

        if duplicates_filtered:
            if duplicates_replaced:
                self.logger.info(
                    "Filtered %d duplicate identifiers (%d replaced with newer versions)",
                    duplicates_filtered,
                    duplicates_replaced,
                )
            else:
                self.logger.info(
                    "Filtered %d duplicate identifiers during fetch", duplicates_filtered
                )
        self.logger.info("Total unique alerts collected: %d", len(unique_alerts))
        if self.last_poll_sources:
            self.logger.info("Alert sources observed: %s", ", ".join(self.last_poll_sources))

        return unique_alerts

    def _safe_json_copy(self, value: Any) -> Any:
        try:
            return json.loads(json.dumps(value, default=str))
        except Exception:
            return value

    def _summarise_geometry(self, geometry: Optional[Dict]) -> Tuple[Optional[str], Optional[int], Optional[List[List[float]]]]:
        if not geometry or not isinstance(geometry, dict):
            return None, None, None

        geom_type = geometry.get('type')
        coordinates = geometry.get('coordinates')
        polygon_count: Optional[int] = None
        preview: Optional[List[List[float]]] = None

        if geom_type == 'Polygon':
            polygon_count = 1
            rings = coordinates or []
            if rings and isinstance(rings, list) and rings[0]:
                preview = [list(point) for point in rings[0][: min(len(rings[0]), 12)]]
        elif geom_type == 'MultiPolygon':
            polygon_count = len(coordinates or []) if isinstance(coordinates, list) else 0
            if coordinates and isinstance(coordinates, list):
                first_polygon = coordinates[0] or []
                if first_polygon and isinstance(first_polygon, list) and first_polygon[0]:
                    preview = [list(point) for point in first_polygon[0][: min(len(first_polygon[0]), 12)]]
        else:
            if isinstance(coordinates, list):
                polygon_count = len(coordinates)
                preview = [list(point) for point in coordinates[: min(len(coordinates), 12)]]

        return geom_type, polygon_count, preview

    # ---------- Relevance ----------
    def _validate_ugc_code(self, ugc: str) -> bool:
        """Validate UGC code format: [A-Z]{2}[CZ]\d{3} (e.g., OHZ016, OHC137)."""
        if not ugc or not isinstance(ugc, str):
            return False
        ugc = ugc.strip().upper()
        # Valid UGC format: 2 letters, C or Z, 3 digits
        return bool(re.match(r'^[A-Z]{2}[CZ]\d{3}$', ugc))

    @staticmethod
    def _normalize_same_code(value: Any) -> Optional[str]:
        digits = ''.join(ch for ch in str(value) if ch.isdigit())
        if not digits:
            return None
        normalized = digits.zfill(6)[:6]
        return normalized if normalized.strip('0') else normalized

    def get_alert_relevance_details(self, alert_data: Dict) -> Dict[str, Any]:
        result: Dict[str, Any] = {
            'is_relevant': False,
            'reason': 'NO_MATCH',
            'matched_ugc': None,
            'matched_terms': [],
            'relevance_matches': [],
            'ugc_codes': [],
            'same_codes': [],
            'area_desc': '',
            'log': None,
        }

        try:
            properties = alert_data.get('properties', {})
            event = properties.get('event', 'Unknown')
            geocode = properties.get('geocode', {}) or {}
            ugc_codes = geocode.get('UGC', []) or []
            same_codes_raw = geocode.get('SAME', []) or []

            # Validate and normalize UGC codes
            normalized_ugc = []
            for ugc in ugc_codes:
                if not ugc:
                    continue
                ugc_str = str(ugc).strip().upper()
                if self._validate_ugc_code(ugc_str):
                    normalized_ugc.append(ugc_str)
                else:
                    self.logger.warning(
                        f"Skipping malformed UGC code '{ugc}' in alert {properties.get('identifier', 'Unknown')}"
                    )

            result['ugc_codes'] = normalized_ugc

            normalized_same = []
            for same in same_codes_raw:
                normalized = self._normalize_same_code(same)
                if normalized:
                    normalized_same.append(normalized)
            result['same_codes'] = normalized_same

            area_desc_raw = properties.get('areaDesc') or ''
            if isinstance(area_desc_raw, list):
                area_desc_raw = '; '.join(area_desc_raw)
            area_desc_upper = area_desc_raw.upper()
            result['area_desc'] = area_desc_raw

            for same in normalized_same:
                if same in self.same_codes:
                    message = f"✓ Alert ACCEPTED by SAME: {event} ({same})"
                    result.update(
                        {
                            'is_relevant': True,
                            'reason': 'SAME_MATCH',
                            'matched_ugc': same,
                            'relevance_matches': [same],
                            'log': {'level': 'info', 'message': message},
                        }
                    )
                    return result

                if same.endswith('000'):
                    prefix = same[:3]
                    if prefix and any(code.startswith(prefix) for code in self.same_codes):
                        message = f"✓ Alert ACCEPTED by statewide SAME: {event} ({same})"
                        result.update(
                            {
                                'is_relevant': True,
                                'reason': 'SAME_MATCH',
                                'matched_ugc': same,
                                'relevance_matches': [same],
                                'log': {'level': 'info', 'message': message},
                            }
                        )
                        return result

            for ugc in normalized_ugc:
                if ugc in self.zone_codes:
                    message = f"✓ Alert ACCEPTED by UGC: {event} ({ugc})"
                    result.update(
                        {
                            'is_relevant': True,
                            'reason': 'UGC_MATCH',
                            'matched_ugc': ugc,
                            'relevance_matches': [ugc],
                            'log': {'level': 'info', 'message': message},
                        }
                    )
                    return result

            message = (
                f"✗ REJECT (not specific enough for {self.county_upper}): {event} - {area_desc_upper}"
            )
            result['log'] = {'level': 'info', 'message': message}
            return result
        except Exception as exc:
            result['log'] = {'level': 'error', 'message': f"Error checking relevance: {exc}"}
            result['error'] = str(exc)
            return result

    def is_relevant_alert(self, alert_data: Dict) -> bool:
        details = self.get_alert_relevance_details(alert_data)
        log_entry = details.get('log') or {}
        message = log_entry.get('message')
        if message:
            level = (log_entry.get('level') or 'info').lower()
            if level == 'error':
                self.logger.error(message)
            elif level == 'warning':
                self.logger.warning(message)
            else:
                self.logger.info(message)
        return bool(details.get('is_relevant'))

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

            source_value = properties.get('source')
            if not source_value and alert_data.get('raw_xml') is not None:
                source_value = ALERT_SOURCE_IPAWS
            elif not source_value:
                source_value = ALERT_SOURCE_NOAA
            source_value = normalize_alert_source(source_value)

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
                'source': source_value,
                '_geometry_data': geometry,
            }
            self.logger.info(f"Parsed alert: {identifier} - {parsed['event']}")
            return parsed
        except Exception as e:
            self.logger.error(f"Error parsing CAP alert: {e}")
            return None

    # ---------- Save / Geometry / Intersections ----------
    def _count_vertices(self, coords, depth: int = 0) -> int:
        """Recursively count vertices in nested coordinate arrays."""
        if depth > 10:  # Prevent infinite recursion on malformed data
            self.logger.warning("Maximum geometry nesting depth exceeded")
            return 0

        if not isinstance(coords, list):
            return 0

        # Check if this is a coordinate pair [lon, lat]
        if coords and len(coords) >= 2 and isinstance(coords[0], (int, float)):
            return 1

        # Otherwise recursively count nested arrays
        return sum(self._count_vertices(item, depth + 1) for item in coords)

    def _set_alert_geometry(self, alert: CAPAlert, geometry_data: Optional[Dict]):
        """Set alert geometry with validation for complexity and validity."""
        try:
            if geometry_data and isinstance(geometry_data, dict):
                # Check polygon complexity before storing
                coords = geometry_data.get('coordinates', [])
                total_vertices = self._count_vertices(coords)

                # Warn and skip geometries that are excessively complex
                if total_vertices > 10000:
                    self.logger.warning(
                        f"Alert {getattr(alert, 'identifier', '?')} has {total_vertices} vertices "
                        "(exceeds 10,000 limit). Geometry will not be stored to prevent performance issues."
                    )
                    alert.geom = None
                    return

                if total_vertices > 5000:
                    self.logger.info(
                        f"Alert {getattr(alert, 'identifier', '?')} has {total_vertices} vertices "
                        "(high complexity)"
                    )

                geom_json = json.dumps(geometry_data)
                result = self.db_session.execute(
                    text("SELECT ST_SetSRID(ST_GeomFromGeoJSON(:g), 4326)"),
                    {"g": geom_json}
                ).scalar()

                # Validate geometry and attempt repair if invalid
                is_valid = self.db_session.execute(
                    text("SELECT ST_IsValid(:geom)"),
                    {"geom": result}
                ).scalar()

                if not is_valid:
                    self.logger.warning(
                        f"Invalid geometry for alert {getattr(alert, 'identifier', '?')}, "
                        "attempting automatic repair with ST_MakeValid"
                    )
                    result = self.db_session.execute(
                        text("SELECT ST_MakeValid(:geom)"),
                        {"geom": result}
                    ).scalar()

                alert.geom = result
                self.logger.debug(f"Geometry set for alert {alert.identifier}")
            else:
                alert.geom = None
                self.logger.debug(f"No geometry for alert {alert.identifier}")
        except Exception as e:
            self.logger.warning(f"Could not set geometry for alert {getattr(alert,'identifier','?')}: {e}")
            alert.geom = None

    def _has_geometry_changed(self, old_geom, new_geom) -> bool:
        """Use PostGIS ST_Equals to reliably compare geometries."""
        if old_geom is None and new_geom is None:
            return False
        if old_geom is None or new_geom is None:
            return True

        try:
            result = self.db_session.execute(
                text("SELECT ST_Equals(:old, :new)"),
                {"old": old_geom, "new": new_geom}
            ).scalar()
            return not result
        except Exception as exc:
            self.logger.warning(f"Geometry comparison failed, assuming changed: {exc}")
            return True

    def _needs_intersection_calculation(self, alert: CAPAlert) -> bool:
        if not alert.geom:
            return False
        try:
            cnt = self.db_session.query(Intersection).filter_by(cap_alert_id=alert.id).count()
            return cnt == 0
        except Exception:
            return True

    def process_intersections(self, alert: CAPAlert):
        """Calculate and store intersections with proper transaction handling."""
        try:
            if not alert.geom:
                return

            # Delete old intersections
            self.db_session.query(Intersection).filter_by(cap_alert_id=alert.id).delete()

            # Query all boundaries with valid geometries
            boundaries = self.db_session.query(Boundary).filter(Boundary.geom.isnot(None)).all()

            # Build list of new intersections (don't commit until all are calculated)
            new_intersections = []
            with_area = 0

            for boundary in boundaries:
                try:
                    res = self.db_session.query(
                        func.ST_Intersects(alert.geom, boundary.geom).label('intersects'),
                        func.ST_Area(func.ST_Intersection(alert.geom, boundary.geom)).label('ia')
                    ).first()

                    if res and res.intersects:
                        ia = float(res.ia or 0)
                        new_intersections.append(Intersection(
                            cap_alert_id=alert.id,
                            boundary_id=boundary.id,
                            intersection_area=ia,
                            created_at=utc_now()
                        ))
                        if ia > 0:
                            with_area += 1
                except Exception as be:
                    self.logger.warning(f"Intersection error with boundary {boundary.id}: {be}")
                    # Continue processing other boundaries

            # Bulk insert all intersections atomically
            if new_intersections:
                self.db_session.bulk_save_objects(new_intersections)

            self.db_session.commit()

            if new_intersections:
                self.logger.info(
                    f"Intersections for alert {alert.identifier}: {len(new_intersections)} "
                    f"({with_area} with area > 0)"
                )
        except Exception as e:
            self.db_session.rollback()
            self.logger.error(f"Error processing intersections for alert {alert.id}: {e}")
            raise  # Re-raise so caller knows intersection calculation failed

    def save_cap_alert(self, alert_data: Dict) -> Tuple[bool, Optional[CAPAlert], Optional[Dict[str, Any]]]:
        try:
            payload = dict(alert_data)
            geometry_data = payload.pop('_geometry_data', None)
            existing = self.db_session.query(CAPAlert).filter_by(
                identifier=payload['identifier']
            ).first()

            if existing:
                for k, v in payload.items():
                    # Update raw_json to maintain audit trail
                    if hasattr(existing, k):
                        setattr(existing, k, v)
                old_geom = existing.geom
                self._set_alert_geometry(existing, geometry_data)
                existing.updated_at = utc_now()
                self.db_session.commit()

                # Use PostGIS ST_Equals for reliable geometry comparison
                geom_changed = self._has_geometry_changed(old_geom, existing.geom)

                if geom_changed or self._needs_intersection_calculation(existing):
                    self.process_intersections(existing)
                if self.led_controller and not self.is_alert_expired(existing):
                    self.update_led_display()
                self.logger.info(f"Updated alert: {existing.event}")
                return False, existing, None

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

            capture_metadata: Optional[Dict[str, Any]] = None
            if self.eas_broadcaster:
                try:
                    broadcast_result = self.eas_broadcaster.handle_alert(new_alert, payload)
                    if broadcast_result and broadcast_result.get("same_triggered"):
                        capture_results = self._coordinate_radio_captures(new_alert, broadcast_result)
                        capture_metadata = {
                            "alert_identifier": getattr(new_alert, "identifier", None),
                            "broadcast": broadcast_result,
                            "captures": capture_results,
                        }
                    else:
                        capture_metadata = {"broadcast": broadcast_result}
                except Exception as exc:
                    self.logger.error(f"EAS broadcast failed for {new_alert.identifier}: {exc}")
                    capture_metadata = {"error": str(exc)}

            self.logger.info(f"Saved new alert: {new_alert.identifier} - {new_alert.event}")
            return True, new_alert, capture_metadata

        except SQLAlchemyError as e:
            self.logger.error(f"Database error saving alert: {e}")
            self.db_session.rollback()
            return False, None, None
        except Exception as e:
            self.logger.error(f"Error saving CAP alert: {e}")
            self.db_session.rollback()
            return False, None, None

    # ---------- LED ----------
    def is_alert_expired(self, alert, max_age_days: int = 30) -> bool:
        """Check if alert is expired or older than max_age_days.

        Alerts with no expiration are considered expired after max_age_days
        to prevent indefinite accumulation of stale alerts.
        """
        # Check explicit expiration
        if getattr(alert, 'expires', None) and alert.expires < utc_now():
            return True

        # Check age-based expiration for alerts without explicit expiry
        sent = getattr(alert, 'sent', None)
        if not getattr(alert, 'expires', None) and sent:
            age = utc_now() - sent
            if age.total_seconds() > (max_age_days * 86400):
                self.logger.debug(
                    f"Alert {getattr(alert, 'identifier', '?')} has no expiration "
                    f"but is {age.days} days old, treating as expired"
                )
                return True

        return False

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

    def _initialise_debug_entry(
        self,
        alert_data: Dict,
        relevance: Dict[str, Any],
        poll_run_id: str,
        poll_started_at: datetime,
    ) -> Dict[str, Any]:
        properties = alert_data.get('properties', {})
        identifier = (properties.get('identifier') or '').strip() or 'No ID'
        sent_raw = properties.get('sent')
        sent_dt = parse_nws_datetime(sent_raw) if sent_raw else None
        geometry = alert_data.get('geometry') if isinstance(alert_data.get('geometry'), dict) else None
        geom_type, polygon_count, preview = self._summarise_geometry(geometry)

        log_entry = relevance.get('log') if isinstance(relevance, dict) else None
        notes: List[str] = []
        if log_entry and log_entry.get('message'):
            notes.append(str(log_entry['message']))

        entry = {
            'poll_run_id': poll_run_id,
            'poll_started_at': poll_started_at,
            'identifier': identifier,
            'event': properties.get('event', 'Unknown'),
            'alert_sent': sent_dt,
            'source': properties.get('source'),
            'raw_properties': self._safe_json_copy(properties),
            'geometry_geojson': self._safe_json_copy(geometry) if geometry else None,
            'geometry_preview': preview,
            'geometry_type': geom_type,
            'polygon_count': polygon_count,
            'is_relevant': relevance.get('is_relevant', False),
            'relevance_reason': relevance.get('reason'),
            'relevance_matches': relevance.get('relevance_matches', []),
            'ugc_codes': relevance.get('ugc_codes', []),
            'area_desc': relevance.get('area_desc'),
            'raw_xml_present': bool(alert_data.get('raw_xml')),
            'parse_success': False,
            'parse_error': None,
            'was_saved': False,
            'was_new': False,
            'alert_db_id': None,
            'notes': notes,
        }

        return entry

    def persist_debug_records(
        self,
        poll_run_id: str,
        poll_started_at: datetime,
        stats: Dict[str, Any],
        debug_records: List[Dict[str, Any]],
    ) -> None:
        if not debug_records:
            return
        if not self._ensure_debug_records_table():
            return

        try:
            data_source = summarise_sources(stats.get('sources', []))
            for entry in debug_records:
                record = PollDebugRecord(
                    poll_run_id=poll_run_id,
                    poll_started_at=poll_started_at,
                    poll_status=stats.get('status', 'UNKNOWN'),
                    data_source=data_source,
                    alert_identifier=entry.get('identifier'),
                    alert_event=entry.get('event'),
                    alert_sent=entry.get('alert_sent'),
                    source=entry.get('source'),
                    is_relevant=entry.get('is_relevant', False),
                    relevance_reason=entry.get('relevance_reason'),
                    relevance_matches=self._safe_json_copy(entry.get('relevance_matches')),
                    ugc_codes=self._safe_json_copy(entry.get('ugc_codes')),
                    area_desc=entry.get('area_desc'),
                    was_saved=entry.get('was_saved', False),
                    was_new=entry.get('was_new', False),
                    alert_db_id=entry.get('alert_db_id'),
                    parse_success=entry.get('parse_success', False),
                    parse_error=entry.get('parse_error'),
                    polygon_count=entry.get('polygon_count'),
                    geometry_type=entry.get('geometry_type'),
                    geometry_geojson=self._safe_json_copy(entry.get('geometry_geojson')),
                    geometry_preview=self._safe_json_copy(entry.get('geometry_preview')),
                    raw_properties=self._safe_json_copy(entry.get('raw_properties')),
                    raw_xml_present=entry.get('raw_xml_present', False),
                    notes="\n".join(filter(None, entry.get('notes', []))) or None,
                )
                self.db_session.add(record)
            self.db_session.commit()
        except Exception as exc:
            self.logger.error(f"Failed to persist poll debug records: {exc}")
            try:
                self.db_session.rollback()
            except Exception:
                pass

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
            try:
                self.db_session.rollback()
            except Exception as rollback_exc:
                self.logger.debug("Rollback failed during poll history cleanup: %s", rollback_exc)

    def cleanup_old_debug_records(self):
        if not self._ensure_debug_records_table():
            return

        try:
            cutoff = utc_now() - timedelta(days=7)
            old_count = (
                self.db_session.query(PollDebugRecord)
                .filter(PollDebugRecord.created_at < cutoff)
                .count()
            )
            if old_count > 500:
                subq = (
                    self.db_session.query(PollDebugRecord.id)
                    .order_by(PollDebugRecord.created_at.desc())
                    .limit(500)
                    .subquery()
                )
                self.db_session.query(PollDebugRecord).filter(
                    PollDebugRecord.created_at < cutoff,
                    ~PollDebugRecord.id.in_(subq),
                ).delete(synchronize_session=False)
                self.db_session.commit()
        except Exception as exc:
            self.logger.error(f"cleanup_old_debug_records error: {exc}")
            try:
                self.db_session.rollback()
            except Exception:
                pass

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
                data_source=summarise_sources(stats.get('sources', [])),
            )
            self.db_session.add(rec)
            self.db_session.commit()
        except Exception as e:
            self.logger.error(f"log_poll_history error: {e}")
            try: self.db_session.rollback()
            except Exception: pass

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
            except Exception: pass

    # ---------- Main poll ----------
    def poll_and_process(self) -> Dict:
        start = time.time()
        poll_start_utc = utc_now()
        poll_start_local = local_now()
        poll_run_id = uuid.uuid4().hex

        stats = {
            'alerts_fetched': 0, 'alerts_new': 0, 'alerts_updated': 0,
            'alerts_filtered': 0, 'alerts_accepted': 0, 'intersections_calculated': 0,
            'execution_time_ms': 0, 'status': 'SUCCESS', 'error_message': None,
            'zone': f"{'/'.join(self.location_settings['zone_codes'])} ({self.location_name}) - STRICT FILTERING",
            'poll_time_utc': poll_start_utc.isoformat(),
            'poll_time_local': poll_start_local.isoformat(),
            'timezone': self.location_settings['timezone'], 'led_updated': False,
            'sources': [], 'duplicates_filtered': 0,
            'poll_run_id': poll_run_id,
            'radio_captures': 0,
        }

        debug_records: List[Dict[str, Any]] = []
        capture_events: List[Dict[str, Any]] = []

        try:
            self.logger.info(
                f"Starting CAP alert polling cycle for {self.location_name} at {format_local_datetime(poll_start_utc)}"
            )

            self._refresh_radio_configuration()

            alerts_data = self.fetch_cap_alerts()
            stats['alerts_fetched'] = len(alerts_data)
            stats['sources'] = list(self.last_poll_sources)
            stats['duplicates_filtered'] = self.last_duplicates_filtered

            for alert_data in alerts_data:
                props = alert_data.get('properties', {})
                event = props.get('event', 'Unknown')
                alert_id = props.get('identifier', 'No ID')

                self.logger.info(f"Processing alert: {event} (ID: {alert_id[:20] if alert_id!='No ID' else 'No ID'}...)")

                relevance = self.get_alert_relevance_details(alert_data)
                log_entry = relevance.get('log') or {}
                message = log_entry.get('message')
                if message:
                    level = (log_entry.get('level') or 'info').lower()
                    if level == 'error':
                        self.logger.error(message)
                    elif level == 'warning':
                        self.logger.warning(message)
                    else:
                        self.logger.info(message)

                debug_entry = self._initialise_debug_entry(alert_data, relevance, poll_run_id, poll_start_utc)
                debug_records.append(debug_entry)

                if not relevance.get('is_relevant'):
                    self.logger.info(f"• Filtered out (not specific to {self.county_upper})")
                    stats['alerts_filtered'] += 1
                    debug_entry.setdefault('notes', []).append('Filtered out by strict location rules')
                    continue

                stats['alerts_accepted'] += 1
                parsed = self.parse_cap_alert(alert_data)
                if not parsed:
                    self.logger.warning(f"Failed to parse: {event}")
                    debug_entry['parse_error'] = 'parse_cap_alert returned None'
                    debug_entry.setdefault('notes', []).append('Parsing failed')
                    continue

                debug_entry['parse_success'] = True
                debug_entry['identifier'] = parsed.get('identifier', debug_entry['identifier'])
                debug_entry['source'] = parsed.get('source', debug_entry.get('source'))
                debug_entry['alert_sent'] = parsed.get('sent', debug_entry.get('alert_sent'))
                geometry_data = parsed.get('_geometry_data')
                if geometry_data:
                    debug_entry['geometry_geojson'] = self._safe_json_copy(geometry_data)
                    geom_type, polygon_count, preview = self._summarise_geometry(geometry_data)
                    debug_entry['geometry_type'] = geom_type
                    debug_entry['polygon_count'] = polygon_count
                    debug_entry['geometry_preview'] = preview

                is_new, alert, capture_metadata = self.save_cap_alert(parsed)
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

                debug_entry['was_saved'] = bool(alert)
                debug_entry['was_new'] = bool(is_new and alert is not None)
                debug_entry['alert_db_id'] = getattr(alert, 'id', None) if alert else None
                if not alert:
                    debug_entry.setdefault('notes', []).append('Database save failed')

                if capture_metadata:
                    capture_metadata.setdefault('timestamp', utc_now())
                    stats['radio_captures'] += len(capture_metadata.get('captures', []))
                    capture_events.append(capture_metadata)

            self.cleanup_old_poll_history()
            self.log_poll_history(stats)
            self.persist_debug_records(poll_run_id, poll_start_utc, stats, debug_records)
            self.cleanup_old_debug_records()

            if self.led_controller:
                self.update_led_display()
                stats['led_updated'] = True

            stats['execution_time_ms'] = int((time.time() - start) * 1000)
            self.logger.info(
                f"Polling cycle completed: {stats['alerts_accepted']} accepted, {stats['alerts_new']} new, "
                f"{stats['alerts_updated']} updated, {stats['alerts_filtered']} filtered, "
                f"{stats['duplicates_filtered']} duplicates skipped, "
                f"{stats['radio_captures']} radio captures"
            )
            if stats['sources']:
                self.logger.info("Polling sources: %s", ", ".join(stats['sources']))
            self.log_system_event('INFO', f"CAP polling successful: {stats['alerts_new']} new alerts", stats)

        except Exception as e:
            stats['status'] = 'ERROR'
            stats['error_message'] = str(e)
            stats['execution_time_ms'] = int((time.time() - start) * 1000)
            self.logger.error(f"Error in polling cycle: {e}")
            self.log_system_event('ERROR', f"CAP polling failed: {e}", stats)

            self.persist_debug_records(poll_run_id, poll_start_utc, stats, debug_records)
            self.cleanup_old_debug_records()

        finally:
            try:
                self._record_receiver_statuses(capture_events)
            except Exception as exc:
                self.logger.error("Failed to persist radio status snapshots: %s", exc)

        return stats

    def close(self):
        try:
            if hasattr(self, 'db_session'):
                self.db_session.close()
        finally:
            if hasattr(self, 'session'):
                self.session.close()
            if self.led_controller:
                try:
                    self.led_controller.close()
                except Exception as led_exc:
                    self.logger.debug("LED controller cleanup failed: %s", led_exc)

# =======================================================================================
# Main
# =======================================================================================

def build_database_url_from_env() -> str:
    """Build a SQLAlchemy database URL from environment variables."""

    url = os.getenv("DATABASE_URL")
    if url:
        return url

    user = os.getenv("POSTGRES_USER", "postgres") or "postgres"
    password = os.getenv("POSTGRES_PASSWORD", "")
    host = os.getenv("POSTGRES_HOST", "host.docker.internal") or "host.docker.internal"
    port = os.getenv("POSTGRES_PORT", "5432") or "5432"
    database = os.getenv("POSTGRES_DB", user) or user

    user_part = quote(user, safe="")
    password_part = quote(password, safe="") if password else ""

    if password_part:
        auth_segment = f"{user_part}:{password_part}"
    else:
        auth_segment = user_part

    return f"postgresql+psycopg2://{auth_segment}@{host}:{port}/{database}"

def main():
    parser = argparse.ArgumentParser(description='Emergency CAP Alert Poller (configurable feeds)')
    parser.add_argument('--database-url',
                        default=build_database_url_from_env(),
                        help='SQLAlchemy DB URL (defaults from env POSTGRES_* or DATABASE_URL)')
    parser.add_argument('--led-ip', help='LED sign IP address')
    parser.add_argument('--led-port', type=int, default=10001, help='LED sign port (default: 10001)')
    parser.add_argument('--log-level', default=os.getenv('LOG_LEVEL', 'INFO'),
                        choices=['DEBUG', 'INFO', 'WARNING', 'ERROR'], help='Logging level')
    parser.add_argument('--continuous', action='store_true', help='Run continuously')
    parser.add_argument('--interval', type=int, default=int(os.getenv('POLL_INTERVAL_SEC', '300')),
                        help='Polling interval seconds (default: 300, minimum: 30)')
    parser.add_argument('--cap-endpoint', dest='cap_endpoints', action='append', default=[],
                        help='Custom CAP feed endpoint (repeatable)')
    parser.add_argument('--cap-endpoints', dest='cap_endpoints_csv',
                        help='Comma-separated CAP feed endpoints to poll')
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
    # Use dynamic location information instead of hardcoded "PUTNAM COUNTY"
    poller_mode = (os.getenv('CAP_POLLER_MODE', 'NOAA') or 'NOAA').strip().upper()
    logger.info(f"Starting CAP Alert Poller with LED Integration - Mode: {poller_mode}")
    logger.info(f"Startup time: {format_local_datetime(startup_utc)}")
    if args.led_ip:
        logger.info(f"LED Sign: {args.led_ip}:{args.led_port}")

    cli_endpoints = list(args.cap_endpoints or [])
    if args.cap_endpoints_csv:
        cli_endpoints.extend([
            endpoint.strip()
            for endpoint in args.cap_endpoints_csv.split(',')
            if endpoint.strip()
        ])

    poller = CAPPoller(args.database_url, args.led_ip, args.led_port, cap_endpoints=cli_endpoints or None)

    try:
        if args.fix_geometry:
            logger.info("Running geometry fix for existing alerts...")
            stats = poller.fix_existing_geometry()
            print(json.dumps(stats, indent=2))
        elif args.continuous:
            # Enforce minimum interval to prevent excessive CPU usage
            interval = max(30, args.interval)
            if interval != args.interval:
                logger.warning(
                    f"Interval {args.interval}s is below minimum; using {interval}s to prevent excessive CPU usage"
                )
            logger.info(f"Running continuously with {interval} second intervals")
            while True:
                try:
                    stats = poller.poll_and_process()
                    print(json.dumps(stats, indent=2))
                    logger.info(f"Polling cycle complete. Sleeping for {interval} seconds...")
                    time.sleep(interval)
                except KeyboardInterrupt:
                    logger.info("Received interrupt signal, shutting down")
                    break
                except Exception as e:
                    logger.error(f"Error in continuous polling: {e}")
                    logger.info("Sleeping for 60 seconds before retry...")
                    time.sleep(60)
        else:
            stats = poller.poll_and_process()
            print(json.dumps(stats, indent=2))
    finally:
        poller.close()

if __name__ == '__main__':
    main()
