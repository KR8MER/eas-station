#!/usr/bin/env python3
"""
EAS Station - Emergency Alert System
Copyright (c) 2025-2026 EAS Station, LLC (KR8MER)

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
NOAA CAP Alert Poller with configurable location filtering
Supports bare metal and containerized deployments with strict jurisdiction filtering,
PostGIS geometry/intersections, and optional LED sign integration.

NOAA Weather API Compliance:
  The NOAA Weather API (https://api.weather.gov/) requires:
  - User-Agent header: Identifies the application and provides contact information
  - Accept header: Specifies desired response format (application/geo+json for CAP alerts)
  - No API key or authentication required
  - Configure via NOAA_USER_AGENT environment variable (defaults to a compliant value)
  - API Documentation: https://www.weather.gov/documentation/services-web-api

Database Configuration (via environment variables):
  DATABASE_URL       - Complete PostgreSQL connection URL (required)
                       Format: ******host:port/database

All database credentials must be configured via DATABASE_URL environment variable.
"""

# CRITICAL DEBUG: Print BEFORE any imports to verify script is running
print("=" * 80, flush=True)
print("[CAP_POLLER_INIT] Script execution started!", flush=True)
print("=" * 80, flush=True)

import os
import sys
print("[CAP_POLLER_INIT] os and sys imported", flush=True)
import time
import re
import uuid
print("[CAP_POLLER_INIT] time, re, uuid imported", flush=True)
import requests
import logging
import hashlib
import math
print("[CAP_POLLER_INIT] requests, logging, hashlib, math imported", flush=True)
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple
import argparse
print("[CAP_POLLER_INIT] datetime, pathlib, typing, argparse imported", flush=True)

import pytz
import certifi
import redis
from dotenv import load_dotenv
from urllib.parse import quote
print("[CAP_POLLER_INIT] pytz, certifi, redis, dotenv, urllib imported", flush=True)

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(CURRENT_DIR, os.pardir))
print(f"[CAP_POLLER_INIT] PROJECT_ROOT: {PROJECT_ROOT}", flush=True)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)
    print(f"[CAP_POLLER_INIT] Added PROJECT_ROOT to sys.path", flush=True)

# Load persistent configuration from a single master environment file.
# Use CONFIG_PATH environment variable to specify the config file location.
# For bare metal installations, defaults to project directory .env file.
# For Docker/container deployments, set CONFIG_PATH=/app-config/.env.
def _resolve_config_path() -> Optional[Path]:
    """Resolve configuration file path with automatic fallback for invalid paths.
    
    Returns the path to the .env configuration file. If CONFIG_PATH environment
    variable points to a non-existent or non-writable location, automatically
    falls back to the project directory .env file to prevent errors.
    """
    # Get project root directory (fallback path)
    project_root = Path(__file__).parent.parent
    project_env = project_root / '.env'
    
    # Check for explicit CONFIG_PATH override
    config_path_env = os.environ.get('CONFIG_PATH', '').strip()
    if config_path_env:
        config_path = Path(config_path_env)
        parent_dir = config_path.parent
        
        # Validate that the override path is usable
        if not parent_dir.exists():
            print(
                f"[CAP_POLLER] WARNING: CONFIG_PATH parent directory does not exist: {parent_dir}. "
                f"Falling back to project directory: {project_env}",
                flush=True
            )
            return project_env
        
        if not os.access(parent_dir, os.W_OK):
            print(
                f"[CAP_POLLER] WARNING: CONFIG_PATH parent directory is not writable: {parent_dir}. "
                f"Falling back to project directory: {project_env}",
                flush=True
            )
            return project_env
        
        # CONFIG_PATH is valid
        print(f"[CAP_POLLER] Using CONFIG_PATH: {config_path}", flush=True)
        return config_path
    
    # Default to project directory .env file (bare metal installation)
    print(f"[CAP_POLLER] Using default config path: {project_env}", flush=True)
    return project_env


# Load the master configuration file
_config_path = _resolve_config_path()
print(f"[CAP_POLLER] Master config path: {_config_path}")
print(f"[CAP_POLLER] Config file exists: {_config_path.exists() if _config_path else False}")
if _config_path and _config_path.exists():
    print(f"[CAP_POLLER] Loading master config from: {_config_path}")
    load_dotenv(_config_path, override=True)
    print(f"[CAP_POLLER] Master config loaded successfully")
else:
    print(f"[CAP_POLLER] Master config not found, using environment variables only")

# Always load a local .env file last so it only fills in missing values
print(f"[CAP_POLLER] Loading fallback .env file (if exists)")
load_dotenv(override=True)
print(f"[CAP_POLLER] Environment loading complete")
print(f"[CAP_POLLER] Importing SQLAlchemy and app modules...")
from sqlalchemy import create_engine, text, func, or_
from sqlalchemy.orm import sessionmaker
from sqlalchemy.exc import SQLAlchemyError, OperationalError, IntegrityError
print(f"[CAP_POLLER] SQLAlchemy imported successfully")

# =======================================================================================
# Timezones and helpers
# =======================================================================================

print(f"[CAP_POLLER] Importing app_utils...")
from app_utils import (
    format_local_datetime as util_format_local_datetime,
    local_now as util_local_now,
    parse_nws_datetime as util_parse_nws_datetime,
    set_location_timezone,
    utc_now as util_utc_now,
)
print(f"[CAP_POLLER] Importing app_utils.alert_sources...")
from app_utils.alert_sources import (
    ALERT_SOURCE_IPAWS,
    ALERT_SOURCE_NOAA,
    ALERT_SOURCE_UNKNOWN,
    normalize_alert_source,
    summarise_sources,
)
print(f"[CAP_POLLER] Importing app_utils.location_settings...")
from app_utils.location_settings import (
    DEFAULT_LOCATION_SETTINGS,
    ensure_list,
    normalise_upper,
    sanitize_fips_codes,
)
print(f"[CAP_POLLER] Importing app_utils.optimized_parsing...")
from app_utils.optimized_parsing import json_loads, json_dumps, parse_xml_string, get_element_tree_module
from app_utils.ipaws_enrichment import extract_certificate_info, save_ipaws_audio
from app_utils.vtec import (
    extract_vtec_identity,
    is_cancellation,
    terminal_chain_updates,
    VTEC_TERMINAL_ACTIONS,
)
from app_utils.eas import load_eas_config
from app_core.audio.auto_forward import auto_forward_cap_alert
print(f"[CAP_POLLER] Importing app_core.models...")
from app_core.models import PollerSettings
print(f"[CAP_POLLER] All app module imports complete!")

# Use optimized XML parser (lxml if available, else xml.etree.ElementTree)
ET = get_element_tree_module()

UTC_TZ = pytz.UTC


def utc_now():
    return util_utc_now()


def local_now():
    return util_local_now()


def parse_nws_datetime(dt_string):
    return util_parse_nws_datetime(dt_string, logger=logging.getLogger(__name__))


def format_local_datetime(dt, include_utc=True):
    return util_format_local_datetime(dt, include_utc=include_utc)


