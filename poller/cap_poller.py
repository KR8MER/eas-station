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
    try:
        load_dotenv(_config_path, override=True)
        print(f"[CAP_POLLER] Master config loaded successfully")
    except (PermissionError, OSError) as e:
        print(f"[CAP_POLLER] Warning: Could not load .env from {_config_path}: {e}. Using environment variables only.")
else:
    print(f"[CAP_POLLER] Master config not found, using environment variables only")

# Always load a local .env file last so it only fills in missing values
print(f"[CAP_POLLER] Loading fallback .env file (if exists)")
try:
    load_dotenv(override=True)
except (PermissionError, FileNotFoundError, OSError) as e:
    print(f"[CAP_POLLER] Warning: Could not load .env file: {e}. Using environment variables only.")
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
        # EAS forwarding tracking
        eas_forwarded = Column(Boolean, default=False, nullable=False)
        eas_forwarding_reason = Column(String(255))
        eas_audio_url = Column(String(512))
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
        storage_zone_codes = Column(JSON)
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

        # HTTP Session with compliance headers for both NOAA and IPAWS
        # NOAA Weather API: https://www.weather.gov/documentation/services-web-api
        # - Requires User-Agent with contact info
        # - Returns application/geo+json for CAP alerts
        # IPAWS/FEMA: https://www.fema.gov/about/openfema/data-sets
        # - Returns application/atom+xml or application/cap+xml
        # - Accepts wildcard or specific XML formats
        self.session = requests.Session()
        default_user_agent = os.getenv(
            'NOAA_USER_AGENT',
            'EAS Station/2.12 (+https://github.com/KR8MER/eas-station; support@easstation.com)',
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
        # Configure sources via IPAWS_CAP_FEED_URLS and CAP_ENDPOINTS in .env file

        configured_endpoints: List[str] = []

        def _extend_from_csv(csv_value: Optional[str]) -> None:
            if not csv_value:
                return
            for endpoint in csv_value.split(','):
                cleaned = endpoint.strip()
                if cleaned:
                    configured_endpoints.append(cleaned)

        # Read all configured endpoints from various sources
        _extend_from_csv(os.getenv('CAP_ENDPOINTS'))
        
        # Always read IPAWS URLs (unified poller)
        _extend_from_csv(os.getenv('IPAWS_CAP_FEED_URLS'))

        if cap_endpoints:
            configured_endpoints.extend([endpoint for endpoint in cap_endpoints if endpoint])

        # Calculate default timestamp for IPAWS URLs with {timestamp} placeholder
        # This is needed for URLs configured via the UI which use template placeholders
        lookback_hours = os.getenv('IPAWS_DEFAULT_LOOKBACK_HOURS', '12')
        try:
            lookback_hours_int = max(1, int(lookback_hours))
        except ValueError:
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
            return []
        
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
            record = self.db_session.query(LocationSettings).order_by(LocationSettings.id).first()
            if record:
                fips_codes, _ = sanitize_fips_codes(record.fips_codes or defaults['fips_codes'])
                storage_zones = getattr(record, 'storage_zone_codes', None)
                settings.update({
                    'county_name': record.county_name or defaults['county_name'],
                    'state_code': (record.state_code or defaults['state_code']).upper(),
                    'timezone': record.timezone or defaults['timezone'],
                    'zone_codes': normalise_upper(record.zone_codes) or list(defaults['zone_codes']),
                    'storage_zone_codes': normalise_upper(storage_zones) if storage_zones else list(defaults['storage_zone_codes']),
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

        for endpoint in self.cap_endpoints:
            try:
                self.logger.info(f"Fetching alerts from: {endpoint}")
                response = self.session.get(endpoint, timeout=timeout)
                
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
                for alert in features:
                    props = alert.get('properties', {})

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
            except requests.exceptions.Timeout as exc:
                error_msg = (
                    f"Timeout fetching from {endpoint} after {timeout}s. "
                    f"API may be slow or rate limiting requests. Error: {str(exc)}"
                )
                self.logger.error(error_msg)
                self.last_fetch_errors.append(f"Timeout: {error_msg}")
            except requests.exceptions.RequestException as exc:
                error_msg = f"Error fetching from {endpoint}: {str(exc)}"
                self.logger.error(error_msg)
                self.last_fetch_errors.append(f"Request Error: {error_msg}")
            except Exception as exc:
                error_msg = f"Unexpected error fetching from {endpoint}: {str(exc)}"
                self.logger.error(error_msg)
                self.last_fetch_errors.append(f"Unexpected Error: {error_msg}")

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

            for ugc in normalized_ugc:
                if ugc in self.zone_codes:
                    # Check if this UGC code is in storage_zone_codes (local county)
                    is_storage_ugc = ugc in self.storage_zone_codes
                    if is_storage_ugc:
                        message = f"✓ Alert ACCEPTED by UGC: {event} ({ugc}) [STORAGE+BROADCAST]"
                    else:
                        message = f"✓ Alert ACCEPTED by UGC: {event} ({ugc}) [BROADCAST ONLY - no storage/boundaries]"
                    result.update(
                        {
                            'is_relevant': True,
                            'is_storage_relevant': is_storage_ugc,
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
            # NOAA API uses 'id' field, IPAWS/CAP uses 'identifier' - check both
            identifier = properties.get('identifier') or properties.get('id')
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
        self._set_alert_geometry(existing, geometry_data)
        existing.updated_at = utc_now()
        self.db_session.commit()

        # Use PostGIS ST_Equals for reliable geometry comparison
        geom_changed = self._has_geometry_changed(old_geom, existing.geom)

        if geom_changed or self._needs_intersection_calculation(existing):
            self.process_intersections(existing)
        
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

        # First commit: Save alert to database to get the ID needed for EAS message linking
        self.db_session.add(new_alert)
        self.db_session.commit()

        if new_alert.geom:
            self.process_intersections(new_alert)
        
        # Publish new alert event to Redis for EAS service to handle
        if not self.is_alert_expired(new_alert):
            # Publish to EAS service for broadcast decision
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

        self.logger.info(f"Saved new alert: {new_alert.identifier} - {new_alert.event}")
        return True, new_alert, None

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
        }

        debug_records: List[Dict[str, Any]] = []

        try:
            # Log poller mode and endpoints
            endpoint_summary = f" ({len(self.cap_endpoints)} endpoint{'s' if len(self.cap_endpoints) != 1 else ''})"

            self.logger.info(
                f"Starting alert polling cycle [NOAA + IPAWS]{endpoint_summary} for {self.location_name} at {format_local_datetime(poll_start_utc)}"
            )

            # Log first endpoint being polled for visibility
            if self.cap_endpoints:
                first_endpoint = self.cap_endpoints[0]
                if 'tdl.apps.fema.gov' in first_endpoint:
                    env_marker = " [STAGING/TDL]"
                elif 'apps.fema.gov' in first_endpoint:
                    env_marker = " [PRODUCTION]"
                elif 'weather.gov' in first_endpoint:
                    env_marker = " [NOAA Weather]"
                else:
                    env_marker = ""
                self.logger.info(f"Polling: {first_endpoint}{env_marker}")

            alerts_data = self.fetch_cap_alerts()
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

                # Only collect debug data if debug records are enabled (expensive)
                if self._debug_records_enabled:
                    debug_entry = self._initialise_debug_entry(alert_data, relevance, poll_run_id, poll_start_utc)
                    debug_records.append(debug_entry)

                if not relevance.get('is_relevant'):
                    self.logger.info(f"• Filtered out (not specific to {self.county_upper})")
                    stats['alerts_filtered'] += 1
                    if self._debug_records_enabled and 'debug_entry' in locals():
                        debug_entry.setdefault('notes', []).append('Filtered out by strict location rules')
                    continue

                stats['alerts_accepted'] += 1
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
                        self.logger.info(
                            f"Saved new {self.location_name} alert: {alert.event if alert else parsed['event']} - Sent: {format_local_datetime(parsed.get('sent'))}"
                        )
                    else:
                        stats['alerts_updated'] += 1
                        self.logger.info(
                            f"Updated {self.location_name} alert: {alert.event if alert else parsed['event']} - Sent: {format_local_datetime(parsed.get('sent'))}"
                        )

                    if self._debug_records_enabled:
                        debug_entry['was_saved'] = bool(alert)
                        debug_entry['was_new'] = bool(is_new and alert is not None)
                        debug_entry['alert_db_id'] = getattr(alert, 'id', None) if alert else None
                        if not alert:
                            debug_entry.setdefault('notes', []).append('Database save failed')

                else:
                    # UGC/Zone match only: Broadcast but don't store or calculate boundaries
                    self.logger.info(
                        f"Broadcast-only alert (UGC match): {event} - Sent: {format_local_datetime(parsed.get('sent'))}"
                    )
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
            self.log_poll_history(stats)
            self.persist_debug_records(poll_run_id, poll_start_utc, stats, debug_records)
            self.cleanup_old_debug_records()

            # Publish LED refresh event to update display with all current alerts
            self._publish_alert_event('alerts:led:refresh', {
                'timestamp': utc_now()
            })

            stats['execution_time_ms'] = int((time.time() - start) * 1000)
            self.logger.info(
                f"Polling cycle completed: {stats['alerts_accepted']} accepted, {stats['alerts_new']} new, "
                f"{stats['alerts_updated']} updated, {stats['alerts_filtered']} filtered, "
                f"{stats['duplicates_filtered']} duplicates skipped"
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
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[logging.StreamHandler(sys.stdout)]
    )
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
            # Enforce minimum interval to prevent excessive CPU usage
            interval = max(30, args.interval)
            if interval != args.interval:
                logger.warning(
                    f"Interval {args.interval}s is below minimum; using {interval}s to prevent excessive CPU usage"
                )
            logger.info(f"Running continuously with {interval} second intervals")
            
            consecutive_errors = 0
            max_backoff = 300  # Maximum 5 minutes between retries
            first_iteration = True
            
            while True:
                try:
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
