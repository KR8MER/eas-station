"""
EAS Station - Emergency Alert System
Copyright (c) 2025-2026 Timothy Kramer (KR8MER)

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

"""Alert and EAS message models split out of the historical ``models`` module."""

from ._models_base import (
    ALERT_SOURCE_UNKNOWN,
    Any,
    Dict,
    JSONB,
    _geometry_type,
    db,
    normalize_alert_source,
    utc_now,
)


class NWSZone(db.Model):
    """Reference table containing NOAA public forecast zone metadata."""

    __tablename__ = "nws_zones"

    id = db.Column(db.Integer, primary_key=True)
    zone_code = db.Column(db.String(6), nullable=False, unique=True)
    state_code = db.Column(db.String(2), nullable=False, index=True)
    zone_number = db.Column(db.String(3), nullable=False)
    zone_type = db.Column(db.String(1), nullable=False, default="Z")
    cwa = db.Column(db.String(9), nullable=False, index=True)
    time_zone = db.Column(db.String(2))
    fe_area = db.Column(db.String(4))
    name = db.Column(db.String(255), nullable=False)
    short_name = db.Column(db.String(64))
    state_zone = db.Column(db.String(5), nullable=False, index=True)
    longitude = db.Column(db.Float)
    latitude = db.Column(db.Float)

    def __repr__(self) -> str:  # pragma: no cover - debugging helper
        return f"<NWSZone {self.zone_code} {self.name}>"


class Boundary(db.Model):
    __tablename__ = "boundaries"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False)
    type = db.Column(db.String(50), nullable=False)
    description = db.Column(db.Text)
    geom = db.Column(_geometry_type("GEOMETRY"))
    created_at = db.Column(db.DateTime(timezone=True), default=utc_now)
    updated_at = db.Column(
        db.DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
    )


class CAPAlert(db.Model):
    __tablename__ = "cap_alerts"

    id = db.Column(db.Integer, primary_key=True)
    identifier = db.Column(db.String(255), unique=True, nullable=False)
    sent = db.Column(db.DateTime(timezone=True), nullable=False, index=True)
    expires = db.Column(db.DateTime(timezone=True))
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
    geom = db.Column(_geometry_type("GEOMETRY"))
    source = db.Column(db.String(32), nullable=False, default=ALERT_SOURCE_UNKNOWN)
    
    # EAS forwarding tracking - records whether this alert triggered an EAS broadcast
    eas_forwarded = db.Column(db.Boolean, default=False, nullable=False)
    eas_forwarding_reason = db.Column(db.String(255))  # Why it was or wasn't forwarded
    eas_audio_url = db.Column(db.String(512))  # URL/path to generated EAS audio file

    # IPAWS XML digital signature verification
    signature_verified = db.Column(db.Boolean)  # None=not checked, True=valid, False=invalid
    signature_status = db.Column(db.String(255))  # Human-readable verification result
    certificate_info = db.Column(db.JSON)  # Full X.509 certificate details from IPAWS signature
    ipaws_audio_url = db.Column(db.String(512))  # Path to saved original IPAWS audio file

    # VTEC event identity — extracted from raw_json at ingest time so related
    # alert updates (NEW → CON → EXT → EXP) can be grouped without scanning JSON.
    # The tuple (vtec_office, vtec_phenomenon, vtec_significance, vtec_etn, vtec_year)
    # is the stable event key shared by every product in the same event series.
    vtec_office = db.Column(db.String(4), index=True)       # e.g. 'KIWX'
    vtec_phenomenon = db.Column(db.String(2), index=True)   # e.g. 'SV'
    vtec_significance = db.Column(db.String(1), index=True) # e.g. 'W'
    vtec_etn = db.Column(db.Integer, index=True)            # e.g. 56
    vtec_year = db.Column(db.Integer, index=True)           # e.g. 2026 (ETNs reset annually)
    vtec_action = db.Column(db.String(3))                   # e.g. 'EXP'

    # VTEC event chain linkage — when a newer product (EXT/CAN/UPG/etc.) arrives
    # for the same VTEC event key, older alerts in the chain are marked with the
    # ID of the alert that supersedes them.  This lets the UI hide stale products
    # by default while still offering a full chain view for operators.
    superseded_by_id = db.Column(
        db.Integer,
        db.ForeignKey('cap_alerts.id', ondelete='SET NULL'),
        nullable=True,
        index=True,
    )

    created_at = db.Column(db.DateTime(timezone=True), default=utc_now)
    updated_at = db.Column(
        db.DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
    )

    def __setattr__(self, name, value):  # pragma: no cover - passthrough
        if name == "source":
            value = normalize_alert_source(value) if value else ALERT_SOURCE_UNKNOWN
        super().__setattr__(name, value)


class EASMessage(db.Model):
    __tablename__ = "eas_messages"

    id = db.Column(db.Integer, primary_key=True)
    cap_alert_id = db.Column(db.Integer, db.ForeignKey("cap_alerts.id", ondelete="SET NULL"), index=True)
    same_header = db.Column(db.String(255), nullable=False)
    audio_filename = db.Column(db.String(255), nullable=False)
    text_filename = db.Column(db.String(255), nullable=False)
    audio_data = db.Column(db.LargeBinary)
    eom_audio_data = db.Column(db.LargeBinary)
    same_audio_data = db.Column(db.LargeBinary)
    attention_audio_data = db.Column(db.LargeBinary)
    tts_audio_data = db.Column(db.LargeBinary)
    buffer_audio_data = db.Column(db.LargeBinary)
    tts_warning = db.Column(db.String(255))
    tts_provider = db.Column(db.String(32))
    text_payload = db.Column(db.JSON, default=dict)
    created_at = db.Column(db.DateTime(timezone=True), default=utc_now, index=True)
    metadata_payload = db.Column(db.JSON, default=dict)

    cap_alert = db.relationship(
        "CAPAlert",
        backref=db.backref("eas_messages", lazy="dynamic"),
    )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "cap_alert_id": self.cap_alert_id,
            "same_header": self.same_header,
            "audio_filename": self.audio_filename,
            "text_filename": self.text_filename,
            "has_audio_blob": self.audio_data is not None,
            "has_eom_blob": self.eom_audio_data is not None,
            "has_same_audio": self.same_audio_data is not None,
            "has_attention_audio": self.attention_audio_data is not None,
            "has_tts_audio": self.tts_audio_data is not None,
            "has_buffer_audio": self.buffer_audio_data is not None,
            "has_text_payload": bool(self.text_payload),
            "tts_warning": self.tts_warning,
            "tts_provider": self.tts_provider,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "metadata": dict(self.metadata_payload or {}),
        }


class EASDecodedAudio(db.Model):
    __tablename__ = "eas_decoded_audio"

    id = db.Column(db.Integer, primary_key=True)
    created_at = db.Column(db.DateTime(timezone=True), default=utc_now, index=True)
    original_filename = db.Column(db.String(255))
    content_type = db.Column(db.String(128))
    raw_text = db.Column(db.Text)
    same_headers = db.Column(db.JSON, default=list)
    quality_metrics = db.Column(db.JSON, default=dict)
    segment_metadata = db.Column(db.JSON, default=dict)
    header_audio_data = db.Column(db.LargeBinary)
    attention_tone_audio_data = db.Column(db.LargeBinary)  # EBS or NWS 1050Hz tone
    narration_audio_data = db.Column(db.LargeBinary)  # Voice narration segment
    eom_audio_data = db.Column(db.LargeBinary)
    buffer_audio_data = db.Column(db.LargeBinary)
    composite_audio_data = db.Column(db.LargeBinary)  # Complete alert audio (all segments combined)
    # Deprecated: kept for backward compatibility with old decodes
    message_audio_data = db.Column(db.LargeBinary)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "original_filename": self.original_filename,
            "content_type": self.content_type,
            "raw_text": self.raw_text,
            "same_headers": list(self.same_headers or []),
            "quality_metrics": dict(self.quality_metrics or {}),
            "segment_metadata": dict(self.segment_metadata or {}),
            "has_header_audio": self.header_audio_data is not None,
            "has_attention_tone_audio": self.attention_tone_audio_data is not None,
            "has_narration_audio": self.narration_audio_data is not None,
            "has_eom_audio": self.eom_audio_data is not None,
            "has_buffer_audio": self.buffer_audio_data is not None,
            "has_composite_audio": self.composite_audio_data is not None,
            "has_message_audio": self.message_audio_data is not None,  # Deprecated
        }


class ReceivedEASAlert(db.Model):
    """
    Tracks EAS alerts received from audio monitoring sources.
    Records forwarding decisions and links to broadcast messages.
    """
    __tablename__ = "received_eas_alerts"

    id = db.Column(db.Integer, primary_key=True)

    # Reception details
    received_at = db.Column(db.DateTime(timezone=True), default=utc_now, nullable=False, index=True)
    source_name = db.Column(db.String(100), nullable=False, index=True)  # Which audio source detected this
    alert_source = db.Column(db.String(32), nullable=True, index=True)  # Canonical ingest path: EAS-RF, EAS-STREAM, etc.

    # SAME header data
    raw_same_header = db.Column(db.Text)  # Raw ZCZC string
    event_code = db.Column(db.String(8), index=True)
    event_name = db.Column(db.String(255))
    originator_code = db.Column(db.String(8))
    originator_name = db.Column(db.String(100))
    fips_codes = db.Column(db.JSON, default=list)  # List of FIPS codes from alert
    issue_datetime = db.Column(db.DateTime(timezone=True))
    purge_datetime = db.Column(db.DateTime(timezone=True))
    callsign = db.Column(db.String(16))

    # Forwarding decision
    forwarding_decision = db.Column(db.String(20), nullable=False, index=True)  # 'forwarded', 'ignored', 'error'
    forwarding_reason = db.Column(db.Text)  # Why it was forwarded or ignored (e.g., "FIPS match: 039137")
    matched_fips_codes = db.Column(db.JSON, default=list)  # Which configured FIPS codes matched

    # Link to generated broadcast (if forwarded)
    generated_message_id = db.Column(db.Integer, db.ForeignKey('eas_messages.id'), nullable=True, index=True)
    generated_message = db.relationship('EASMessage', foreign_keys=[generated_message_id], backref='source_alerts')
    forwarded_at = db.Column(db.DateTime(timezone=True))

    # Full decoded data (JSON)
    full_alert_data = db.Column(JSONB)  # Complete EASAlert object as JSON

    # Quality metrics
    decode_confidence = db.Column(db.Float)  # 0.0 to 1.0

    # Raw received audio (WAV bytes captured at detection time)
    raw_audio_data = db.Column(db.LargeBinary, nullable=True)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "received_at": self.received_at.isoformat() if self.received_at else None,
            "source_name": self.source_name,
            "alert_source": self.alert_source,
            "raw_same_header": self.raw_same_header,
            "event_code": self.event_code,
            "event_name": self.event_name,
            "originator_code": self.originator_code,
            "originator_name": self.originator_name,
            "fips_codes": list(self.fips_codes or []),
            "issue_datetime": self.issue_datetime.isoformat() if self.issue_datetime else None,
            "purge_datetime": self.purge_datetime.isoformat() if self.purge_datetime else None,
            "callsign": self.callsign,
            "forwarding_decision": self.forwarding_decision,
            "forwarding_reason": self.forwarding_reason,
            "matched_fips_codes": list(self.matched_fips_codes or []),
            "generated_message_id": self.generated_message_id,
            "forwarded_at": self.forwarded_at.isoformat() if self.forwarded_at else None,
            "decode_confidence": self.decode_confidence,
            "full_alert_data": self.full_alert_data,
            "has_audio": self.raw_audio_data is not None,
        }


class ManualEASActivation(db.Model):
    __tablename__ = "manual_eas_activations"

    id = db.Column(db.Integer, primary_key=True)
    identifier = db.Column(db.String(120), nullable=False)
    event_code = db.Column(db.String(8), nullable=False)
    event_name = db.Column(db.String(255), nullable=False)
    status = db.Column(db.String(32), nullable=False)
    message_type = db.Column(db.String(32), nullable=False)
    same_header = db.Column(db.String(255), nullable=False)
    same_locations = db.Column(db.JSON, nullable=False, default=list)
    tone_profile = db.Column(db.String(32), nullable=False)
    tone_seconds = db.Column(db.Float)
    sample_rate = db.Column(db.Integer)
    includes_tts = db.Column(db.Boolean, default=False)
    tts_warning = db.Column(db.String(255))
    sent_at = db.Column(db.DateTime(timezone=True))
    expires_at = db.Column(db.DateTime(timezone=True))
    headline = db.Column(db.String(240))
    message_text = db.Column(db.Text)
    instruction_text = db.Column(db.Text)
    duration_minutes = db.Column(db.Float)
    storage_path = db.Column(db.String(255), nullable=False)
    summary_filename = db.Column(db.String(255))
    components_payload = db.Column(db.JSON, nullable=False, default=dict)
    metadata_payload = db.Column(db.JSON, nullable=False, default=dict)
    created_at = db.Column(db.DateTime(timezone=True), default=utc_now)
    archived_at = db.Column(db.DateTime(timezone=True))
    triggered_at = db.Column(db.DateTime(timezone=True))
    created_by = db.Column(db.String(100), nullable=True)
    triggered_by = db.Column(db.String(100), nullable=True)
    created_by_ip = db.Column(db.String(45), nullable=True)
    triggered_by_ip = db.Column(db.String(45), nullable=True)
    # Binary audio data cached in database
    composite_audio_data = db.Column(db.LargeBinary)
    same_audio_data = db.Column(db.LargeBinary)
    attention_audio_data = db.Column(db.LargeBinary)
    tts_audio_data = db.Column(db.LargeBinary)
    eom_audio_data = db.Column(db.LargeBinary)
    # Uploaded audio segments (user-provided files)
    narration_upload_audio_data = db.Column(db.LargeBinary)
    pre_alert_audio_data = db.Column(db.LargeBinary)
    post_alert_audio_data = db.Column(db.LargeBinary)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "identifier": self.identifier,
            "event_code": self.event_code,
            "event_name": self.event_name,
            "status": self.status,
            "message_type": self.message_type,
            "same_header": self.same_header,
            "same_locations": list(self.same_locations or []),
            "tone_profile": self.tone_profile,
            "tone_seconds": self.tone_seconds,
            "sample_rate": self.sample_rate,
            "includes_tts": bool(self.includes_tts),
            "tts_warning": self.tts_warning,
            "sent_at": self.sent_at.isoformat() if self.sent_at else None,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "headline": self.headline,
            "message_text": self.message_text,
            "instruction_text": self.instruction_text,
            "duration_minutes": self.duration_minutes,
            "storage_path": self.storage_path,
            "summary_filename": self.summary_filename,
            "components": dict(self.components_payload or {}),
            "metadata": dict(self.metadata_payload or {}),
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "archived_at": self.archived_at.isoformat() if self.archived_at else None,
            "triggered_at": self.triggered_at.isoformat() if self.triggered_at else None,
            "created_by": self.created_by,
            "triggered_by": self.triggered_by,
            "created_by_ip": self.created_by_ip,
            "triggered_by_ip": self.triggered_by_ip,
        }


class AlertDeliveryReport(db.Model):
    __tablename__ = "alert_delivery_reports"

    id = db.Column(db.Integer, primary_key=True)
    generated_at = db.Column(
        db.DateTime(timezone=True), nullable=False, default=utc_now
    )
    window_start = db.Column(db.DateTime(timezone=True), nullable=False)
    window_end = db.Column(db.DateTime(timezone=True), nullable=False)
    scope = db.Column(db.String(16), nullable=False)
    originator = db.Column(db.String(64))
    station = db.Column(db.String(128))
    total_alerts = db.Column(db.Integer, nullable=False, default=0)
    delivered_alerts = db.Column(db.Integer, nullable=False, default=0)
    delayed_alerts = db.Column(db.Integer, nullable=False, default=0)
    average_latency_seconds = db.Column(db.Integer)

    __table_args__ = (
        db.Index(
            "idx_alert_delivery_reports_scope_window",
            "scope",
            "window_start",
            "window_end",
        ),
        db.Index("idx_alert_delivery_reports_originator", "originator"),
        db.Index("idx_alert_delivery_reports_station", "station"),
    )

    def to_dict(self) -> Dict[str, Any]:  # pragma: no cover - convenience helper
        return {
            "id": self.id,
            "generated_at": self.generated_at,
            "window_start": self.window_start,
            "window_end": self.window_end,
            "scope": self.scope,
            "originator": self.originator,
            "station": self.station,
            "total_alerts": self.total_alerts,
            "delivered_alerts": self.delivered_alerts,
            "delayed_alerts": self.delayed_alerts,
            "average_latency_seconds": self.average_latency_seconds,
        }


class Intersection(db.Model):
    __tablename__ = "intersections"

    id = db.Column(db.Integer, primary_key=True)
    cap_alert_id = db.Column(
        db.Integer,
        db.ForeignKey("cap_alerts.id", ondelete="CASCADE"),
    )
    boundary_id = db.Column(
        db.Integer,
        db.ForeignKey("boundaries.id", ondelete="CASCADE"),
    )
    intersection_area = db.Column(db.Float)
    created_at = db.Column(db.DateTime(timezone=True), default=utc_now)


class USCountyBoundary(db.Model):
    """US Census county boundary for FIPS-based alert geometry lookup.

    Loaded from Census Bureau TIGER/Line shapefiles.  Used to build
    union geometry for multi-county IPAWS alerts that carry SAME geocodes
    but no inline polygon.
    """
    __tablename__ = "us_county_boundaries"

    id = db.Column(db.Integer, primary_key=True)
    statefp = db.Column(db.String(2), nullable=False, index=True)
    countyfp = db.Column(db.String(3), nullable=False)
    geoid = db.Column(db.String(5), nullable=False, unique=True, index=True)
    name = db.Column(db.String(255), nullable=False)
    namelsad = db.Column(db.String(255))
    stusps = db.Column(db.String(2))
    state_name = db.Column(db.String(100))
    aland = db.Column(db.BigInteger)
    awater = db.Column(db.BigInteger)
    geom = db.Column(_geometry_type("MULTIPOLYGON"))

    @property
    def same_code(self) -> str:
        """Return the 6-digit SAME code (0 + STATEFP + COUNTYFP)."""
        return f"0{self.statefp}{self.countyfp}"

    def __repr__(self) -> str:
        return f"<USCountyBoundary {self.geoid} {self.namelsad or self.name}>"