def _env_flag(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on", "t", "y"}


def _serialize_alert_for_sig(alert_elem) -> str:
    """Serialize an alert element preserving original namespace prefixes.

    XML digital signature verification requires that the stored raw_xml uses the
    same namespace prefixes as the original document (e.g. ``ds:`` for XMLdsig).
    The stdlib ElementTree mangler rewrites these as ``ns0:``, ``ns1:`` etc., which
    causes C14N canonicalization to produce bytes that differ from the signed bytes.

    This function always uses lxml when available (lxml preserves nsmap prefix names)
    and falls back to the generic ``ET`` module otherwise (signature verification will
    not succeed but the XML is still stored for display purposes).
    """
    try:
        from lxml import etree as _lxml_et
        return _lxml_et.tostring(alert_elem, encoding='unicode', with_tail=False)
    except ImportError:
        pass
    return ET.tostring(alert_elem, encoding='unicode')

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
    from app_core.models import AlertFilterSettings  # type: ignore
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
        data_source = db.Column(db.String(64))
        details = db.Column(JSON)

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
        # EAS forwarding tracking
        eas_forwarded = Column(Boolean, default=False, nullable=False)
        eas_forwarding_reason = Column(String(255))
        eas_audio_url = Column(String(512))
        # IPAWS signature and enrichment
        signature_verified = Column(Boolean)
        signature_status = Column(String(255))
        certificate_info = Column(JSON)
        ipaws_audio_url = Column(String(512))
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
        details = Column(JSON)

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
        map_center_lat = Column(Float)
        map_center_lng = Column(Float)
        map_default_zoom = Column(Integer)
        updated_at = Column(DateTime, default=utc_now)

    class AlertFilterSettings(Base):
        __tablename__ = 'alert_filter_settings'
        __table_args__ = {'extend_existing': True}
        id = Column(Integer, primary_key=True)
        fips_codes = Column(JSON)
        zone_codes = Column(JSON)
        storage_zone_codes = Column(JSON)
        area_terms = Column(JSON)
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
        same_audio_data = Column(LargeBinary)
        attention_audio_data = Column(LargeBinary)
        tts_audio_data = Column(LargeBinary)
        buffer_audio_data = Column(LargeBinary)
        tts_warning = Column(String(255))
        tts_provider = Column(String(32))
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
        cap_endpoints: Optional[List[str]] = None,
    ):
        self.database_url = database_url

        self.logger = logging.getLogger(__name__)

        # Create engine with retry (for database initialization timing)
        self.engine = self._make_engine_with_retry(self.database_url)
        Session = sessionmaker(bind=self.engine)
        self.db_session = Session()

        self.last_poll_sources: List[str] = []
        self.last_duplicates_filtered: int = 0
        self.last_fetch_errors: List[str] = []  # Track errors during fetch for frontend logging
        self.last_endpoints_by_type: Dict[str, List[str]] = {}  # endpoint_type -> list of URLs polled
        self.last_per_source_errors: Dict[str, List[str]] = {}  # endpoint_type -> list of error msgs

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
        
        # Track when cleanup was last run to avoid expensive operations on every poll
        # Use separate trackers for poll_history and debug_records cleanup
        self._last_poll_history_cleanup_time = None
        self._last_debug_records_cleanup_time = None
        self._cleanup_interval_seconds = 86400  # Run cleanup once per day (24 hours)
        
        # Control debug record persistence to avoid CPU/database overhead
        # Debug records are useful for troubleshooting but expensive (one DB row per alert per poll)
        self._debug_records_enabled = _env_flag('CAP_POLLER_DEBUG_RECORDS', False)

        # Redis client for event publishing
        # Poller publishes events to Redis instead of directly managing EAS/LED/Radio
        redis_host = os.getenv('REDIS_HOST', 'redis')
        redis_port = int(os.getenv('REDIS_PORT', '6379'))
        redis_db = int(os.getenv('REDIS_DB', '0'))
        try:
            self.redis_client = redis.Redis(
                host=redis_host,
                port=redis_port,
                db=redis_db,
                decode_responses=True,
                socket_connect_timeout=5,
                socket_timeout=5
            )
            # Test connection
            self.redis_client.ping()
            self.logger.info(f"Redis client initialized: {redis_host}:{redis_port}/{redis_db}")
        except Exception as exc:
            self.logger.warning(f"Redis unavailable: {exc}. Event publishing will be disabled.")
            self.redis_client = None

        # EAS broadcast configuration for automatic alert forwarding.
        # Pass self.db_session so that TTS settings can be read directly
        # from the database even though this process has no Flask app context.
        try:
            self.eas_config = load_eas_config(db_session=self.db_session)
            if self.eas_config.get('enabled'):
                self.logger.info("EAS auto-forwarding enabled (originator=%s, station=%s)",
                                 self.eas_config.get('originator'), self.eas_config.get('station_id'))
                tts_provider = self.eas_config.get('tts_provider', '')
                if tts_provider:
                    self.logger.info("TTS provider loaded for auto-forwarding: %s", tts_provider)
                else:
                    self.logger.info("No TTS provider configured; voice narration will be skipped")
            else:
                self.logger.info("EAS broadcasting is disabled; alerts will be stored but not auto-forwarded")
        except Exception as exc:
            self.logger.warning("Failed to load EAS config for auto-forwarding: %s", exc)
            self.eas_config = {'enabled': False}

        # HTTP Session with compliance headers for both NOAA and IPAWS
        # NOAA Weather API: https://www.weather.gov/documentation/services-web-api
        # - Requires User-Agent with contact info
        # - Returns application/geo+json for CAP alerts
        # IPAWS/FEMA: https://www.fema.gov/about/openfema/data-sets
        # - Returns application/atom+xml or application/cap+xml
        # - Accepts wildcard or specific XML formats
        self.session = requests.Session()
        # Prefer DB setting, fall back to env var for backwards compatibility
        db_user_agent = None
        try:
            _ps = PollerSettings.query.first()
            if _ps and _ps.noaa_user_agent:
                db_user_agent = _ps.noaa_user_agent
        except Exception:
            pass
        default_user_agent = (
            db_user_agent
            or os.getenv('NOAA_USER_AGENT', '')
            or 'EAS Station/2.12 (+https://github.com/KR8MER/eas-station; support@easstation.com)'
        )
        self.session.headers.update({
            'User-Agent': default_user_agent,
            # Accept multiple formats: geo+json (NOAA), atom+xml (IPAWS), cap+xml (generic CAP)
            'Accept': 'application/geo+json, application/atom+xml, application/cap+xml, application/xml, application/json;q=0.9',
        })
        # CRITICAL: Disable proxy to allow direct connections to external CAP feeds
        # Only nginx should act as reverse proxy; outbound HTTP must bypass HTTP_PROXY env vars
        self.session.proxies = {'http': None, 'https': None}
        # Configure SSL certificate verification
        ssl_verify_disable = os.getenv('SSL_VERIFY_DISABLE', '').strip().lower() in ('1', 'true', 'yes')
        ca_bundle_override = os.getenv('REQUESTS_CA_BUNDLE') or os.getenv('CAP_POLLER_CA_BUNDLE')

        if ssl_verify_disable:
            self.logger.warning('⚠️  SSL certificate verification is DISABLED (SSL_VERIFY_DISABLE=1). This is insecure and not recommended for production.')
            self.session.verify = False
        elif ca_bundle_override:
            self.logger.info('Using custom CA bundle for CAP polling: %s', ca_bundle_override)
            self.session.verify = ca_bundle_override
        else:
            # Try system CA bundle first (more up-to-date), fall back to certifi
            system_ca_bundle = '/etc/ssl/certs/ca-certificates.crt'
            if os.path.exists(system_ca_bundle):
                self.logger.info('Using system CA bundle for SSL verification: %s', system_ca_bundle)
                self.session.verify = system_ca_bundle
            else:
                certifi_path = certifi.where()
                self.logger.info('Using certifi CA bundle for SSL verification: %s', certifi_path)
                self.session.verify = certifi_path

        # Endpoint configuration - Unified multi-source polling
        # The poller automatically polls all configured sources (NOAA, IPAWS, custom)
        # Feed URLs are now stored in the poller_settings table.

        configured_endpoints: List[str] = []

        def _extend_from_list(url_list) -> None:
            if not url_list:
                return
            for url in url_list:
                cleaned = url.strip() if isinstance(url, str) else ''
                if cleaned:
                    configured_endpoints.append(cleaned)

        def _extend_from_csv(csv_value: Optional[str]) -> None:
            if not csv_value:
                return
            for endpoint in csv_value.split(','):
                cleaned = endpoint.strip()
                if cleaned:
                    configured_endpoints.append(cleaned)

        # Read feed URLs from database (preferred), falling back to env vars
        try:
            _db_ps = PollerSettings.query.first()
            if _db_ps:
                _extend_from_list(_db_ps.cap_endpoints)
                _extend_from_list(_db_ps.ipaws_feed_urls)
        except Exception as _exc:
            self.logger.debug("Could not read feed URLs from DB, falling back to env vars: %s", _exc)
            _db_ps = None
            _extend_from_csv(os.getenv('CAP_ENDPOINTS'))
            _extend_from_csv(os.getenv('IPAWS_CAP_FEED_URLS'))

        if cap_endpoints:
            configured_endpoints.extend([endpoint for endpoint in cap_endpoints if endpoint])

        # Calculate default timestamp for IPAWS URLs with {timestamp} placeholder
        # Prefer DB setting, fall back to env var
        lookback_hours_int = 12
        try:
            if _db_ps and _db_ps.ipaws_default_lookback_hours:
                lookback_hours_int = max(1, _db_ps.ipaws_default_lookback_hours)
            else:
                lookback_hours_int = max(1, int(os.getenv('IPAWS_DEFAULT_LOOKBACK_HOURS', '12')))
        except (ValueError, TypeError):
            lookback_hours_int = 12

        default_start = (utc_now() - timedelta(hours=lookback_hours_int)).strftime('%Y-%m-%dT%H:%M:%SZ')
        override_start = (os.getenv('IPAWS_DEFAULT_START') or '').strip()
        if override_start:
            default_start = override_start

        def _truncate_url(url: str, max_len: int = 60) -> str:
            """Truncate URL for logging purposes."""
            return url[:max_len] + '...' if len(url) > max_len else url

        if configured_endpoints:
            # Process {timestamp} placeholders in configured URLs
            # This handles URLs saved via the UI with template placeholders
            processed_endpoints: List[str] = []
            for endpoint in configured_endpoints:
                if '{timestamp}' in endpoint:
                    try:
                        processed_endpoint = endpoint.format(timestamp=default_start)
                        processed_endpoints.append(processed_endpoint)
                        self.logger.debug(
                            "Processed timestamp placeholder in URL: %s -> %s",
                            _truncate_url(endpoint),
                            _truncate_url(processed_endpoint),
                        )
                    except Exception as exc:
                        self.logger.warning(
                            "Failed to process timestamp placeholder in URL '%s': %s. Using URL as-is.",
                            _truncate_url(endpoint),
                            exc,
                        )
                        processed_endpoints.append(endpoint)
                else:
                    processed_endpoints.append(endpoint)

            # Preserve order but remove duplicates
            seen: Set[str] = set()
            unique_endpoints: List[str] = []
            for endpoint in processed_endpoints:
                if endpoint not in seen:
                    unique_endpoints.append(endpoint)
                    seen.add(endpoint)

            # ALWAYS add NOAA zone-based endpoints alongside configured IPAWS/custom feeds.
            # PollerSettings.cap_endpoints is documented as "in addition to built-in NOAA feeds"
            # but the original code skipped NOAA entirely when any configured endpoint existed.
            noaa_endpoints = self._build_batched_noaa_endpoints(
                self.location_settings['zone_codes'] or DEFAULT_LOCATION_SETTINGS['zone_codes']
            )
            for ep in noaa_endpoints:
                if ep not in seen:
                    unique_endpoints.append(ep)
                    seen.add(ep)
            if noaa_endpoints:
                self.logger.info(
                    "Added %d NOAA zone endpoint(s) alongside configured feeds", len(noaa_endpoints)
                )

            self.cap_endpoints = unique_endpoints
        else:
            # No explicit endpoints configured - build defaults for both NOAA and IPAWS
            default_endpoints: List[str] = []
            
            # Add IPAWS endpoint
            endpoint_template = (
                os.getenv(
                    'IPAWS_DEFAULT_ENDPOINT_TEMPLATE',
                    'https://apps.fema.gov/IPAWSOPEN_EAS_SERVICE/rest/public/recent/{timestamp}',
                )
                or 'https://apps.fema.gov/IPAWSOPEN_EAS_SERVICE/rest/public/recent/{timestamp}'
            )
            try:
                ipaws_endpoint = endpoint_template.format(timestamp=default_start)
            except Exception:
                ipaws_endpoint = endpoint_template

            default_endpoints.append(ipaws_endpoint)
            self.logger.info("Added default IPAWS endpoint (starting %s)", default_start)
            
            # Add NOAA endpoints
            # Batch zone codes into single requests to reduce API calls
            noaa_endpoints = self._build_batched_noaa_endpoints(
                self.location_settings['zone_codes'] or DEFAULT_LOCATION_SETTINGS['zone_codes']
            )
            default_endpoints.extend(noaa_endpoints)
            self.logger.info("Added %d NOAA endpoint(s)", len(noaa_endpoints))
            
            self.cap_endpoints = default_endpoints
            
            if not default_endpoints:
                self.logger.warning("No endpoints configured and no defaults could be generated")

        self.zone_codes = set(self.location_settings['zone_codes'])
        fips_codes, _ = sanitize_fips_codes(self.location_settings.get('fips_codes'))
        self.same_codes = {code for code in fips_codes if code}
        # Storage zone codes: UGC/zone codes that should trigger storage (in addition to SAME codes)
        self.storage_zone_codes = set(self.location_settings.get('storage_zone_codes', []))

        # Log configuration for troubleshooting alert matching issues
        self.logger.info(f"📍 Location: {self.location_name} ({self.county_upper})")
        self.logger.info(f"📋 Zone codes: {sorted(self.zone_codes)}")
        self.logger.info(f"🔢 SAME/FIPS codes: {sorted(self.same_codes)}")
        self.logger.info(f"💾 Storage zone codes: {sorted(self.storage_zone_codes)}")

    def _reload_location_settings(self) -> bool:
        """Reload location settings from database to pick up changes made via admin UI.

        Returns True if settings changed, False otherwise.
        """
        try:
            new_settings = self._load_location_settings()

            # Check if anything relevant changed
            old_zone_codes = self.zone_codes
            old_same_codes = self.same_codes
            old_storage_zone_codes = self.storage_zone_codes

            new_zone_codes = set(new_settings.get('zone_codes', []))
            fips_codes, _ = sanitize_fips_codes(new_settings.get('fips_codes'))
            new_same_codes = {code for code in fips_codes if code}
            new_storage_zone_codes = set(new_settings.get('storage_zone_codes', []))

            changed = (
                old_zone_codes != new_zone_codes or
                old_same_codes != new_same_codes or
                old_storage_zone_codes != new_storage_zone_codes
            )

            if changed:
                self.location_settings = new_settings
                self.location_name = f"{new_settings['county_name']}, {new_settings['state_code']}".strip(', ')
                self.county_upper = new_settings['county_name'].upper()
                self.zone_codes = new_zone_codes
                self.same_codes = new_same_codes
                self.storage_zone_codes = new_storage_zone_codes

                self.logger.info("🔄 Location settings reloaded from database")
                self.logger.info(f"📋 Zone codes: {sorted(self.zone_codes)}")
                self.logger.info(f"🔢 SAME/FIPS codes: {sorted(self.same_codes)}")
                self.logger.info(f"💾 Storage zone codes: {sorted(self.storage_zone_codes)}")

                # Rebuild NOAA endpoints if zone codes changed
                if old_zone_codes != new_zone_codes:
                    new_noaa_endpoints = self._build_batched_noaa_endpoints(list(new_zone_codes))
                    # Keep IPAWS endpoints, replace NOAA endpoints
                    ipaws_endpoints = [ep for ep in self.cap_endpoints if 'fema.gov' in ep or 'IPAWS' in ep]
                    self.cap_endpoints = ipaws_endpoints + new_noaa_endpoints
                    self.logger.info(f"🌐 Rebuilt NOAA endpoints: {len(new_noaa_endpoints)} endpoint(s) for {len(new_zone_codes)} zone(s)")

                return True

            return False
        except Exception as e:
            self.logger.warning(f"Failed to reload location settings: {e}")
            return False

    # ---------- NOAA API Batching ----------
    def _build_batched_noaa_endpoints(self, zone_codes: List[str], max_url_length: int = 2000) -> List[str]:
        """Build batched NOAA API endpoints by combining zone codes.
        
        The NOAA Weather API supports comma-separated zone codes in a single request,
        which dramatically reduces the number of API calls needed. For example:
        - Before: 16 requests (one per zone code)
        - After: 1-2 requests (all zones combined)
        
        This prevents rate limiting and reduces load on the NOAA API.
        
        Args:
            zone_codes: List of zone codes (e.g., ['OHZ004', 'OHZ005', 'OHC137'])
            max_url_length: Maximum URL length to stay compatible with servers/proxies
            
        Returns:
            List of batched endpoint URLs
        """
        if not zone_codes:
            self.logger.warning("_build_batched_noaa_endpoints called with empty zone_codes - no NOAA endpoints will be created!")
            return []

        self.logger.info(f"Building NOAA endpoints for zone codes: {zone_codes}")
        base_url = "https://api.weather.gov/alerts/active?zone="
        base_len = len(base_url)
        
        endpoints: List[str] = []
        current_batch: List[str] = []
        current_len = base_len
        
        for code in zone_codes:
            # Each code adds its length plus a comma (except for first in batch)
            code_len = len(code) + (1 if current_batch else 0)  # +1 for comma separator
            
            if current_len + code_len > max_url_length and current_batch:
                # Current batch would exceed limit, finalize it and start new batch
                endpoints.append(base_url + ",".join(current_batch))
                current_batch = [code]
                current_len = base_len + len(code)
            else:
                current_batch.append(code)
                current_len += code_len
        
        # Add final batch
        if current_batch:
            endpoints.append(base_url + ",".join(current_batch))

        # Log batching info when multiple zones are combined into fewer requests
        if len(zone_codes) > 1 and len(endpoints) < len(zone_codes):
            self.logger.info(
                f"Batched {len(zone_codes)} zone codes into {len(endpoints)} API request(s) to reduce rate limiting"
            )

        # Log the generated endpoints
        for ep in endpoints:
            self.logger.info(f"Generated NOAA endpoint: {ep}")

        return endpoints

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

    def _publish_alert_event(self, channel: str, alert_data: Dict[str, Any]) -> None:
        """Publish alert event to Redis for other services to consume.
        
        Args:
            channel: Redis channel name (e.g., 'alerts:new', 'alerts:led')
            alert_data: Alert data payload to publish
        """
        if not self.redis_client:
            self.logger.debug("Redis client not available, skipping event publish")
            return
        
        try:
            # Validate inputs
            if not channel or not isinstance(channel, str):
                self.logger.error(f"Invalid Redis channel: {channel}")
                return
                
            if not isinstance(alert_data, dict):
                self.logger.error(f"Alert data must be dict, got {type(alert_data).__name__}")
                return
            
            # Convert datetime objects to ISO format strings for JSON serialization
            serializable_data = {}
            for key, value in alert_data.items():
                try:
                    if isinstance(value, datetime):
                        serializable_data[key] = value.isoformat()
                    elif value is None:
                        serializable_data[key] = None
                    elif isinstance(value, (str, int, float, bool)):
                        serializable_data[key] = value
                    elif isinstance(value, (list, dict)):
                        # Will be handled by json_dumps, but check for nested datetimes
                        serializable_data[key] = value
                    else:
                        # Convert other types to string
                        serializable_data[key] = str(value)
                except Exception as convert_err:
                    self.logger.warning(
                        f"Failed to serialize field '{key}' (type {type(value).__name__}): {convert_err}"
                    )
                    serializable_data[key] = None
            
            try:
                payload = json_dumps(serializable_data)
            except (TypeError, ValueError) as json_err:
                self.logger.error(
                    f"Failed to serialize alert data to JSON for channel {channel}: {json_err}. "
                    f"Keys: {list(serializable_data.keys())}"
                )
                return
            
            try:
                subscribers = self.redis_client.publish(channel, payload)
                self.logger.debug(f"Published alert event to {channel} ({subscribers} subscribers)")
            except Exception as pub_err:
                self.logger.error(
                    f"Redis publish failed for channel {channel}: {type(pub_err).__name__}: {pub_err}"
                )
                
        except Exception as exc:
            self.logger.error(
                f"Unexpected error publishing to Redis channel {channel}: {type(exc).__name__}: {exc}"
            )

    # ---------- Engine with retry ----------
    def _load_location_settings(self) -> Dict[str, Any]:
        defaults = dict(DEFAULT_LOCATION_SETTINGS)
        settings: Dict[str, Any] = dict(defaults)

        try:
            # Expire cached objects to ensure we read fresh data from database
            # This is important when the web app has updated settings
            self.db_session.expire_all()
            record = self.db_session.query(LocationSettings).order_by(LocationSettings.id).first()
            filter_record = self.db_session.query(AlertFilterSettings).order_by(AlertFilterSettings.id).first()
            if record:
                settings.update({
                    'county_name': record.county_name or defaults['county_name'],
                    'state_code': (record.state_code or defaults['state_code']).upper(),
                    'timezone': record.timezone or defaults['timezone'],
                    'map_center_lat': record.map_center_lat or defaults['map_center_lat'],
                    'map_center_lng': record.map_center_lng or defaults['map_center_lng'],
                    'map_default_zoom': record.map_default_zoom or defaults['map_default_zoom'],
                })
            else:
                self.logger.info("No location settings found; using defaults")
            if filter_record:
                fips_codes, _ = sanitize_fips_codes(filter_record.fips_codes or defaults['fips_codes'])
                storage_zones = filter_record.storage_zone_codes
                settings.update({
                    'zone_codes': normalise_upper(filter_record.zone_codes) or list(defaults['zone_codes']),
                    'storage_zone_codes': normalise_upper(storage_zones) if storage_zones else list(defaults['storage_zone_codes']),
                    'fips_codes': fips_codes or list(defaults['fips_codes']),
                    'area_terms': normalise_upper(filter_record.area_terms) or list(defaults['area_terms']),
                })
            else:
                self.logger.info("No alert filter settings found; using defaults")
        except Exception as exc:  # pragma: no cover - defensive logging
            self.logger.error(
                "Failed to load location settings from DB: %s. "
                "Falling back to defaults — rolling back DB session to prevent "
                "subsequent queries from failing with InFailedSqlTransaction.",
                exc,
            )
            try:
                self.db_session.rollback()
            except Exception as rb_exc:
                self.logger.warning("Session rollback after location settings failure also failed: %s", rb_exc)

        if not settings['zone_codes']:
            settings['zone_codes'] = list(defaults['zone_codes'])
        if not settings.get('storage_zone_codes'):
            settings['storage_zone_codes'] = list(defaults['storage_zone_codes'])
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
        
        # If we get here, all retries failed
        # Sleep for a longer period before raising to prevent service restart loops
        self.logger.error(
            f"Failed to connect to database after {retries} attempts. "
            f"Sleeping for 60 seconds before exit to prevent restart loop."
        )
        time.sleep(60)
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
            root = parse_xml_string(xml_text)
        except Exception as exc:
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
        resources = self._extract_cap_resources(info_elem, ns)

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
            'resources': resources,
            'source': ALERT_SOURCE_IPAWS,
        }

        if not properties['identifier']:
            fallback = f"{properties.get('event', 'Unknown')}|{properties.get('sent', '')}"
            # md5 here is a non-security deterministic dedup key; switching algorithms
            # would orphan rows already stored under the original fingerprint.
            properties['identifier'] = f"ipaws_{hashlib.md5(fallback.encode()).hexdigest()[:16]}"  # noqa: S324

        feature = {
            'type': 'Feature',
            'properties': properties,
            'geometry': geometry,
            # Serialize using lxml to preserve original namespace prefixes (e.g. ds:, capsig:).
            # This is required for XML digital signature verification: C14N of SignedInfo
            # must produce the same bytes as the original signed document.  stdlib
            # ElementTree mangles prefixes (ns0:, ns1:) which breaks C14N byte-matching.
            'raw_xml': _serialize_alert_for_sig(alert_elem),
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

    def _extract_cap_resources(self, info_elem: Optional[ET.Element], ns: Dict[str, str]) -> List[Dict[str, str]]:
        """Extract resource elements from CAP info block.
        
        CAP 1.2 alerts can contain <resource> elements with embedded or linked content,
        including audio files. IPAWS alerts often include pre-recorded audio messages.
        
        Returns:
            List of resource dicts with keys: resourceDesc, mimeType, uri, derefUri, digest
        """
        resources: List[Dict[str, str]] = []
        if info_elem is None:
            return resources

        for resource in info_elem.findall('cap:resource', ns):
            resource_dict: Dict[str, str] = {}
            
            # Required fields
            resource_desc = resource.findtext('cap:resourceDesc', default='', namespaces=ns)
            if resource_desc:
                resource_dict['resourceDesc'] = resource_desc.strip()
            
            mime_type = resource.findtext('cap:mimeType', default='', namespaces=ns)
            if mime_type:
                resource_dict['mimeType'] = mime_type.strip()
            
            # Optional fields - URI for external resource
            uri = resource.findtext('cap:uri', default='', namespaces=ns)
            if uri:
                resource_dict['uri'] = uri.strip()
            
            # Optional fields - derefUri for base64-encoded inline content
            deref_uri = resource.findtext('cap:derefUri', default='', namespaces=ns)
            if deref_uri:
                resource_dict['derefUri'] = deref_uri.strip()
            
            # Optional fields - digest for integrity verification
            digest = resource.findtext('cap:digest', default='', namespaces=ns)
            if digest:
                resource_dict['digest'] = digest.strip()
            
            # Size in bytes (optional)
            size = resource.findtext('cap:size', default='', namespaces=ns)
            if size:
                resource_dict['size'] = size.strip()
            
            # Only include if we have at least a description or URI
            if resource_dict.get('resourceDesc') or resource_dict.get('uri') or resource_dict.get('derefUri'):
                resources.append(resource_dict)
                
                # Log audio resources for debugging
                if mime_type and 'audio' in mime_type.lower():
                    self.logger.info(
                        f"Found audio resource in CAP alert: {resource_desc or 'unnamed'} "
                        f"(type: {mime_type}, uri: {uri[:50] + '...' if uri and len(uri) > 50 else uri or 'embedded'})"
                    )

        return resources

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
                
                # Validate coordinate ranges
                if not (-90 <= lat <= 90):
                    self.logger.warning(f"Invalid latitude {lat} in polygon, skipping coordinate")
                    continue
                if not (-180 <= lon <= 180):
                    self.logger.warning(f"Invalid longitude {lon} in polygon, skipping coordinate")
                    continue
                    
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
        """Parse CAP circle element into polygon coordinates.
        
        Args:
            circle_text: CAP circle string format "lat,lon radius_km"
            points: Number of points to approximate circle (default 36)
            
        Returns:
            List of [lon, lat] coordinate pairs, or None if invalid
        """
        if not circle_text:
            return None

        parts = circle_text.strip().split()
        if not parts:
            self.logger.debug("Empty circle text after stripping whitespace")
            return None

        try:
            if ',' not in parts[0]:
                self.logger.warning(f"Invalid circle format (missing comma): '{circle_text[:50]}'")
                return None
                
            lat_str, lon_str = parts[0].split(',', 1)
            lat = float(lat_str)
            lon = float(lon_str)
            
            # Validate coordinate ranges
            if not (-90 <= lat <= 90):
                self.logger.warning(f"Circle latitude out of range: {lat} (must be -90 to 90)")
                return None
            if not (-180 <= lon <= 180):
                self.logger.warning(f"Circle longitude out of range: {lon} (must be -180 to 180)")
                return None
                
        except ValueError as e:
            self.logger.warning(f"Invalid circle coordinates: '{parts[0]}' - {e}")
            return None
        except Exception as e:
            self.logger.error(f"Unexpected error parsing circle coordinates: {e}")
            return None

        radius_km = 0.0
        if len(parts) > 1:
            try:
                radius_km = float(parts[1])
            except ValueError as e:
                self.logger.warning(f"Invalid circle radius: '{parts[1]}' - {e}")
                radius_km = 0.0

        if radius_km <= 0:
            self.logger.warning(f"Circle radius must be positive: {radius_km} km")
            return None
            
        if radius_km > 20000:  # Earth's half-circumference
            self.logger.warning(f"Circle radius unreasonably large: {radius_km} km (max 20000 km)")
            return None

        return self._approximate_circle_polygon(lat, lon, radius_km, points)

    def _approximate_circle_polygon(self, lat: float, lon: float, radius_km: float, points: int) -> List[List[float]]:
        """Approximate a circle as a polygon using haversine formula.
        
        Args:
            lat: Center latitude in degrees
            lon: Center longitude in degrees
            radius_km: Radius in kilometers
            points: Number of points to use for approximation
            
        Returns:
            List of [lon, lat] coordinate pairs forming a closed ring
            
        Raises:
            ValueError: If inputs are invalid
        """
        coords: List[List[float]] = []
        
        # Validate inputs
        if not (-90 <= lat <= 90):
            raise ValueError(f"Latitude must be -90 to 90, got {lat}")
        if not (-180 <= lon <= 180):
            raise ValueError(f"Longitude must be -180 to 180, got {lon}")
        if radius_km <= 0:
            raise ValueError(f"Radius must be positive, got {radius_km}")
        if points < 3:
            raise ValueError(f"Need at least 3 points for polygon, got {points}")
        
        # Handle edge case: circles at or near poles
        if abs(lat) > 89.5:
            self.logger.warning(
                f"Circle center at extreme latitude ({lat:.2f}°) - using simplified rectangular approximation. "
                f"Haversine formula unreliable near poles."
            )
            # For near-pole circles, use a simplified square approximation
            offset = radius_km / 111.0  # Rough km to degrees conversion
            coords = [
                [lon - offset, min(89.9, lat + offset)],
                [lon + offset, min(89.9, lat + offset)],
                [lon + offset, max(-89.9, lat - offset)],
                [lon - offset, max(-89.9, lat - offset)],
                [lon - offset, min(89.9, lat + offset)],  # Close ring
            ]
            return coords
        
        # Handle edge case: very large radius
        if radius_km > 10000:
            self.logger.warning(
                f"Circle radius very large ({radius_km:.0f} km) - may produce distorted geometry"
            )
        
        try:
            radius_ratio = radius_km / 6371.0  # Earth radius in km
            center_lat = math.radians(lat)
            center_lon = math.radians(lon)

            for step in range(points):
                bearing = 2 * math.pi * (step / points)
                sin_lat = math.sin(center_lat)
                cos_lat = math.cos(center_lat)
                sin_radius = math.sin(radius_ratio)
                cos_radius = math.cos(radius_ratio)

                # Haversine formula for point on great circle
                lat_rad = math.asin(
                    sin_lat * cos_radius + cos_lat * sin_radius * math.cos(bearing)
                )
                
                # Handle potential division by zero when cos_lat is very small
                if abs(cos_lat) < 1e-10:
                    self.logger.warning(f"cos_lat near zero at {lat}°, using center longitude")
                    lon_rad = center_lon
                else:
                    lon_rad = center_lon + math.atan2(
                        math.sin(bearing) * sin_radius * cos_lat,
                        cos_radius - sin_lat * math.sin(lat_rad)
                    )

                # Convert to degrees and validate
                lon_deg = math.degrees(lon_rad)
                lat_deg = math.degrees(lat_rad)
                
                # Normalize longitude to -180 to 180
                while lon_deg > 180:
                    lon_deg -= 360
                while lon_deg < -180:
                    lon_deg += 360
                
                # Clamp latitude to valid range
                lat_deg = max(-90, min(90, lat_deg))
                
                coords.append([lon_deg, lat_deg])

        except (ValueError, OverflowError) as e:
            self.logger.error(
                f"Math error approximating circle at ({lat}, {lon}) radius {radius_km}km: {e}. "
                f"Falling back to simple square."
            )
            # Fallback to simple square on math error
            offset = radius_km / 111.0
            coords = [
                [lon - offset, min(89.9, lat + offset)],
                [lon + offset, min(89.9, lat + offset)],
                [lon + offset, max(-89.9, lat - offset)],
                [lon - offset, max(-89.9, lat - offset)],
                [lon - offset, min(89.9, lat + offset)],
            ]
            return coords

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
        signature_cache: Set[str] = set()
        alerts_by_identifier: Dict[str, Dict] = {}
        alerts_without_identifier: List[Dict] = []

        # Reset error tracking for this fetch cycle
        self.last_fetch_errors = []
        endpoints_by_type: Dict[str, List[str]] = {}
        per_source_errors: Dict[str, List[str]] = {}

        for endpoint in self.cap_endpoints:
            # Determine endpoint type before the try block so errors are attributed correctly
            if 'tdl.apps.fema.gov' in endpoint:
                endpoint_type = "IPAWS"
            elif 'apps.fema.gov' in endpoint:
                endpoint_type = "IPAWS"
            elif 'weather.gov' in endpoint:
                endpoint_type = "NOAA"
            else:
                endpoint_type = "CUSTOM"
            endpoints_by_type.setdefault(endpoint_type, []).append(endpoint)

            try:
                self.logger.info(f"Fetching alerts from: {endpoint}")
                self.logger.info(f"  -> Making HTTP GET request...")
                response = self.session.get(endpoint, timeout=timeout)
                self.logger.info(f"  -> Response status: {response.status_code}")
                self.logger.info(f"  -> Response headers: Content-Type={response.headers.get('Content-Type', 'N/A')}, Content-Length={response.headers.get('Content-Length', 'N/A')}")

                # Check for rate limiting before raising for other status codes
                if response.status_code == 429:
                    retry_after = response.headers.get('Retry-After', 'unknown')
                    self.logger.warning(
                        f"Rate limited by {endpoint} (HTTP 429). Retry-After: {retry_after}. "
                        f"Consider increasing poll interval to avoid API rate limits."
                    )
                    continue  # Skip this endpoint and move to next
                elif response.status_code == 503:
                    self.logger.warning(
                        f"Service unavailable from {endpoint} (HTTP 503). "
                        f"API may be overloaded or blocking requests."
                    )
                    continue  # Skip this endpoint and move to next
                
                response.raise_for_status()
                features = self._parse_feed_payload(response)
                self.logger.info(f"Retrieved {len(features)} alerts from {endpoint}")

                # endpoint_type already determined above before the try block

                # Log summary of what was fetched from this endpoint
                self.logger.info(f"=" * 60)
                self.logger.info(f"ENDPOINT: {endpoint_type}")
                self.logger.info(f"URL: {endpoint}")
                self.logger.info(f"ALERTS RETURNED: {len(features)}")
                if features:
                    for i, feat in enumerate(features[:10]):  # Show first 10
                        props = feat.get('properties', {})
                        event = props.get('event', 'Unknown')
                        identifier = props.get('identifier') or props.get('id') or 'No ID'
                        geocode = props.get('geocode', {}) or {}
                        ugc_codes = geocode.get('UGC', []) or []
                        same_codes = geocode.get('SAME', []) or []
                        self.logger.info(f"  [{i+1}] [{endpoint_type}] {event}")
                        self.logger.info(f"      ID: {identifier[:50]}{'...' if len(identifier) > 50 else ''}")
                        self.logger.info(f"      UGC: {ugc_codes[:5]}{'...' if len(ugc_codes) > 5 else ''}")
                        self.logger.info(f"      SAME: {same_codes[:5]}{'...' if len(same_codes) > 5 else ''}")
                    if len(features) > 10:
                        self.logger.info(f"  ... and {len(features) - 10} more alerts from {endpoint_type}")
                else:
                    self.logger.info(f"  (no alerts from {endpoint_type})")
                self.logger.info(f"=" * 60)
                for alert in features:
                    props = alert.get('properties', {})
                    # Track which endpoint this alert came from
                    props['_fetch_endpoint'] = endpoint
                    props['_fetch_endpoint_type'] = endpoint_type

                    # NOAA API uses 'id' field, IPAWS/CAP uses 'identifier' - check both
                    identifier = (props.get('identifier') or props.get('id') or '').strip()
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

                    sender_name = (props.get('senderName') or '').strip().upper()
                    sent_value = (props.get('sent') or '').strip()
                    headline_value = (props.get('headline') or '').strip()
                    signature_parts = [canonical_source or ALERT_SOURCE_UNKNOWN, identifier, sender_name, sent_value, headline_value]
                    signature_text = "|".join(signature_parts)
                    signature_hash = hashlib.sha256(signature_text.encode('utf-8', 'ignore')).hexdigest()

                    if signature_hash in signature_cache:
                        duplicates_filtered += 1
                        self.logger.info(
                            "Duplicate NOAA/IPAWS payload skipped (source=%s, identifier=%s)",
                            canonical_source,
                            identifier or 'unknown',
                        )
                        continue

                    signature_cache.add(signature_hash)

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
                error_msg = (
                    f"TLS certificate verification failed for {endpoint}: {str(exc)}. "
                    f"Provide a CA bundle via REQUESTS_CA_BUNDLE or CAP_POLLER_CA_BUNDLE if your environment "
                    f"uses custom certificates, or set SSL_VERIFY_DISABLE=1 to disable verification (not recommended)."
                )
                self.logger.error(error_msg)
                self.last_fetch_errors.append(f"SSL Error: {error_msg}")
                per_source_errors.setdefault(endpoint_type, []).append(f"SSL Error: {error_msg}")
            except requests.exceptions.Timeout as exc:
                error_msg = (
                    f"Timeout fetching from {endpoint} after {timeout}s. "
                    f"API may be slow or rate limiting requests. Error: {str(exc)}"
                )
                self.logger.error(error_msg)
                self.last_fetch_errors.append(f"Timeout: {error_msg}")
                per_source_errors.setdefault(endpoint_type, []).append(f"Timeout: {error_msg}")
            except requests.exceptions.RequestException as exc:
                error_msg = f"Error fetching from {endpoint}: {str(exc)}"
                self.logger.error(error_msg)
                self.last_fetch_errors.append(f"Request Error: {error_msg}")
                per_source_errors.setdefault(endpoint_type, []).append(f"Request Error: {error_msg}")
            except Exception as exc:
                error_msg = f"Unexpected error fetching from {endpoint}: {str(exc)}"
                self.logger.error(error_msg)
                self.last_fetch_errors.append(f"Unexpected Error: {error_msg}")
                per_source_errors.setdefault(endpoint_type, []).append(f"Unexpected Error: {error_msg}")

        unique_alerts.extend(alerts_by_identifier.values())
        unique_alerts.extend(alerts_without_identifier)

        self.last_poll_sources = sorted(sources_seen)
        self.last_duplicates_filtered = duplicates_filtered
        self.last_endpoints_by_type = endpoints_by_type
        self.last_per_source_errors = per_source_errors

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
            return json_loads(json_dumps(value))
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
        r"""Validate UGC code format: [A-Z]{2}[CZ]\d{3} (e.g., OHZ016, OHC137)."""
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
            'is_storage_relevant': False,  # True only if SAME code matches (for storage/boundaries)
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

            # DEBUG: Log the matching comparison with endpoint source
            endpoint_type = properties.get('_fetch_endpoint_type', 'UNKNOWN')
            fetch_endpoint = properties.get('_fetch_endpoint', 'UNKNOWN')
            self.logger.info(f"  MATCHING CHECK for: {event}")
            self.logger.info(f"    Source endpoint: [{endpoint_type}] {fetch_endpoint}")
            self.logger.info(f"    Alert UGC codes: {normalized_ugc}")
            self.logger.info(f"    Alert SAME codes: {normalized_same}")
            self.logger.info(f"    Our zone codes: {sorted(self.zone_codes)}")
            self.logger.info(f"    Our SAME codes: {sorted(self.same_codes)}")
            self.logger.info(f"    Our storage zones: {sorted(self.storage_zone_codes)}")

            # Check for matches
            ugc_intersection = set(normalized_ugc) & self.zone_codes
            same_intersection = set(normalized_same) & self.same_codes
            self.logger.info(f"    UGC intersection: {ugc_intersection if ugc_intersection else 'NONE'}")
            self.logger.info(f"    SAME intersection: {same_intersection if same_intersection else 'NONE'}")

            for same in normalized_same:
                if same in self.same_codes:
                    message = f"✓ Alert ACCEPTED by SAME: {event} ({same}) [STORAGE+BROADCAST]"
                    result.update(
                        {
                            'is_relevant': True,
                            'is_storage_relevant': True,  # SAME match = store + calculate boundaries
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
                        message = f"✓ Alert ACCEPTED by statewide SAME: {event} ({same}) [STORAGE+BROADCAST]"
                        result.update(
                            {
                                'is_relevant': True,
                                'is_storage_relevant': True,  # Statewide SAME match = store + calculate boundaries
                                'reason': 'SAME_MATCH',
                                'matched_ugc': same,
                                'relevance_matches': [same],
                                'log': {'level': 'info', 'message': message},
                            }
                        )
                        return result

            # Check ALL matching UGC codes - if ANY match storage_zone_codes, store the alert
            matched_zone_ugcs: List[str] = []
            matched_storage_ugcs: List[str] = []
            for ugc in normalized_ugc:
                if ugc in self.zone_codes:
                    matched_zone_ugcs.append(ugc)
                    if ugc in self.storage_zone_codes:
                        matched_storage_ugcs.append(ugc)

            if matched_zone_ugcs:
                # Determine storage relevance: True if ANY matched UGC is in storage_zone_codes
                is_storage_relevant = len(matched_storage_ugcs) > 0
                # Use the first storage match for logging, or first zone match if no storage match
                primary_ugc = matched_storage_ugcs[0] if matched_storage_ugcs else matched_zone_ugcs[0]
                if is_storage_relevant:
                    message = f"✓ Alert ACCEPTED by UGC: {event} ({primary_ugc}) [STORAGE+BROADCAST]"
                    if len(matched_storage_ugcs) > 1:
                        message += f" (+{len(matched_storage_ugcs) - 1} more storage zones)"
                else:
                    message = f"✓ Alert ACCEPTED by UGC: {event} ({primary_ugc}) [BROADCAST ONLY - no storage/boundaries]"
                result.update(
                    {
                        'is_relevant': True,
                        'is_storage_relevant': is_storage_relevant,
                        'reason': 'UGC_MATCH',
                        'matched_ugc': primary_ugc,
                        'relevance_matches': matched_storage_ugcs if matched_storage_ugcs else matched_zone_ugcs,
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
            # NOAA API uses 'id' field, IPAWS/CAP uses 'identifier' - check both
            identifier = properties.get('identifier') or properties.get('id')
            if not identifier:
                event = properties.get('event', 'Unknown')
                sent = properties.get('sent', str(time.time()))
                # md5 here is a non-security deterministic dedup key; switching algorithms
                # would orphan rows already stored under the original fingerprint.
                identifier = f"temp_{hashlib.md5((event + sent).encode()).hexdigest()[:16]}"  # noqa: S324

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
        """Set alert geometry with validation for complexity and validity.
        
        Args:
            alert: CAPAlert object to update
            geometry_data: GeoJSON geometry dict or None
        """
        try:
            if not geometry_data or not isinstance(geometry_data, dict):
                alert.geom = None
                self.logger.debug(f"No geometry for alert {getattr(alert, 'identifier', '?')}")
                return
                
            # Check polygon complexity before storing
            coords = geometry_data.get('coordinates', [])
            if not coords:
                self.logger.debug(f"Empty coordinates in geometry for alert {getattr(alert, 'identifier', '?')}")
                alert.geom = None
                return
                
            total_vertices = self._count_vertices(coords)

            # Warn and skip geometries that are excessively complex
            if total_vertices > 10000:
                self.logger.warning(
                    f"Alert {getattr(alert, 'identifier', '?')} has {total_vertices:,} vertices "
                    f"(exceeds 10,000 limit). Geometry will not be stored to prevent database "
                    f"performance degradation. Consider simplifying the geometry."
                )
                alert.geom = None
                return

            if total_vertices > 5000:
                self.logger.info(
                    f"Alert {getattr(alert, 'identifier', '?')} has {total_vertices:,} vertices "
                    f"(high complexity - may impact performance)"
                )

            # Convert to GeoJSON string for PostGIS
            try:
                geom_json = json_dumps(geometry_data)
            except (TypeError, ValueError) as json_err:
                self.logger.error(
                    f"Failed to serialize geometry to JSON for alert {getattr(alert, 'identifier', '?')}: {json_err}"
                )
                alert.geom = None
                return

            # Use PostGIS to create geometry from GeoJSON
            try:
                result = self.db_session.execute(
                    text("SELECT ST_SetSRID(ST_GeomFromGeoJSON(:g), 4326)"),
                    {"g": geom_json}
                ).scalar()
            except Exception as geom_err:
                self.logger.error(
                    f"PostGIS failed to parse GeoJSON for alert {getattr(alert, 'identifier', '?')}: {geom_err}. "
                    f"Geometry type: {geometry_data.get('type')}, vertices: {total_vertices}"
                )
                alert.geom = None
                return

            # Validate geometry and attempt repair if invalid
            try:
                is_valid = self.db_session.execute(
                    text("SELECT ST_IsValid(:geom)"),
                    {"geom": result}
                ).scalar()
            except Exception as valid_err:
                self.logger.warning(
                    f"Geometry validation check failed for alert {getattr(alert, 'identifier', '?')}: {valid_err}"
                )
                # Assume invalid if check fails
                is_valid = False

            if not is_valid:
                self.logger.warning(
                    f"Invalid geometry for alert {getattr(alert, 'identifier', '?')} - "
                    f"attempting automatic repair with ST_MakeValid. "
                    f"This may indicate self-intersecting polygons or other topology issues."
                )
                try:
                    result = self.db_session.execute(
                        text("SELECT ST_MakeValid(:geom)"),
                        {"geom": result}
                    ).scalar()
                    self.logger.info(f"Geometry repaired successfully for alert {getattr(alert, 'identifier', '?')}")
                except Exception as repair_err:
                    self.logger.error(
                        f"ST_MakeValid failed to repair geometry for alert {getattr(alert, 'identifier', '?')}: {repair_err}. "
                        f"Geometry will not be stored."
                    )
                    alert.geom = None
                    return

            alert.geom = result
            self.logger.debug(f"Geometry set for alert {getattr(alert, 'identifier', '?')} ({total_vertices} vertices)")
            
        except Exception as e:
            self.logger.error(
                f"Unexpected error setting geometry for alert {getattr(alert,'identifier','?')}: {type(e).__name__}: {e}. "
                f"Geometry will not be stored."
            )
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

    def _try_build_geometry_from_same_codes(self, alert: CAPAlert) -> bool:
        """Attempt to build alert geometry from SAME geocodes via the county boundary table.

        Fallback for alerts that carry no polygon geometry in the feed (e.g.
        county-wide watches, advisories, and statements that use SAME codes
        instead of a specific area polygon).  This mirrors the Priority 3 logic
        in ``webapp/admin/coverage.py::try_build_geometry_from_same_codes`` but
        uses the poller's own ``db_session`` instead of Flask-SQLAlchemy.

        Returns True if the alert now has geometry, False otherwise.
        """
        try:
            if alert.geom:
                return True

            # Confirm the county boundary table exists and has rows.
            try:
                table_exists = self.db_session.execute(
                    text(
                        "SELECT EXISTS ("
                        "  SELECT 1 FROM information_schema.tables"
                        "  WHERE table_name = 'us_county_boundaries'"
                        ")"
                    )
                ).scalar()
                if not table_exists:
                    return False
                row_count = self.db_session.execute(
                    text("SELECT COUNT(*) FROM us_county_boundaries")
                ).scalar()
                if not row_count:
                    return False
            except Exception:
                return False

            raw_json = alert.raw_json if isinstance(alert.raw_json, dict) else {}

            # Guard: if the alert has a polygon in raw_json but an earlier parse
            # attempt failed, do not substitute a coarse county union — it would
            # inflate coverage for a localized event (e.g. a partial-county warning).
            raw_geom = raw_json.get('geometry')
            if raw_geom and isinstance(raw_geom, dict) and raw_geom.get('coordinates'):
                return False

            same_codes = (
                raw_json.get('properties', {})
                .get('geocode', {})
                .get('SAME', [])
            )
            if not same_codes:
                return False

            geoids: set = set()
            statewide_state_fps: set = set()

            for code in same_codes:
                if not isinstance(code, str) or len(code) != 6:
                    continue
                if code.endswith('000'):
                    # Statewide: SAME 039000 → state FIPS "39"
                    statewide_state_fps.add(code[1:3])
                    continue
                # SAME codes are always 6 chars: 0SSCCC.  Drop the single leading
                # zero to obtain the 5-digit Census GEOID (SSCCC).  Using lstrip('0')
                # would over-strip codes for states 01-09.
                geoid = code[1:]
                geoids.add(geoid)

            if not geoids and not statewide_state_fps:
                return False

            conditions = []
            params: Dict[str, Any] = {}

            if geoids:
                conditions.append("geoid = ANY(:geoids)")
                params["geoids"] = list(geoids)
            if statewide_state_fps:
                conditions.append("statefp = ANY(:state_fps)")
                params["state_fps"] = list(statewide_state_fps)

            where_clause = " OR ".join(conditions)

            # Compute the county union and match count in a single query.
            row = self.db_session.execute(
                text(
                    f"SELECT ST_SetSRID(ST_Multi(ST_Union(geom)), 4326) AS union_geom,"
                    f" COUNT(*) AS county_count"
                    f" FROM us_county_boundaries"
                    f" WHERE ({where_clause}) AND geom IS NOT NULL"
                ),
                params,
            ).one()

            if not row.county_count or row.union_geom is None:
                return False

            alert.geom = row.union_geom
            self.db_session.commit()

            self.logger.info(
                "Built geometry from %d SAME codes (%d counties) for alert %s",
                len(same_codes),
                row.county_count,
                getattr(alert, 'identifier', '?'),
            )
            return True

        except Exception as exc:
            self.logger.warning(
                "SAME geometry build failed for alert %s: %s",
                getattr(alert, 'identifier', '?'),
                exc,
            )
            try:
                self.db_session.rollback()
            except Exception:
                pass
            return False

    def process_intersections(self, alert: CAPAlert):
        """Calculate and store intersections with proper transaction handling.
        
        Optimized to use a single bulk query instead of N+1 queries (one per boundary).
        This dramatically reduces CPU usage when processing alerts with many boundaries.
        
        Args:
            alert: CAPAlert object with geometry to intersect
            
        Raises:
            Exception: Re-raises exceptions after rollback to signal failure
        """
        try:
            if not alert.geom:
                self.logger.debug(f"Alert {getattr(alert, 'identifier', '?')} has no geometry, skipping intersections")
                return
            
            if not alert.id:
                self.logger.error(f"Alert {getattr(alert, 'identifier', '?')} has no ID, cannot calculate intersections")
                return

            # Validate geometry before processing intersections
            try:
                is_valid = self.db_session.execute(
                    text("SELECT ST_IsValid(:geom)"),
                    {"geom": alert.geom}
                ).scalar()
                
                if not is_valid:
                    self.logger.warning(
                        f"Alert {getattr(alert, 'identifier', '?')} has invalid geometry, "
                        f"cannot calculate intersections. Run ST_MakeValid to repair."
                    )
                    return
            except Exception as validation_err:
                self.logger.error(
                    f"Geometry validation failed for alert {getattr(alert, 'identifier', '?')}: {validation_err}"
                )
                return

            # Delete old intersections
            try:
                deleted_count = self.db_session.query(Intersection).filter_by(cap_alert_id=alert.id).delete()
                if deleted_count > 0:
                    self.logger.debug(f"Deleted {deleted_count} old intersections for alert {alert.id}")
            except Exception as delete_err:
                self.logger.error(f"Failed to delete old intersections for alert {alert.id}: {delete_err}")
                raise

            # OPTIMIZED: Calculate ALL intersections in a single query instead of N queries
            # This uses a SQL subquery to compute ST_Intersects and ST_Area for all boundaries at once
            # OLD: N+1 queries (1 to fetch boundaries + N queries for intersections)
            # NEW: 1 query that calculates all intersections
            # 
            # IMPORTANT: Use ST_Area(geography(...)) to get area in square meters, not degrees²
            # This provides accurate area measurements for intersection calculations
            intersection_query = text("""
                SELECT 
                    b.id as boundary_id,
                    ST_Area(
                        ST_Transform(
                            ST_Intersection(:alert_geom, b.geom),
                            4326
                        )::geography
                    ) as intersection_area
                FROM boundaries b
                WHERE b.geom IS NOT NULL
                  AND ST_IsValid(b.geom)
                  AND ST_Intersects(:alert_geom, b.geom)
            """)
            
            try:
                results = self.db_session.execute(
                    intersection_query,
                    {'alert_geom': alert.geom}
                ).fetchall()
            except Exception as query_err:
                self.logger.error(
                    f"Intersection query failed for alert {getattr(alert, 'identifier', '?')}: {query_err}. "
                    f"This may indicate corrupted geometry or database issues."
                )
                raise

            # Build list of new intersections from bulk query results
            new_intersections = []
            with_area = 0
            errors = 0

            for row in results:
                try:
                    boundary_id = row.boundary_id
                    # Area is now in square meters (from geography cast)
                    ia = float(row.intersection_area or 0)
                    
                    if ia < 0:
                        self.logger.warning(
                            f"Negative intersection area ({ia}) for alert {alert.id} boundary {boundary_id}, "
                            f"setting to 0"
                        )
                        ia = 0
                    
                    new_intersections.append(Intersection(
                        cap_alert_id=alert.id,
                        boundary_id=boundary_id,
                        intersection_area=ia,
                        created_at=utc_now()
                    ))
                    if ia > 0:
                        with_area += 1
                except (ValueError, TypeError) as convert_err:
                    errors += 1
                    self.logger.warning(
                        f"Data conversion error for intersection alert={alert.id} boundary={boundary_id}: {convert_err}"
                    )
                except Exception as row_err:
                    errors += 1
                    self.logger.error(
                        f"Unexpected error processing intersection row alert={alert.id} boundary={boundary_id}: {row_err}"
                    )

            if errors > 0:
                self.logger.warning(f"Encountered {errors} errors processing intersection results")

            # Bulk insert all intersections atomically
            if new_intersections:
                try:
                    self.db_session.bulk_save_objects(new_intersections)
                except Exception as bulk_err:
                    self.logger.error(
                        f"Bulk insert failed for {len(new_intersections)} intersections: {bulk_err}"
                    )
                    raise

            try:
                self.db_session.commit()
            except Exception as commit_err:
                self.logger.error(f"Failed to commit intersections for alert {alert.id}: {commit_err}")
                raise

            if new_intersections:
                self.logger.info(
                    f"Intersections for alert {getattr(alert, 'identifier', '?')}: {len(new_intersections)} total "
                    f"({with_area} with area > 0, {errors} errors)"
                )
            else:
                self.logger.debug(f"No intersections found for alert {getattr(alert, 'identifier', '?')}")
                
        except Exception as e:
            self.logger.error(
                f"Error processing intersections for alert {getattr(alert, 'id', '?')} "
                f"({getattr(alert, 'identifier', '?')}): {type(e).__name__}: {e}"
            )
            try:
                self.db_session.rollback()
            except Exception as rollback_err:
                self.logger.error(f"Rollback failed: {rollback_err}")
            raise  # Re-raise so caller knows intersection calculation failed

    def save_cap_alert(self, alert_data: Dict) -> Tuple[bool, Optional[CAPAlert], Optional[Dict[str, Any]]]:
        from app_core.logging_context import bind_alert

        # Bind the CAP identifier as the correlation ID for every log line
        # produced while this alert moves through dedup, DB write, geometry
        # processing, Redis publish, auto-forward, and IntegrityError retries.
        with bind_alert(alert_data.get('identifier')):
            try:
                payload = dict(alert_data)
                geometry_data = payload.pop('_geometry_data', None)
                existing = self.db_session.query(CAPAlert).filter_by(
                    identifier=payload['identifier']
                ).first()

                if existing:
                    return self._update_existing_alert(existing, payload, geometry_data)

                return self._insert_new_alert(payload, geometry_data, alert_data)

            except IntegrityError as e:
                # Race condition: another process inserted the same alert between our
                # SELECT and INSERT. Rollback and retry as an UPDATE.
                self.logger.warning(
                    f"IntegrityError saving alert {payload.get('identifier', 'unknown')}, "
                    f"retrying as update: {e}"
                )
                self.db_session.rollback()

                # Re-fetch the existing alert and update it
                try:
                    existing = self.db_session.query(CAPAlert).filter_by(
                        identifier=payload['identifier']
                    ).first()
                    if existing:
                        return self._update_existing_alert(existing, payload, geometry_data)
                    else:
                        # Alert was deleted between our attempts - this is very rare
                        self.logger.error(
                            f"Alert {payload.get('identifier')} not found after IntegrityError"
                        )
                        return False, None, None
                except Exception as retry_err:
                    self.logger.error(f"Failed to update alert after IntegrityError: {retry_err}")
                    self.db_session.rollback()
                    return False, None, None

            except SQLAlchemyError as e:
                self.logger.error(f"Database error saving alert: {e}")
                self.db_session.rollback()
                return False, None, None
            except Exception as e:
                self.logger.error(f"Error saving CAP alert: {e}")
                self.db_session.rollback()
                return False, None, None

    def _update_existing_alert(
        self,
        existing: CAPAlert,
        payload: Dict,
        geometry_data: Optional[Dict]
    ) -> Tuple[bool, Optional[CAPAlert], None]:
        """Update an existing alert with new data."""
        for k, v in payload.items():
            # Update raw_json to maintain audit trail
            if hasattr(existing, k):
                setattr(existing, k, v)
        old_geom = existing.geom
        if geometry_data is not None:
            # The feed provided polygon geometry for this update — apply it.
            # This correctly replaces stale SAME-derived geometry when the real
            # polygon becomes available, or updates the geometry when NWS revises
            # the warning polygon.
            self._set_alert_geometry(existing, geometry_data)
        # If geometry_data is None the feed has no polygon for this alert (e.g.
        # a county-wide watch or advisory that only carries SAME codes).  Do NOT
        # clear existing.geom — it may have been built from SAME codes by
        # try_build_geometry_from_same_codes and we must preserve that work
        # across poll cycles.
        existing.updated_at = utc_now()

        # Backfill VTEC identity if not yet populated (e.g. alert was ingested
        # before this feature was deployed, or an update carries fresh VTEC data)
        if not existing.vtec_office:
            try:
                vtec_fields = extract_vtec_identity(payload.get('raw_json', {}))
                if vtec_fields:
                    for field, value in vtec_fields.items():
                        setattr(existing, field, value)
            except Exception as exc:
                self.logger.debug("VTEC backfill failed for %s: %s",
                                  existing.identifier, exc)

        # A cancellation can also arrive as an update to the same CAP
        # identifier rather than a brand-new product; recognise it here so the
        # alert flips to Cancelled instead of silently keeping its 'Actual'
        # status until the original expiry lapses.
        self._apply_cancellation_status(existing)

        self.db_session.commit()

        # For alerts with no polygon geometry, try building from SAME codes so
        # that intersection calculation can proceed automatically.
        if not existing.geom:
            self._try_build_geometry_from_same_codes(existing)

        # Use PostGIS ST_Equals for reliable geometry comparison
        geom_changed = self._has_geometry_changed(old_geom, existing.geom)

        if geom_changed or self._needs_intersection_calculation(existing):
            try:
                self.process_intersections(existing)
            except Exception as exc:
                self.logger.error(
                    "Intersection recalculation failed for %s (non-fatal): %s",
                    existing.identifier, exc,
                )
        
        # Publish LED update event via Redis
        if not self.is_alert_expired(existing):
            self._publish_alert_event('alerts:led:update', {
                'alert_id': existing.id,
                'identifier': existing.identifier,
                'event': existing.event,
                'severity': existing.severity
            })
        
        self.logger.info(f"Updated alert: {existing.event}")
        return False, existing, None

    def _insert_new_alert(
        self,
        payload: Dict,
        geometry_data: Optional[Dict],
        alert_data: Dict
    ) -> Tuple[bool, Optional[CAPAlert], Optional[Dict[str, Any]]]:
        """Insert a new alert into the database.
        
        Args:
            payload: Parsed alert data for database storage (without raw_json structure)
            geometry_data: GeoJSON geometry data for PostGIS storage
            alert_data: Original alert data with raw_json containing BLOCKCHANNEL, etc.
        """
        new_alert = CAPAlert(**payload)
        new_alert.created_at = utc_now()
        new_alert.updated_at = utc_now()
        # Initialize EAS forwarding fields
        new_alert.eas_forwarded = False
        new_alert.eas_forwarding_reason = None
        new_alert.eas_audio_url = None
        self._set_alert_geometry(new_alert, geometry_data)

        # IPAWS enrichment: extract certificate info, verify signature, save audio
        raw_json = alert_data.get('raw_json', {})
        raw_xml = raw_json.get('raw_xml', '') if isinstance(raw_json, dict) else ''
        if raw_xml:
            try:
                cert_info = extract_certificate_info(raw_xml)
                if cert_info:
                    new_alert.certificate_info = cert_info
                    # Persist signature verification result to DB columns
                    if cert_info.get('signature_verified') is not None:
                        new_alert.signature_verified = cert_info['signature_verified']
                    if cert_info.get('signature_status'):
                        new_alert.signature_status = cert_info['signature_status']
                    self.logger.info(
                        "Extracted certificate info for %s: issuer=%s, cert_valid=%s, sig=%s",
                        payload.get('identifier', '?'),
                        cert_info.get('issuer', 'unknown'),
                        cert_info.get('is_cert_valid', '?'),
                        cert_info.get('signature_status', '?'),
                    )
            except Exception as exc:
                self.logger.warning("Certificate extraction failed for %s: %s",
                                    payload.get('identifier', '?'), exc)

        if isinstance(raw_json, dict):
            try:
                eas_output = os.getenv('EAS_OUTPUT_DIR') or os.path.join(
                    os.getenv('EAS_STATIC_DIR', os.path.join(os.getcwd(), 'static')),
                    'eas_messages',
                )
                audio_filename = save_ipaws_audio(
                    raw_json, payload.get('identifier', 'unknown'), eas_output,
                )
                if audio_filename:
                    new_alert.ipaws_audio_url = audio_filename
            except Exception as exc:
                self.logger.warning("IPAWS audio save failed for %s: %s",
                                    payload.get('identifier', '?'), exc)

        # Extract VTEC identity fields so related updates share a queryable event key
        try:
            vtec_fields = extract_vtec_identity(alert_data.get('raw_json', {}))
            if vtec_fields:
                for field, value in vtec_fields.items():
                    setattr(new_alert, field, value)
        except Exception as exc:
            self.logger.debug("VTEC identity extraction failed for %s: %s",
                              payload.get('identifier', '?'), exc)

        # A cancellation product (msgType=Cancel / VTEC CAN) is itself a notice
        # that the event is over — label it Cancelled so it is reported as such
        # and stays out of the active-alerts view.
        self._apply_cancellation_status(new_alert)

        # First commit: Save alert to database to get the ID needed for EAS message linking
        self.db_session.add(new_alert)
        self.db_session.commit()

        # Mark prior products in the same VTEC event chain as superseded so the
        # UI can hide stale entries by default.  Only non-NEW actions represent
        # follow-on products (updates, extensions, cancellations, etc.).
        if new_alert.vtec_action and new_alert.vtec_action != 'NEW':
            try:
                self._mark_vtec_chain_superseded(new_alert)
            except Exception as exc:
                self.logger.warning(
                    "Failed to mark prior VTEC chain alerts superseded for %s: %s",
                    new_alert.identifier, exc,
                )

        # Build geometry before the forwarding decision: the notification
        # email's coverage map renders from new_alert.geom at send time, and
        # _try_build_geometry_from_same_codes is internally guarded (returns
        # False on any failure) so it cannot block the air chain.
        has_geometry = bool(new_alert.geom) or self._try_build_geometry_from_same_codes(new_alert)

        # Publish new alert event to Redis for other services
        if not self.is_alert_expired(new_alert):
            # Publish to Redis for real-time UI updates and LED service
            self._publish_alert_event('alerts:new', {
                'alert_id': new_alert.id,
                'identifier': new_alert.identifier,
                'event': new_alert.event,
                'severity': new_alert.severity,
                'urgency': new_alert.urgency,
                'certainty': new_alert.certainty,
                'sent': new_alert.sent,
                'expires': new_alert.expires,
                'raw_json': alert_data.get('raw_json', {})
            })

            # Publish to LED service for display update
            self._publish_alert_event('alerts:led:new', {
                'alert_id': new_alert.id,
                'identifier': new_alert.identifier,
                'event': new_alert.event,
                'severity': new_alert.severity
            })

            # Auto-forward to air chain: generate SAME header with station
            # originator, build audio, activate GPIO, and play broadcast.
            # This is fully automatic with zero operator intervention.
            #
            # Reload the EAS config from the database before each forwarding
            # decision so admin UI changes (broadcast_enabled, originator,
            # forwarded_event_codes, etc.) take effect without a service
            # restart.  Without this refresh, alerts the operator has just
            # de-selected from the auto-forward allowlist would continue to
            # be rebroadcast until the cap-poller process is restarted.
            try:
                self.eas_config = load_eas_config(db_session=self.db_session)
            except Exception as exc:
                self.logger.warning(
                    "Failed to refresh EAS config before forwarding %s; "
                    "using cached config: %s",
                    new_alert.identifier, exc,
                )

            try:
                forward_result = auto_forward_cap_alert(
                    cap_alert=new_alert,
                    alert_data=alert_data,
                    db_session=self.db_session,
                    eas_message_cls=EASMessage,
                    eas_config=self.eas_config,
                    location_settings=self.location_settings,
                    logger_instance=self.logger,
                )
                if forward_result.get('forwarded'):
                    self.logger.info(
                        "Auto-forwarded %s to air chain: %s",
                        new_alert.identifier,
                        forward_result.get('same_header', ''),
                    )
                else:
                    self.logger.info(
                        "Auto-forward skipped for %s: %s",
                        new_alert.identifier,
                        forward_result.get('reason', 'unknown'),
                    )
            except Exception as exc:
                self.logger.error(
                    "Auto-forward failed for %s: %s",
                    new_alert.identifier, exc, exc_info=True,
                )

        # Boundary intersections are analytics for the map/statistics pages.
        # They run AFTER the forwarding decision and behind a guard because
        # process_intersections() re-raises on database errors; when it sat
        # ahead of auto_forward_cap_alert, a single PostGIS failure on a
        # statewide alert aborted the save and the alert never received a
        # forwarding decision (Ohio RMT CAPNET-1-14329-20260610034200,
        # 2026-06-10).
        if has_geometry:
            try:
                self.process_intersections(new_alert)
            except Exception as exc:
                self.logger.error(
                    "Intersection calculation failed for %s (non-fatal; alert "
                    "is saved and the forwarding decision was already made): %s",
                    new_alert.identifier, exc,
                )

        self.logger.info(f"Saved new alert: {new_alert.identifier} - {new_alert.event}")
        return True, new_alert, None

    def _apply_cancellation_status(self, alert: CAPAlert) -> bool:
        """Mark *alert* as Cancelled when it is an explicit cancellation product.

        Recognises both the CAP ``msgType=Cancel`` envelope and the VTEC ``CAN``
        action code.  Sets ``status='Cancelled'`` and stamps ``cancelled_at``
        while leaving ``expires`` untouched, so the alert detail view can show
        the event was lifted early.  Returns ``True`` when the alert is (now) a
        cancellation.

        This handles the case where a cancellation arrives as an *update* to the
        same CAP identifier (the prior-product path is covered by
        ``_mark_vtec_chain_superseded``).  Air behaviour is unchanged: the
        auto-forward guard already suppresses terminal VTEC actions and any
        non-'Actual' status.
        """
        if not is_cancellation(
            getattr(alert, 'message_type', None),
            getattr(alert, 'vtec_action', None),
        ):
            return False
        if alert.status != 'Cancelled':
            alert.status = 'Cancelled'
        if getattr(alert, 'cancelled_at', None) is None:
            alert.cancelled_at = utc_now()
        return True

    def _mark_vtec_chain_superseded(self, new_alert: CAPAlert) -> int:
        """Mark all un-superseded prior alerts in the same VTEC event chain as
        superseded by *new_alert*.

        The VTEC event key is (office, phenomenon, significance, etn, year).
        Only rows that are not already superseded are touched so the chain
        remains a proper linked list rather than a star.

        Returns the number of rows updated.
        """
        if not all([
            new_alert.vtec_office,
            new_alert.vtec_phenomenon,
            new_alert.vtec_significance,
            new_alert.vtec_etn,
            new_alert.vtec_year,
        ]):
            return 0

        # Build the field update dict.  For terminal VTEC actions the event is
        # definitively over: 'EXP' collapses the prior alerts' expiry to now,
        # while 'CAN' marks them Cancelled (preserving the original expiry so
        # the UI can show the event was lifted early).  Either way they drop out
        # of every active-alerts view.
        updates = terminal_chain_updates(new_alert.vtec_action, new_alert.id, utc_now())

        updated = (
            self.db_session.query(CAPAlert)
            .filter(
                CAPAlert.vtec_office       == new_alert.vtec_office,
                CAPAlert.vtec_phenomenon   == new_alert.vtec_phenomenon,
                CAPAlert.vtec_significance == new_alert.vtec_significance,
                CAPAlert.vtec_etn          == new_alert.vtec_etn,
                CAPAlert.vtec_year         == new_alert.vtec_year,
                CAPAlert.id                != new_alert.id,
                CAPAlert.superseded_by_id.is_(None),
            )
            .update(updates, synchronize_session='fetch')
        )
        if updated:
            self.db_session.commit()
            if new_alert.vtec_action == 'CAN':
                terminal_note = ', cancelled'
            elif new_alert.vtec_action in VTEC_TERMINAL_ACTIONS:
                terminal_note = ', expired immediately'
            else:
                terminal_note = ''
            self.logger.info(
                "Marked %d prior VTEC chain alert(s) superseded by %s (action=%s%s)",
                updated, new_alert.identifier, new_alert.vtec_action, terminal_note,
            )
        return updated

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

    # Catch-up window for retry_unevaluated_forwards().  Alerts whose insert
    # pipeline died between the database save and the forwarding decision are
    # retried for up to this long after ingest; auto_forward_cap_alert's own
    # gates (expiry, status, allowlist, dedup) still decide whether anything
    # actually airs.
    FORWARD_RETRY_WINDOW_MINUTES = 60

    # Terminal reason stamped on alerts that expired while never evaluated.
    # The "Never evaluated" prefix is matched by the alert trail
    # (app_core/alert_trail.py::_forwarding_event) and the health endpoint
    # (webapp/routes_monitoring.py) to render/count a missed broadcast —
    # keep all three in sync.
    MISSED_FORWARDING_REASON = (
        "Never evaluated — ingest pipeline fault; alert expired before the "
        "catch-up sweep could retry"
    )

    def retry_unevaluated_forwards(self) -> int:
        """Re-run the auto-forward decision for alerts that never received one.

        ``eas_forwarding_reason`` is written by every exit path of
        ``auto_forward_cap_alert`` (at minimum an empty string), so a NULL
        reason combined with ``eas_forwarded=False`` means the insert pipeline
        was interrupted between the database save and the forwarding decision
        (PostGIS failure, OOM kill, service restart).  Forwarding normally
        happens only on first insert, so without this sweep such an alert
        silently misses its only chance to air.

        Returns the number of alerts re-evaluated.
        """
        now = utc_now()
        cutoff = now - timedelta(minutes=self.FORWARD_RETRY_WINDOW_MINUTES)

        # Terminal accounting first: the pipeline died AND the alert expired
        # before any retry could happen — the broadcast window is gone.  Stamp
        # a terminal reason (one-shot: the NULL reason is what marks a row as
        # pending) and raise a system-log ERROR so the miss is investigated
        # rather than discovered on a trail page later.  The
        # created_at < expires filter excludes alerts that were *already*
        # expired when ingested (historical imports), for which skipping the
        # forwarding decision is correct behaviour, not a fault.
        try:
            missed = (
                self.db_session.query(CAPAlert)
                .filter(CAPAlert.eas_forwarded.is_(False))
                .filter(CAPAlert.eas_forwarding_reason.is_(None))
                .filter(CAPAlert.expires.isnot(None))
                .filter(CAPAlert.expires <= now)
                .filter(CAPAlert.expires > now - timedelta(hours=24))
                .filter(CAPAlert.created_at < CAPAlert.expires)
                .all()
            )
        except Exception as exc:
            self.logger.warning("Missed-forwarding query failed: %s", exc)
            try:
                self.db_session.rollback()
            except Exception:
                pass
            missed = []
        if missed:
            try:
                for alert in missed:
                    alert.eas_forwarding_reason = self.MISSED_FORWARDING_REASON[:255]
                    self.db_session.add(alert)
                self.db_session.commit()
            except Exception as exc:
                self.logger.error("Failed to stamp missed-forwarding alerts: %s", exc)
                try:
                    self.db_session.rollback()
                except Exception:
                    pass
            self.log_system_event(
                'ERROR',
                f"MISSED BROADCAST: {len(missed)} alert(s) expired without "
                f"ever being evaluated for forwarding — the ingest pipeline "
                f"faulted and the catch-up sweep did not run in time",
                {'identifiers': [a.identifier for a in missed]},
            )

        try:
            pending = (
                self.db_session.query(CAPAlert)
                .filter(CAPAlert.eas_forwarded.is_(False))
                .filter(CAPAlert.eas_forwarding_reason.is_(None))
                .filter(CAPAlert.created_at >= cutoff)
                .filter(CAPAlert.expires.isnot(None))
                .filter(CAPAlert.expires > now)
                .all()
            )
        except Exception as exc:
            self.logger.warning("Forwarding catch-up query failed: %s", exc)
            try:
                self.db_session.rollback()
            except Exception:
                pass
            return 0

        if not pending:
            return 0

        # A never-evaluated alert means the ingest pipeline faulted (PostGIS
        # error, OOM kill, service restart) — the rescue below restores the
        # broadcast, but the fault itself must be loud so an operator
        # investigates the cause instead of discovering it on a trail page
        # weeks later.
        self.log_system_event(
            'ERROR',
            f"Forwarding catch-up: {len(pending)} alert(s) were saved but "
            f"never evaluated for forwarding — ingest pipeline was "
            f"interrupted; re-running the auto-forward decision now",
            {'identifiers': [a.identifier for a in pending]},
        )

        # Same config refresh the insert path does, so allowlist/enabled
        # changes made since the last cycle are honoured.
        try:
            self.eas_config = load_eas_config(db_session=self.db_session)
        except Exception as exc:
            self.logger.warning(
                "Failed to refresh EAS config for forwarding catch-up; "
                "using cached config: %s", exc,
            )

        evaluated = 0
        for alert in pending:
            self.logger.warning(
                "Alert %s was saved but never evaluated for forwarding "
                "(pipeline interrupted at ingest) — re-running the "
                "auto-forward decision",
                alert.identifier,
            )
            alert_data = {
                'identifier': alert.identifier,
                'raw_json': alert.raw_json if isinstance(alert.raw_json, dict) else {},
            }
            try:
                forward_result = auto_forward_cap_alert(
                    cap_alert=alert,
                    alert_data=alert_data,
                    db_session=self.db_session,
                    eas_message_cls=EASMessage,
                    eas_config=self.eas_config,
                    location_settings=self.location_settings,
                    logger_instance=self.logger,
                )
                evaluated += 1
                if forward_result.get('forwarded'):
                    self.logger.info(
                        "Catch-up forwarded %s to air chain: %s",
                        alert.identifier,
                        forward_result.get('same_header', ''),
                    )
                else:
                    self.logger.info(
                        "Catch-up evaluated %s without broadcast: %s",
                        alert.identifier,
                        forward_result.get('reason', 'unknown'),
                    )
            except Exception as exc:
                self.logger.error(
                    "Forwarding catch-up failed for %s: %s",
                    alert.identifier, exc, exc_info=True,
                )
                try:
                    self.db_session.rollback()
                except Exception:
                    pass
        return evaluated

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
        """Persist poll debug records to database.
        
        This is a CPU and database intensive operation that creates one row per alert
        processed (including rejected alerts) with full geometry and properties.
        
        By default, this is DISABLED to reduce CPU usage. Enable by setting:
            CAP_POLLER_DEBUG_RECORDS=1
        
        Only enable for troubleshooting or when actively debugging alert filtering issues.
        """
        if not self._debug_records_enabled:
            # Skip debug record persistence to reduce CPU and database overhead
            return
            
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
        """Clean old poll history records. Only runs periodically to avoid CPU overhead."""
        # Check if cleanup is due (runs once per day by default)
        # Early return to avoid ANY database queries when cleanup is not due
        now = utc_now()
        if self._last_poll_history_cleanup_time is not None:
            time_since_cleanup = (now - self._last_poll_history_cleanup_time).total_seconds()
            if time_since_cleanup < self._cleanup_interval_seconds:
                # Skip cleanup - not enough time has passed
                # Don't perform any database queries to minimize CPU usage
                return
        
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
                deleted = self.db_session.query(PollHistory).filter(
                    PollHistory.timestamp < cutoff, ~PollHistory.id.in_(subq)
                ).delete(synchronize_session=False)
                self.db_session.commit()
                self.logger.info("Cleaned old poll history (removed %d records, kept 100 most recent)", deleted)
            else:
                self.logger.debug("Skipping poll history cleanup - only %d old records (threshold: 100)", old_count)
            
            # Update last cleanup time on success
            self._last_poll_history_cleanup_time = now
        except Exception as e:
            self.logger.error(f"cleanup_old_poll_history error: {e}")
            try:
                self.db_session.rollback()
            except Exception as rollback_exc:
                self.logger.debug("Rollback failed during poll history cleanup: %s", rollback_exc)

    def cleanup_old_debug_records(self):
        """Clean old debug records. Only runs periodically to avoid CPU overhead."""
        # Check if cleanup is due (runs once per day by default)
        # Early return to avoid ANY database queries when cleanup is not due
        now = utc_now()
        if self._last_debug_records_cleanup_time is not None:
            time_since_cleanup = (now - self._last_debug_records_cleanup_time).total_seconds()
            if time_since_cleanup < self._cleanup_interval_seconds:
                # Skip cleanup - not enough time has passed
                # Don't perform any database queries to minimize CPU usage
                return
        
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
                deleted = self.db_session.query(PollDebugRecord).filter(
                    PollDebugRecord.created_at < cutoff,
                    ~PollDebugRecord.id.in_(subq),
                ).delete(synchronize_session=False)
                self.db_session.commit()
                self.logger.info("Cleaned old debug records (removed %d records, kept 500 most recent)", deleted)
            else:
                self.logger.debug("Skipping debug records cleanup - only %d old records (threshold: 500)", old_count)
            
            # Update last cleanup time on success
            self._last_debug_records_cleanup_time = now
        except Exception as exc:
            self.logger.error(f"cleanup_old_debug_records error: {exc}")
            try:
                self.db_session.rollback()
            except Exception:
                pass

    def log_poll_history(self, stats, per_source_stats: Dict = None):
        try:
            try:
                self.db_session.execute(text("SELECT 1 FROM poll_history LIMIT 1"))
            except Exception as db_exc:
                self.logger.error(
                    "Failed to write poll history — DB session unusable: %s. "
                    "Poll results will NOT be recorded until the session recovers. "
                    "Check for earlier errors (e.g. a failed schema query) that "
                    "left the transaction in an aborted state.",
                    db_exc,
                )
                try:
                    self.db_session.rollback()
                except Exception:
                    pass
                return

            # Shared details fields (config info relevant to every source)
            common_details = {
                'configured_zone_codes': stats.get('configured_zone_codes', []),
                'configured_same_codes': stats.get('configured_same_codes', []),
                'configured_storage_zones': stats.get('configured_storage_zones', []),
                'duplicates_filtered': stats.get('duplicates_filtered', 0),
                'poll_time_utc': stats.get('poll_time_utc'),
                'poll_time_local': stats.get('poll_time_local'),
                'timezone': stats.get('timezone'),
            }

            if per_source_stats:
                # Write one PollHistory record per source type (NOAA, IPAWS, CUSTOM …)
                endpoints_by_type = self.last_endpoints_by_type or {}
                for src_type, src_s in per_source_stats.items():
                    src_details = dict(common_details)
                    src_details['endpoints_polled'] = [
                        {'type': src_type, 'url': u}
                        for u in endpoints_by_type.get(src_type, [])
                    ]
                    src_details['alerts_filtered'] = src_s.get('alerts_filtered', 0)
                    src_details['alerts_accepted'] = src_s.get('alerts_accepted', 0)

                    # data_source uses the endpoint type label directly; 'NOAA', 'IPAWS',
                    # and 'CUSTOM' are preserved as-is (normalize_alert_source maps 'CUSTOM'
                    # to 'UNKNOWN' which is not useful here).
                    data_source = src_type

                    rec = PollHistory(
                        timestamp=utc_now(),
                        alerts_fetched=src_s.get('alerts_fetched', 0),
                        alerts_new=src_s.get('alerts_new', 0),
                        alerts_updated=src_s.get('alerts_updated', 0),
                        execution_time_ms=stats.get('execution_time_ms', 0),
                        status=src_s.get('status', stats.get('status', 'UNKNOWN')),
                        error_message=src_s.get('error_message'),
                        data_source=data_source,
                        details=src_details,
                    )
                    self.db_session.add(rec)
                self.db_session.commit()
            else:
                # Fallback: single combined record (backward-compatible)
                poll_details = dict(common_details)
                poll_details['endpoints_polled'] = stats.get('endpoints_polled', [])
                poll_details['alerts_filtered'] = stats.get('alerts_filtered', 0)
                poll_details['alerts_accepted'] = stats.get('alerts_accepted', 0)
                rec = PollHistory(
                    timestamp=utc_now(),
                    alerts_fetched=stats.get('alerts_fetched', 0),
                    alerts_new=stats.get('alerts_new', 0),
                    alerts_updated=stats.get('alerts_updated', 0),
                    execution_time_ms=stats.get('execution_time_ms', 0),
                    status=stats.get('status', 'UNKNOWN'),
                    error_message=stats.get('error_message'),
                    data_source=summarise_sources(stats.get('sources', [])),
                    details=poll_details,
                )
                self.db_session.add(rec)
                self.db_session.commit()
        except Exception as e:
            self.logger.error(f"log_poll_history error: {e}")
            try:
                self.db_session.rollback()
            except Exception as rollback_err:
                self.logger.warning(f"log_poll_history rollback failed: {rollback_err}")

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
            try:
                self.db_session.rollback()
            except Exception as rollback_err:
                self.logger.warning(f"log_system_event rollback failed: {rollback_err}")

    # ---------- Main poll ----------
    def poll_and_process(self) -> Dict:
        start = time.time()
        poll_start_utc = utc_now()
        poll_start_local = local_now()
        poll_run_id = uuid.uuid4().hex

        # Reload location settings to pick up any changes from admin UI
        self._reload_location_settings()

        # Build endpoint info for logging
        endpoints_info = []
        for ep in self.cap_endpoints:
            if 'tdl.apps.fema.gov' in ep:
                ep_type = "IPAWS"
            elif 'apps.fema.gov' in ep:
                ep_type = "IPAWS"
            elif 'weather.gov' in ep:
                ep_type = "NOAA"
            else:
                ep_type = "CUSTOM"
            endpoints_info.append({'type': ep_type, 'url': ep})

        stats = {
            'alerts_fetched': 0, 'alerts_new': 0, 'alerts_updated': 0,
            'alerts_filtered': 0, 'alerts_accepted': 0, 'intersections_calculated': 0,
            'execution_time_ms': 0, 'status': 'SUCCESS', 'error_message': None,
            'zone': f"{'/'.join(self.location_settings['zone_codes'])} ({self.location_name}) - STRICT FILTERING",
            'poll_time_utc': poll_start_utc.isoformat(),
            'poll_time_local': poll_start_local.isoformat(),
            'timezone': self.location_settings['timezone'],
            'sources': [], 'duplicates_filtered': 0,
            'poll_run_id': poll_run_id,
            'fetched_alerts': [],  # List of alerts that were fetched (for visibility)
            # Endpoint and config info for frontend visibility
            'endpoints_polled': endpoints_info,
            'configured_zone_codes': sorted(self.zone_codes),
            'configured_same_codes': sorted(self.same_codes),
            'configured_storage_zones': sorted(self.storage_zone_codes),
        }

        # Per-source stats — one entry per endpoint type (NOAA, IPAWS, CUSTOM)
        per_source_stats: Dict[str, Dict] = {}

        def _init_source_stats() -> Dict:
            return {
                'alerts_fetched': 0,
                'alerts_new': 0,
                'alerts_updated': 0,
                'alerts_filtered': 0,
                'alerts_accepted': 0,
                'status': 'SUCCESS',
                'error_message': None,
            }

        debug_records: List[Dict[str, Any]] = []

        try:
            # Log poller mode and endpoints
            endpoint_summary = f" ({len(self.cap_endpoints)} endpoint{'s' if len(self.cap_endpoints) != 1 else ''})"

            self.logger.info(
                f"Starting alert polling cycle [NOAA + IPAWS]{endpoint_summary} for {self.location_name} at {format_local_datetime(poll_start_utc)}"
            )

            # Log ALL endpoints being polled for debugging
            self.logger.info("=" * 70)
            self.logger.info("POLL CYCLE DEBUG INFO")
            self.logger.info("=" * 70)
            self.logger.info(f"Configured zone codes: {sorted(self.zone_codes)}")
            self.logger.info(f"Configured SAME/FIPS codes: {sorted(self.same_codes)}")
            self.logger.info(f"Storage zone codes: {sorted(self.storage_zone_codes)}")
            self.logger.info("-" * 70)
            self.logger.info(f"Polling {len(self.cap_endpoints)} endpoint(s):")
            for idx, endpoint in enumerate(self.cap_endpoints, 1):
                if 'tdl.apps.fema.gov' in endpoint:
                    env_marker = " [STAGING/TDL]"
                elif 'apps.fema.gov' in endpoint:
                    env_marker = " [IPAWS PRODUCTION]"
                elif 'weather.gov' in endpoint:
                    env_marker = " [NOAA Weather]"
                else:
                    env_marker = ""
                self.logger.info(f"  [{idx}] {endpoint}{env_marker}")
            self.logger.info("=" * 70)

            # Read cap_timeout from DB settings if available
            _cap_timeout = 30
            try:
                _ps_timeout = PollerSettings.query.first()
                if _ps_timeout and _ps_timeout.cap_timeout:
                    _cap_timeout = max(5, _ps_timeout.cap_timeout)
            except Exception:
                _cap_timeout = int(os.getenv('CAP_TIMEOUT', '30'))
            alerts_data = self.fetch_cap_alerts(timeout=_cap_timeout)
            stats['alerts_fetched'] = len(alerts_data)
            stats['sources'] = list(self.last_poll_sources)
            # If no sources were detected in alerts (e.g., empty poll), use unified identifier
            if not stats['sources']:
                stats['sources'] = ['NOAA', 'IPAWS']  # Default sources for unified poller
            stats['duplicates_filtered'] = self.last_duplicates_filtered

            # Check for fetch errors and log them to the database
            if self.last_fetch_errors:
                error_summary = "; ".join(self.last_fetch_errors)
                stats['error_message'] = error_summary
                stats['status'] = 'ERROR' if len(alerts_data) == 0 else 'PARTIAL_SUCCESS'
                self.logger.warning(f"Fetch errors occurred: {error_summary}")
                self.log_system_event('ERROR', f"CAP polling encountered errors: {error_summary}", stats)

            # Check poller settings for detailed logging (query once per poll cycle)
            log_fetched_alerts = False
            try:
                poller_settings = PollerSettings.query.first()
                log_fetched_alerts = poller_settings.log_fetched_alerts if poller_settings else False
            except Exception:
                # If PollerSettings table doesn't exist yet or query fails, default to False
                pass

            for alert_data in alerts_data:
                props = alert_data.get('properties', {})
                event = props.get('event', 'Unknown')
                alert_id = props.get('identifier', 'No ID')
                area_desc = props.get('areaDesc', 'Unknown area')
                headline = props.get('headline', '')
                endpoint_type = props.get('_fetch_endpoint_type', 'UNKNOWN')

                # Accumulate per-source stats for this alert
                if endpoint_type not in per_source_stats:
                    per_source_stats[endpoint_type] = _init_source_stats()
                per_source_stats[endpoint_type]['alerts_fetched'] += 1

                self.logger.info(f"Processing alert from [{endpoint_type}]: {event} (ID: {alert_id[:20] if alert_id!='No ID' else 'No ID'}...)")

                # Track this alert in fetched_alerts for visibility (even if filtered)
                alert_summary = {
                    'identifier': alert_id[:50] + '...' if len(alert_id) > 50 else alert_id,
                    'event': event,
                    'area': area_desc[:100] + '...' if len(area_desc) > 100 else area_desc,
                    'headline': headline[:150] + '...' if len(headline) > 150 else headline,
                    'sent': props.get('sent', 'Unknown'),
                    'status': 'pending',  # Will be updated based on processing
                    'reason': None,
                }

                # Log detailed alert information if enabled in database settings (helps debug missing alerts)
                if log_fetched_alerts:
                    sent = props.get('sent', 'Unknown')
                    expires = props.get('expires', 'Unknown')
                    effective = props.get('effective', 'Unknown')
                    urgency = props.get('urgency', 'Unknown')
                    severity = props.get('severity', 'Unknown')
                    certainty = props.get('certainty', 'Unknown')
                    area_desc = props.get('areaDesc', 'Unknown')
                    headline = props.get('headline', '')
                    
                    self.logger.info(f"  ├─ Full ID: {alert_id}")
                    self.logger.info(f"  ├─ Event: {event}")
                    self.logger.info(f"  ├─ Sent: {sent}")
                    self.logger.info(f"  ├─ Effective: {effective}")
                    self.logger.info(f"  ├─ Expires: {expires}")
                    self.logger.info(f"  ├─ Urgency: {urgency} | Severity: {severity} | Certainty: {certainty}")
                    self.logger.info(f"  ├─ Area: {area_desc}")
                    if headline:
                        self.logger.info(f"  └─ Headline: {headline}")
                    else:
                        self.logger.info(f"  └─ (No headline)")

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

                # Only collect debug data if debug records are enabled (expensive)
                if self._debug_records_enabled:
                    debug_entry = self._initialise_debug_entry(alert_data, relevance, poll_run_id, poll_start_utc)
                    debug_records.append(debug_entry)

                if not relevance.get('is_relevant'):
                    # Log detailed info about filtered alert so user can see what was fetched
                    ugc_codes = relevance.get('ugc_codes', [])
                    same_codes = relevance.get('same_codes', [])
                    self.logger.info(f"╔═ FILTERED ALERT (not stored) ═══════════════════════════════")
                    self.logger.info(f"║ Event: {event}")
                    self.logger.info(f"║ ID: {alert_id[:60]}{'...' if len(alert_id) > 60 else ''}")
                    self.logger.info(f"║ Area: {area_desc[:80]}{'...' if len(area_desc) > 80 else ''}")
                    self.logger.info(f"║ Alert UGC codes: {', '.join(ugc_codes[:5]) if ugc_codes else 'None'}")
                    self.logger.info(f"║ Alert SAME codes: {', '.join(same_codes[:5]) if same_codes else 'None'}")
                    self.logger.info(f"║ Reason: Not relevant to {self.county_upper} - no matching location codes")
                    self.logger.info(f"╚═══════════════════════════════════════════════════════════════")
                    stats['alerts_filtered'] += 1
                    per_source_stats[endpoint_type]['alerts_filtered'] += 1
                    # Track filtered alert for visibility
                    alert_summary['status'] = 'filtered'
                    alert_summary['reason'] = f"Not relevant to {self.county_upper} - no matching location codes"
                    alert_summary['ugc_codes'] = ugc_codes[:5] if ugc_codes else []
                    alert_summary['same_codes'] = same_codes[:5] if same_codes else []
                    stats['fetched_alerts'].append(alert_summary)
                    if self._debug_records_enabled and 'debug_entry' in locals():
                        debug_entry.setdefault('notes', []).append('Filtered out by strict location rules')
                    continue

                stats['alerts_accepted'] += 1
                per_source_stats[endpoint_type]['alerts_accepted'] += 1
                parsed = self.parse_cap_alert(alert_data)
                if not parsed:
                    self.logger.warning(f"Failed to parse: {event}")
                    if self._debug_records_enabled and 'debug_entry' in locals():
                        debug_entry['parse_error'] = 'parse_cap_alert returned None'
                        debug_entry.setdefault('notes', []).append('Parsing failed')
                    continue

                if self._debug_records_enabled and 'debug_entry' in locals():
                    debug_entry['parse_success'] = True
                    debug_entry['identifier'] = parsed.get('identifier', '')
                    debug_entry['source'] = parsed.get('source')
                    debug_entry['alert_sent'] = parsed.get('sent')
                    geometry_data = parsed.get('_geometry_data')
                    if geometry_data:
                        debug_entry['geometry_geojson'] = self._safe_json_copy(geometry_data)
                        geom_type, polygon_count, preview = self._summarise_geometry(geometry_data)
                        debug_entry['geometry_type'] = geom_type
                        debug_entry['polygon_count'] = polygon_count
                        debug_entry['geometry_preview'] = preview

                # Check if this alert should be stored (SAME match) or broadcast-only (UGC match)
                is_storage_relevant = relevance.get('is_storage_relevant', False)

                if is_storage_relevant:
                    # SAME code match: Save to database and calculate boundaries
                    is_new, alert, _ = self.save_cap_alert(parsed)
                    if is_new:
                        stats['alerts_new'] += 1
                        per_source_stats[endpoint_type]['alerts_new'] += 1
                        self.logger.info(
                            f"Saved new {self.location_name} alert: {alert.event if alert else parsed['event']} - Sent: {format_local_datetime(parsed.get('sent'))}"
                        )
                        # Track saved new alert
                        alert_summary['status'] = 'saved_new'
                        alert_summary['reason'] = 'New alert saved to database (SAME code match)'
                    else:
                        stats['alerts_updated'] += 1
                        per_source_stats[endpoint_type]['alerts_updated'] += 1
                        self.logger.info(
                            f"Updated {self.location_name} alert: {alert.event if alert else parsed['event']} - Sent: {format_local_datetime(parsed.get('sent'))}"
                        )
                        # Track updated alert
                        alert_summary['status'] = 'updated'
                        alert_summary['reason'] = 'Existing alert updated in database'
                    stats['fetched_alerts'].append(alert_summary)

                    if self._debug_records_enabled:
                        debug_entry['was_saved'] = bool(alert)
                        debug_entry['was_new'] = bool(is_new and alert is not None)
                        debug_entry['alert_db_id'] = getattr(alert, 'id', None) if alert else None
                        if not alert:
                            debug_entry.setdefault('notes', []).append('Database save failed')

                else:
                    # UGC/Zone match only: Broadcast but don't store or calculate boundaries
                    # This happens when UGC codes match zone_codes but none match storage_zone_codes
                    matched_ugcs = relevance.get('relevance_matches', [])
                    alert_same_codes = relevance.get('same_codes', [])
                    self.logger.info(f"╔═ BROADCAST-ONLY ALERT (not stored) ═══════════════════════════")
                    self.logger.info(f"║ Event: {event}")
                    self.logger.info(f"║ ID: {alert_id[:60]}{'...' if len(alert_id) > 60 else ''}")
                    self.logger.info(f"║ Area: {area_desc[:80]}{'...' if len(area_desc) > 80 else ''}")
                    self.logger.info(f"║ Matched UGC codes: {', '.join(matched_ugcs[:5]) if matched_ugcs else 'None'}")
                    self.logger.info(f"║ Alert SAME codes: {', '.join(alert_same_codes[:5]) if alert_same_codes else 'None'}")
                    self.logger.info(f"║ Your SAME codes: {', '.join(sorted(self.same_codes)[:5]) if self.same_codes else 'None configured'}")
                    self.logger.info(f"║ Your storage zones: {', '.join(sorted(self.storage_zone_codes)[:5]) if self.storage_zone_codes else 'None configured'}")
                    self.logger.info(f"║ Sent: {format_local_datetime(parsed.get('sent'))}")
                    self.logger.info(f"║ Reason: Matched zone_codes for broadcast, but no match in SAME or storage_zone_codes")
                    self.logger.info(f"╚═══════════════════════════════════════════════════════════════")
                    # Track broadcast-only alert
                    alert_summary['status'] = 'broadcast_only'
                    alert_summary['reason'] = 'UGC/Zone match - broadcast to displays but not stored'
                    alert_summary['ugc_codes'] = matched_ugcs[:5] if matched_ugcs else []
                    stats['fetched_alerts'].append(alert_summary)
                    if self._debug_records_enabled:
                        debug_entry.setdefault('notes', []).append('Broadcast-only (UGC match, no storage)')
                        debug_entry['was_saved'] = False
                        debug_entry['was_new'] = False

                    # Publish broadcast-only alert to Redis for EAS service
                    self._publish_alert_event('alerts:broadcast_only', {
                        'event': event,
                        'severity': parsed.get('severity'),
                        'urgency': parsed.get('urgency'),
                        'certainty': parsed.get('certainty'),
                        'sent': parsed.get('sent'),
                        'expires': parsed.get('expires'),
                        'raw_json': alert_data.get('raw_json', {})
                    })

            self.cleanup_old_poll_history()

            # Catch-up: re-run the forwarding decision for any recent,
            # unexpired alert whose insert pipeline died before recording one.
            try:
                self.retry_unevaluated_forwards()
            except Exception as exc:
                self.logger.error(f"Forwarding catch-up sweep failed: {exc}")

            # Ensure every polled source type has an entry (even if 0 alerts came back)
            for src_type, src_endpoints in self.last_endpoints_by_type.items():
                if src_type not in per_source_stats:
                    per_source_stats[src_type] = _init_source_stats()
                # Propagate fetch-phase errors into per-source status
                src_errors = self.last_per_source_errors.get(src_type, [])
                if src_errors:
                    per_source_stats[src_type]['error_message'] = '; '.join(src_errors)
                    per_source_stats[src_type]['status'] = (
                        'PARTIAL_SUCCESS' if per_source_stats[src_type]['alerts_fetched'] > 0
                        else 'ERROR'
                    )

            stats['execution_time_ms'] = int((time.time() - start) * 1000)

            self.log_poll_history(stats, per_source_stats)
            self.persist_debug_records(poll_run_id, poll_start_utc, stats, debug_records)
            self.cleanup_old_debug_records()

            # Publish LED refresh event to update display with all current alerts
            self._publish_alert_event('alerts:led:refresh', {
                'timestamp': utc_now()
            })

            # Log poll summary with location info for debugging
            self.logger.info("═══════════════════════════════════════════════════════════════")
            self.logger.info(f"POLL CYCLE COMPLETE - {self.location_name}")
            self.logger.info("═══════════════════════════════════════════════════════════════")
            self.logger.info(f"ENDPOINTS POLLED: {len(self.cap_endpoints)}")
            for ep in self.cap_endpoints:
                if 'weather.gov' in ep:
                    self.logger.info(f"  [NOAA] {ep}")
                elif 'fema.gov' in ep:
                    self.logger.info(f"  [IPAWS] {ep}")
                else:
                    self.logger.info(f"  [CUSTOM] {ep}")
            self.logger.info("-" * 63)
            self.logger.info(f"RESULTS:")
            self.logger.info(f"  Total fetched from all endpoints: {stats['alerts_fetched']}")
            self.logger.info(f"  Accepted (matched your location): {stats['alerts_accepted']}")
            self.logger.info(f"  New (saved to database):          {stats['alerts_new']}")
            self.logger.info(f"  Updated (existing alert):         {stats['alerts_updated']}")
            self.logger.info(f"  Filtered (not your location):     {stats['alerts_filtered']}")
            self.logger.info("-" * 63)
            if stats['alerts_fetched'] == 0:
                self.logger.warning("NO ALERTS FETCHED! This could mean:")
                self.logger.warning("  - No active alerts in the zones you're polling")
                self.logger.warning("  - Network/API connectivity issues")
                self.logger.warning("  - Check endpoints above to verify correct zone codes")
            elif stats['alerts_accepted'] == 0 and stats['alerts_fetched'] > 0:
                self.logger.warning(f"ALERTS FETCHED BUT NONE MATCHED YOUR LOCATION!")
                self.logger.warning(f"  Your zone codes: {sorted(self.zone_codes)}")
                self.logger.warning(f"  Your SAME codes: {sorted(self.same_codes)}")
                self.logger.warning(f"  Check if alerts match your configured zones above")
            self.logger.info(f"YOUR CONFIGURATION:")
            self.logger.info(f"  Zone codes (for polling): {sorted(self.zone_codes)}")
            self.logger.info(f"  SAME/FIPS codes (for matching): {sorted(self.same_codes)}")
            self.logger.info(f"  Storage zones (for saving): {sorted(self.storage_zone_codes)}")
            if stats['sources']:
                self.logger.info(f"  Sources seen: {', '.join(stats['sources'])}")
            self.logger.info("═══════════════════════════════════════════════════════════════")

            self.log_system_event('INFO', f"CAP polling successful: {stats['alerts_new']} new alerts", stats)

        except Exception as e:
            stats['status'] = 'ERROR'
            stats['error_message'] = str(e)
            stats['execution_time_ms'] = int((time.time() - start) * 1000)
            self.logger.error(f"Error in polling cycle: {e}")
            self.log_system_event('ERROR', f"CAP polling failed: {e}", stats)

            self.persist_debug_records(poll_run_id, poll_start_utc, stats, debug_records)
            self.cleanup_old_debug_records()

        return stats

    def close(self):
        try:
            if hasattr(self, 'db_session'):
                self.db_session.close()
            if hasattr(self, 'redis_client') and self.redis_client:
                try:
                    self.redis_client.close()
                except Exception as redis_exc:
                    self.logger.debug("Redis client cleanup failed: %s", redis_exc)
        finally:
            if hasattr(self, 'session'):
                self.session.close()

# =======================================================================================
# Main
# =======================================================================================

def build_database_url_from_env() -> str:
    """Get DATABASE_URL from environment - required for database connection."""
    
    url = os.getenv("DATABASE_URL")
    if not url:
        print("[CAP_POLLER] ERROR: DATABASE_URL environment variable is required", file=sys.stderr)
        sys.exit(1)
    
    print(f"[CAP_POLLER] Using DATABASE_URL from environment")
    return url

def main():
    print("[CAP_POLLER] ========================================")
    print("[CAP_POLLER] main() function called - poller starting")
    print("[CAP_POLLER] ========================================")
    parser = argparse.ArgumentParser(description='Emergency CAP Alert Poller (configurable feeds)')
    print("[CAP_POLLER] Reading database URL from environment...")
    database_url = os.getenv('DATABASE_URL')
    if not database_url:
        raise ValueError("DATABASE_URL environment variable is required")
    parser.add_argument('--database-url',
                        default=database_url,
                        help='SQLAlchemy DB URL (from DATABASE_URL env var)')
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

    # Logging to stdout for service management and systemd
    from app_core.logging_context import install_alert_filter
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format='%(asctime)s - %(name)s - %(levelname)s - [alert=%(alert_id)s] %(message)s',
        handlers=[logging.StreamHandler(sys.stdout)]
    )
    install_alert_filter()
    logger = logging.getLogger(__name__)

    startup_utc = utc_now()
    # Unified poller - polls NOAA + IPAWS + custom sources, publishes to Redis
    logger.info("Starting CAP Alert Poller - Unified Mode (NOAA + IPAWS) with Redis Event Publishing")
    logger.info(f"Startup time: {format_local_datetime(startup_utc)}")

    cli_endpoints = list(args.cap_endpoints or [])
    if args.cap_endpoints_csv:
        cli_endpoints.extend([
            endpoint.strip()
            for endpoint in args.cap_endpoints_csv.split(',')
            if endpoint.strip()
        ])

    poller = CAPPoller(
        args.database_url,
        cap_endpoints=cli_endpoints or None,
    )

    try:
        if args.fix_geometry:
            logger.info("Running geometry fix for existing alerts...")
            stats = poller.fix_existing_geometry()
            print(json_dumps(stats, indent=2))
        elif args.continuous:
            # Read initial interval from args, but will dynamically update from DB
            interval = max(30, args.interval)
            if interval != args.interval:
                logger.warning(
                    f"Interval {args.interval}s is below minimum; using {interval}s to prevent excessive CPU usage"
                )
            logger.info(f"Running continuously with {interval} second intervals (will update from database settings)")
            
            consecutive_errors = 0
            max_backoff = 300  # Maximum 5 minutes between retries
            first_iteration = True
            
            while True:
                try:
                    # Check poller settings from database for dynamic configuration
                    poller_enabled = True
                    db_interval = interval  # Default to current interval
                    try:
                        poller_settings = PollerSettings.query.first()
                        if poller_settings:
                            poller_enabled = poller_settings.enabled
                            db_interval = max(30, poller_settings.poll_interval_sec)  # Enforce minimum
                            if db_interval != interval:
                                logger.info(f"Poll interval updated from database: {interval}s → {db_interval}s")
                                interval = db_interval
                    except Exception as e:
                        # If PollerSettings table doesn't exist yet or query fails, use args
                        logger.debug(f"Failed to read poller settings from database, using command line arguments: {e}")
                    
                    # Sleep before polling (except on first iteration) to prevent CPU hammering
                    # This ensures we always wait between polls, even if a poll completes very quickly
                    if not first_iteration:
                        if consecutive_errors > 0:
                            # Exponential backoff for errors: 60s, 120s, 240s, up to max_backoff
                            backoff_time = min(60 * (2 ** (consecutive_errors - 1)), max_backoff)
                            logger.info(f"Backing off for {backoff_time} seconds after {consecutive_errors} consecutive error(s)...")
                            time.sleep(backoff_time)
                        else:
                            # Normal interval for successful polls
                            logger.info(f"Waiting {interval} seconds before next poll...")
                            time.sleep(interval)
                    first_iteration = False
                    
                    # Check if poller is enabled before polling
                    if not poller_enabled:
                        logger.info("Poller disabled in database settings, skipping poll cycle")
                        consecutive_errors = 0
                        continue
                    
                    stats = poller.poll_and_process()
                    print(json_dumps(stats, indent=2))
                    logger.info(f"Polling cycle complete.")
                    consecutive_errors = 0  # Reset error counter on success
                except KeyboardInterrupt:
                    logger.info("Received interrupt signal, shutting down")
                    break
                except Exception as e:
                    consecutive_errors += 1
                    logger.error(f"Error in continuous polling (attempt {consecutive_errors}): {e}", exc_info=True)
                    # Backoff will be applied at the start of the next iteration
                    # If this is a JSON serialization error, log the problematic stats
                    if "json" in str(e).lower() or "serializ" in str(e).lower():
                        logger.error(f"Stats that failed to serialize: {type(stats)}")
                        for key, value in stats.items():
                            try:
                                json_dumps({key: value})
                            except Exception as json_err:
                                logger.error(f"Key '{key}' with value type {type(value)} cannot be JSON serialized: {json_err}")
        else:
            stats = poller.poll_and_process()
            print(json_dumps(stats, indent=2))
    finally:
        poller.close()

if __name__ == '__main__':
    main()
