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

"""Audio source / health / alert / metadata models."""

from ._models_base import JSONB, db, utc_now


class AudioSourceMetrics(db.Model):
    """Real-time audio source metrics for monitoring and health tracking."""
    __tablename__ = "audio_source_metrics"

    id = db.Column(db.Integer, primary_key=True)
    source_name = db.Column(db.String(100), nullable=False, index=True)
    source_type = db.Column(db.String(20), nullable=False)
    
    # Audio levels
    peak_level_db = db.Column(db.Float, nullable=False)
    rms_level_db = db.Column(db.Float, nullable=False)
    peak_level_linear = db.Column(db.Float, nullable=False)
    rms_level_linear = db.Column(db.Float, nullable=False)
    
    # Stream information
    sample_rate = db.Column(db.Integer, nullable=False)
    channels = db.Column(db.Integer, nullable=False)
    frames_captured = db.Column(db.BigInteger, nullable=False)
    
    # Health indicators
    silence_detected = db.Column(db.Boolean, default=False)
    clipping_detected = db.Column(db.Boolean, default=False)
    buffer_utilization = db.Column(db.Float, default=0.0)
    
    # Timing
    timestamp = db.Column(db.DateTime(timezone=True), default=utc_now, nullable=False, index=True)

    # Additional metadata (JSON)
    # Map to existing 'metadata' column to avoid schema drift
    source_metadata = db.Column('metadata', JSONB)


class AudioHealthStatus(db.Model):
    """Overall audio system health status snapshots."""
    __tablename__ = "audio_health_status"

    id = db.Column(db.Integer, primary_key=True)
    source_name = db.Column(db.String(100), nullable=False, index=True)
    
    # Health score (0-100)
    health_score = db.Column(db.Float, nullable=False)
    
    # Status indicators
    is_active = db.Column(db.Boolean, default=False)
    is_healthy = db.Column(db.Boolean, default=False)
    silence_detected = db.Column(db.Boolean, default=False)
    error_detected = db.Column(db.Boolean, default=False)
    
    # Timing information
    uptime_seconds = db.Column(db.Float, default=0.0)
    silence_duration_seconds = db.Column(db.Float, default=0.0)
    time_since_last_signal_seconds = db.Column(db.Float, default=0.0)
    
    # Trend information
    level_trend = db.Column(db.String(20))  # 'rising', 'falling', 'stable'
    trend_value_db = db.Column(db.Float, default=0.0)
    
    # Timestamps
    timestamp = db.Column(db.DateTime(timezone=True), default=utc_now, nullable=False, index=True)
    last_update = db.Column(db.DateTime(timezone=True), default=utc_now)

    # Additional metadata (JSON)
    # Map to existing 'metadata' column to avoid schema drift
    health_metadata = db.Column('metadata', JSONB)


class AudioAlert(db.Model):
    """Audio system alerts and notifications."""
    __tablename__ = "audio_alerts"

    id = db.Column(db.Integer, primary_key=True)
    source_name = db.Column(db.String(100), nullable=False, index=True)
    # Correlation ID tying this row to the alert lifecycle it belongs to.
    # Auto-populated from logging_context when set during the write.
    alert_identifier = db.Column(db.String(255), nullable=True, index=True)

    # Alert classification
    alert_level = db.Column(db.String(20), nullable=False)  # 'info', 'warning', 'error', 'critical'
    alert_type = db.Column(db.String(50), nullable=False)   # 'silence', 'clipping', 'disconnect', etc.
    
    # Alert content
    message = db.Column(db.Text, nullable=False)
    details = db.Column(db.Text)
    
    # Threshold information
    threshold_value = db.Column(db.Float)
    actual_value = db.Column(db.Float)
    
    # Status
    acknowledged = db.Column(db.Boolean, default=False)
    acknowledged_by = db.Column(db.String(100))
    acknowledged_at = db.Column(db.DateTime(timezone=True))
    
    # Resolution
    resolved = db.Column(db.Boolean, default=False)
    resolved_by = db.Column(db.String(100))
    resolved_at = db.Column(db.DateTime(timezone=True))
    resolution_notes = db.Column(db.Text)
    
    # Timestamps
    created_at = db.Column(db.DateTime(timezone=True), default=utc_now, nullable=False, index=True)
    updated_at = db.Column(db.DateTime(timezone=True), default=utc_now, onupdate=utc_now)

    # Additional metadata (JSON)
    # Map to existing 'metadata' column to avoid schema drift
    alert_metadata = db.Column('metadata', JSONB)


class AudioSourceConfigDB(db.Model):
    """Persistent audio source configurations (database model)."""
    __tablename__ = "audio_source_configs"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, unique=True, index=True)
    source_type = db.Column(db.String(20), nullable=False)  # 'sdr', 'alsa', 'pulse', 'file'

    # Configuration parameters (stored as JSON)
    config_params = db.Column('config', JSONB, nullable=False)

    # Source settings
    priority = db.Column(db.Integer, default=0)
    enabled = db.Column(db.Boolean, default=True)
    auto_start = db.Column(db.Boolean, default=False)

    # Timestamps
    created_at = db.Column(db.DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at = db.Column(db.DateTime(timezone=True), default=utc_now, onupdate=utc_now)

    # Optional description
    description = db.Column(db.Text)

    def to_dict(self):
        """Convert configuration to dictionary."""
        return {
            'id': self.id,
            'name': self.name,
            'source_type': self.source_type,
            'config': self.config_params or {},
            'priority': self.priority,
            'enabled': self.enabled,
            'auto_start': self.auto_start,
            'description': self.description,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }


class StreamMetadataLog(db.Model):
    """Persistent log of ICY/stream metadata changes (now-playing events).

    A new row is written every time a source's StreamTitle changes so the
    song-play history can be queried from the web UI.
    """

    __tablename__ = "stream_metadata_log"

    id = db.Column(db.Integer, primary_key=True)
    source_name = db.Column(db.String(100), nullable=False, index=True)
    timestamp = db.Column(db.DateTime(timezone=True), default=utc_now, nullable=False, index=True)

    # Parsed fields
    title = db.Column(db.Text)
    artist = db.Column(db.Text)
    album = db.Column(db.Text)
    artwork_url = db.Column(db.Text)
    length = db.Column(db.String(20))
    display = db.Column(db.Text)  # "Artist – Title" display string

    # Raw ICY StreamTitle string
    raw = db.Column(db.Text)

    # Playback URL — populated when the StreamTitle contains a base64-encoded
    # audio/stream URL or an explicit url="" ICY attribute.
    stream_url = db.Column(db.Text)


