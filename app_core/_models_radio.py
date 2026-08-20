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

"""Radio receiver and receiver-status models."""

from typing import TYPE_CHECKING

from ._models_base import Optional, db, utc_now

if TYPE_CHECKING:  # pragma: no cover - import only for type checkers
    # Imported lazily: app_core.radio.manager imports the models package, so a
    # module-level import here would be circular. The to_receiver_config /
    # to_receiver_status return annotations below reference these names.
    from app_core.radio.manager import ReceiverConfig, ReceiverStatus


class RadioReceiver(db.Model):
    """Persistent configuration for SDR hardware receivers.

    Note: For internet stream sources (HTTP/M3U), use the AudioSource system instead.
    RadioReceiver is exclusively for SDR hardware like RTL-SDR and Airspy.

    IMPORTANT: sample_rate vs audio_sample_rate
    - sample_rate: IQ sample rate from SDR hardware (e.g., 2.4 MHz for RTL-SDR)
    - audio_sample_rate: Demodulated audio output rate (e.g., 48 kHz for FM stereo)
    """

    __tablename__ = "radio_receivers"

    id = db.Column(db.Integer, primary_key=True)
    identifier = db.Column(db.String(64), nullable=False)
    display_name = db.Column(db.String(128), nullable=False)
    driver = db.Column(db.String(64), nullable=False)
    frequency_hz = db.Column(db.Float, nullable=False)
    sample_rate = db.Column(db.Integer, nullable=False)  # IQ sample rate (MHz range, e.g., 2400000)
    audio_sample_rate = db.Column(db.Integer, nullable=True)  # Audio output rate (kHz range, e.g., 48000)
    frequency_correction_ppm = db.Column(db.Float, nullable=False, default=0.0)  # PPM correction for clock drift
    gain = db.Column(db.Float)
    external_lna_db = db.Column(db.Float, nullable=False, default=0.0)  # External LNA ahead of SDR (dB)
    bias_t_enabled = db.Column(db.Boolean, nullable=False, default=False)  # Power external LNA via SDR's antenna bias-T
    channel = db.Column(db.Integer)
    serial = db.Column(db.String(128))
    auto_start = db.Column(db.Boolean, nullable=False, default=True)
    enabled = db.Column(db.Boolean, nullable=False, default=True)
    notes = db.Column(db.Text)
    # Audio demodulation settings
    modulation_type = db.Column(db.String(16), nullable=False, default='IQ')  # IQ, FM, AM, NFM, WFM
    audio_output = db.Column(db.Boolean, nullable=False, default=False)  # Enable demodulated audio output
    stereo_enabled = db.Column(db.Boolean, nullable=False, default=True)  # FM stereo decoding
    deemphasis_us = db.Column(db.Float, nullable=False, default=75.0)  # De-emphasis (75μs NA, 50μs EU)
    enable_rbds = db.Column(db.Boolean, nullable=False, default=False)  # Extract RBDS/RDS from FM
    created_at = db.Column(db.DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at = db.Column(
        db.DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
        nullable=False,
    )

    statuses = db.relationship(
        "RadioReceiverStatus",
        back_populates="receiver",
        cascade="all, delete-orphan",
        lazy="dynamic",
    )

    __table_args__ = (
        db.Index("idx_radio_receivers_identifier", identifier, unique=True),
    )

    def to_receiver_config(self) -> "ReceiverConfig":
        """Translate this database row into a radio manager configuration object."""

        from app_core.radio import ReceiverConfig

        # Determine audio sample rate with intelligent defaults
        audio_rate = self.audio_sample_rate
        if audio_rate is None or audio_rate < 20000:
            # Auto-select based on modulation type and stereo settings
            modulation = (self.modulation_type or 'IQ').upper()
            if modulation in ('FM', 'WFM', 'WBFM'):
                # Wide FM (broadcast): higher quality needed
                audio_rate = 48000 if self.stereo_enabled else 32000
            elif modulation in ('NFM', 'AM'):
                # Narrowband FM or AM: lower rate acceptable
                audio_rate = 24000
            else:
                # IQ or unknown: safe default
                audio_rate = 44100

        return ReceiverConfig(
            identifier=self.identifier,
            driver=self.driver,
            frequency_hz=float(self.frequency_hz),
            sample_rate=int(self.sample_rate),
            audio_sample_rate=int(audio_rate),
            frequency_correction_ppm=float(self.frequency_correction_ppm or 0.0),
            gain=self.gain,
            external_lna_db=float(self.external_lna_db or 0.0),
            bias_t_enabled=bool(self.bias_t_enabled),
            channel=self.channel,
            serial=self.serial,
            enabled=bool(self.enabled),
            modulation_type=self.modulation_type or 'IQ',
            audio_output=bool(self.audio_output),
            stereo_enabled=bool(self.stereo_enabled),
            deemphasis_us=float(self.deemphasis_us) if self.deemphasis_us else 75.0,
            enable_rbds=bool(self.enable_rbds),
            auto_start=bool(self.auto_start),
        )

    def latest_status(self) -> Optional["RadioReceiverStatus"]:
        """Return the most recent status sample if any have been recorded."""

        if self.statuses is None:
            return None

        return self.statuses.order_by(RadioReceiverStatus.reported_at.desc()).first()

    def __repr__(self) -> str:  # pragma: no cover - debugging helper
        return (
            f"<RadioReceiver id={self.id} identifier={self.identifier!r} "
            f"driver={self.driver!r} frequency_hz={self.frequency_hz}>"
        )


class RadioReceiverStatus(db.Model):
    """Historical status samples emitted by configured receivers."""

    __tablename__ = "radio_receiver_status"

    id = db.Column(db.Integer, primary_key=True)
    receiver_id = db.Column(
        db.Integer,
        db.ForeignKey("radio_receivers.id", ondelete="CASCADE"),
        nullable=False,
    )
    reported_at = db.Column(db.DateTime(timezone=True), default=utc_now, nullable=False)
    locked = db.Column(db.Boolean, nullable=False, default=False)
    signal_strength = db.Column(db.Float)
    last_error = db.Column(db.Text)
    capture_mode = db.Column(db.String(16))
    capture_path = db.Column(db.String(255))

    receiver = db.relationship(
        "RadioReceiver",
        back_populates="statuses",
    )

    __table_args__ = (
        db.Index("idx_radio_receiver_status_receiver_id", receiver_id),
        db.Index("idx_radio_receiver_status_reported_at", reported_at.desc()),
    )

    def to_receiver_status(self) -> "ReceiverStatus":
        """Convert the status row into the lightweight dataclass used by the manager."""

        from app_core.radio import ReceiverStatus

        return ReceiverStatus(
            identifier=self.receiver.identifier if self.receiver else "unknown",
            locked=bool(self.locked),
            signal_strength=self.signal_strength,
            last_error=self.last_error,
            capture_mode=self.capture_mode,
            capture_path=self.capture_path,
            reported_at=self.reported_at,
        )

    def __repr__(self) -> str:  # pragma: no cover - debugging helper
        return (
            f"<RadioReceiverStatus receiver_id={self.receiver_id} locked={self.locked} "
            f"signal_strength={self.signal_strength}>"
        )


