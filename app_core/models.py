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

from __future__ import annotations

"""Database models used by the NOAA alerts application.

Historically every SQLAlchemy model lived in this single ~2.4k-line module.
The class definitions have been split into topical sibling modules
(``_models_alerts``, ``_models_admin``, ``_models_audio``, ``_models_displays``,
``_models_polling``, ``_models_radio``, ``_models_settings``,
``_models_signage``) that share a common base in ``_models_base``.

This module re-exports every public name those submodules expose, so external
callers continue to ``from app_core.models import CAPAlert`` exactly as before.
The on-disk split is purely organisational; no class definitions, table names,
columns, or method signatures were changed.
"""

# Shared helpers, typing, and SQLAlchemy primitives.  These re-exports keep
# legacy ``from app_core.models import db`` (and the various typing/stdlib
# names that used to be incidentally exposed) working unchanged.
from ._models_base import (
    ALERT_SOURCE_UNKNOWN,
    Any,
    DEFAULT_LOCATION_SETTINGS,
    Dict,
    Geometry,
    JSONB,
    List,
    Optional,
    _GEOMETRY_SUPPORTED,
    _geometry_type,
    _log_info,
    _log_warning,
    _spatial_backend_supports_geometry,
    current_app,
    datetime,
    db,
    has_app_context,
    hashlib,
    make_url,
    normalize_alert_source,
    os,
    utc_now,
    werkzeug_check_password_hash,
    werkzeug_generate_password_hash,
)

# Import Role and Permission models to ensure they're available for
# relationship resolution.  This prevents "failed to locate a name ('Role')"
# errors when AdminUser mapper is configured.
from app_core.auth.roles import Permission, Role

from ._models_alerts import (
    AlertDeliveryReport,
    Boundary,
    CAPAlert,
    EASDecodedAudio,
    EASMessage,
    Intersection,
    ManualEASActivation,
    NWSZone,
    ReceivedEASAlert,
    USCountyBoundary,
)
from ._models_admin import AdminSession, AdminUser, SystemLog
from ._models_gating import AlertGatingSettings, GatedAlert
from ._models_backup import BackupVerificationRun
from ._models_heartbeat import HeartbeatSettings
from ._models_polling import PollDebugRecord, PollHistory, PollerSettings
from ._models_settings import (
    AlertFilterSettings,
    ApplicationSettings,
    AutoPurgeSettings,
    CertbotSettings,
    EASDecoderMonitorSettings,
    EASSettings,
    Fail2banSettings,
    HardwareSettings,
    IcecastSettings,
    LocationSettings,
    NotificationSettings,
    TTSPronunciationRule,
    TTSSettings,
    TTS_BUILTIN_PRONUNCIATIONS,
    TailscaleSettings,
)
from ._models_radio import RadioReceiver, RadioReceiverStatus
from ._models_signage import (
    LEDMessage,
    LEDRSSFeed,
    LEDRSSItem,
    LEDSignStatus,
    VFDDisplay,
    VFDStatus,
)
from ._models_audio import (
    AudioAlert,
    AudioHealthStatus,
    AudioSourceConfigDB,
    AudioSourceMetrics,
    StreamMetadataLog,
)
from ._models_displays import (
    DisplayScreen,
    GPIOActivationLog,
    LocalAuthority,
    RWTScheduleConfig,
    ScreenRotation,
)
# Web-traffic analytics models live in the analytics package; re-export them
# here so they register on the shared metadata and stay importable from
# ``app_core.models`` like every other table.
from app_core.analytics.web_traffic import TrafficAnalyticsSettings, WebRequestLog

# Wire the alert-correlation-ID auto-populate hook onto log-shaped tables.
# Every INSERT to one of these tables made while a logging_context alert
# is bound will record the identifier without the call site having to know
# about it.  GPIOActivationLog uses its legacy ``alert_id`` column; the
# rest carry the canonical ``alert_identifier`` column added in migration
# 20260521_add_alert_identifier_columns.
from .logging_context import attach_alert_id_autopopulate as _attach_alert_autop
_attach_alert_autop(SystemLog, AudioAlert, EASMessage)
_attach_alert_autop(GPIOActivationLog, attr='alert_id')
del _attach_alert_autop


__all__ = [
    "db",
    "AlertDeliveryReport",
    "AlertFilterSettings",
    "AlertGatingSettings",
    "ApplicationSettings",
    "AudioAlert",
    "AudioHealthStatus",
    "AudioSourceConfigDB",
    "AudioSourceMetrics",
    "AutoPurgeSettings",
    "AdminUser",
    "BackupVerificationRun",
    "Boundary",
    "CAPAlert",
    "CertbotSettings",
    "DisplayScreen",
    "EASDecodedAudio",
    "EASMessage",
    "Fail2banSettings",
    "GatedAlert",
    "GPIOActivationLog",
    "HeartbeatSettings",
    "IcecastSettings",
    "Intersection",
    "LEDMessage",
    "LEDSignStatus",
    "LocalAuthority",
    "LocationSettings",
    "ManualEASActivation",
    "NotificationSettings",
    "NWSZone",
    "Permission",
    "PollDebugRecord",
    "PollHistory",
    "RadioReceiver",
    "RadioReceiverStatus",
    "ReceivedEASAlert",
    "Role",
    "RWTScheduleConfig",
    "ScreenRotation",
    "StreamMetadataLog",
    "SystemLog",
    "TailscaleSettings",
    "TrafficAnalyticsSettings",
    "USCountyBoundary",
    "VFDDisplay",
    "VFDStatus",
    "WebRequestLog",
]
