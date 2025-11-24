"""
Pydantic schemas for Audio API endpoints
"""

from typing import Optional, Dict, Any, List
from datetime import datetime
from pydantic import BaseModel, Field, validator


class AudioSourceBase(BaseModel):
    """Base schema for audio source"""
    name: str = Field(..., description="Audio source name", min_length=1, max_length=100)
    type: str = Field(..., description="Source type (sdr, stream, alsa, pulse, file)")
    sample_rate: int = Field(default=22050, description="Sample rate in Hz", ge=8000, le=48000)
    channels: int = Field(default=1, description="Number of audio channels", ge=1, le=2)
    enabled: bool = Field(default=True, description="Whether source is enabled")
    priority: int = Field(default=100, description="Source priority (lower = higher priority)", ge=0, le=1000)
    description: Optional[str] = Field(None, description="Source description", max_length=500)


class AudioSourceCreate(AudioSourceBase):
    """Schema for creating a new audio source"""
    device_params: Dict[str, Any] = Field(default_factory=dict, description="Device-specific parameters")
    silence_threshold_db: float = Field(default=-60.0, description="Silence detection threshold in dB", ge=-120, le=0)
    silence_duration_seconds: float = Field(default=5.0, description="Silence duration before alert", ge=0, le=3600)
    auto_start: bool = Field(default=False, description="Auto-start on system boot")


class AudioSourceUpdate(BaseModel):
    """Schema for updating an audio source"""
    enabled: Optional[bool] = None
    priority: Optional[int] = Field(None, ge=0, le=1000)
    silence_threshold_db: Optional[float] = Field(None, ge=-120, le=0)
    silence_duration_seconds: Optional[float] = Field(None, ge=0, le=3600)
    auto_start: Optional[bool] = None
    description: Optional[str] = Field(None, max_length=500)


class AudioMetrics(BaseModel):
    """Audio metrics for a source"""
    peak_level_db: float = Field(..., description="Peak audio level in dBFS")
    rms_level_db: float = Field(..., description="RMS audio level in dBFS")
    sample_rate: int = Field(..., description="Current sample rate")
    channels: int = Field(..., description="Number of channels")
    buffer_utilization: float = Field(..., description="Buffer utilization (0-1)", ge=0, le=1)
    frames_captured: int = Field(default=0, description="Total frames captured")
    silence_detected: bool = Field(default=False, description="Whether silence is detected")
    timestamp: datetime = Field(..., description="Metrics timestamp")
    metadata: Optional[Dict[str, Any]] = Field(None, description="Additional metadata")


class AudioSourceResponse(AudioSourceBase):
    """Schema for audio source response"""
    id: str = Field(..., description="Unique source identifier")
    status: str = Field(..., description="Source status (running, stopped, error, etc.)")
    error_message: Optional[str] = Field(None, description="Error message if status is error")
    metrics: Optional[AudioMetrics] = Field(None, description="Current metrics if running")
    icecast_url: Optional[str] = Field(None, description="Icecast streaming URL if available")
    created_at: Optional[datetime] = Field(None, description="Creation timestamp")
    updated_at: Optional[datetime] = Field(None, description="Last update timestamp")

    class Config:
        from_attributes = True  # Enable ORM mode for SQLAlchemy models


class AudioSourceListResponse(BaseModel):
    """Schema for list of audio sources"""
    sources: List[AudioSourceResponse]
    total: int = Field(..., description="Total number of sources")
    active_count: int = Field(default=0, description="Number of active/running sources")


class AudioMetricsResponse(BaseModel):
    """Schema for real-time audio metrics"""
    audio_metrics: Dict[str, Any] = Field(..., description="Current audio metrics snapshot")
    broadcast_stats: Dict[str, Any] = Field(default_factory=dict, description="Broadcast statistics")
    active_source: Optional[str] = Field(None, description="Currently active source name")
    timestamp: datetime = Field(..., description="Metrics timestamp")


class SourceHealthMetrics(BaseModel):
    """Health metrics for a single source"""
    status: str = Field(..., description="Health status (healthy, degraded, failed)")
    uptime_seconds: float = Field(..., description="Source uptime in seconds")
    buffer_fill_percentage: float = Field(..., description="Buffer fill percentage", ge=0, le=100)
    restart_count: int = Field(default=0, description="Number of restarts")
    error_message: Optional[str] = Field(None, description="Error message if unhealthy")
    is_silent: bool = Field(default=False, description="Whether source is silent")


class AudioHealthResponse(BaseModel):
    """Schema for audio system health"""
    overall_health_score: float = Field(..., description="Overall health score (0-100)", ge=0, le=100)
    source_health: Dict[str, SourceHealthMetrics] = Field(..., description="Health metrics per source")
    categorized_sources: Dict[str, List[str]] = Field(..., description="Sources categorized by health")
    active_source: Optional[str] = Field(None, description="Currently active source")
    timestamp: datetime = Field(..., description="Health check timestamp")


class WaveformResponse(BaseModel):
    """Schema for waveform data"""
    waveform: List[float] = Field(..., description="Waveform samples (-1 to 1)")
    sample_count: int = Field(..., description="Number of samples")
    sample_rate: int = Field(..., description="Sample rate")
    timestamp: datetime = Field(..., description="Waveform timestamp")


class SpectrogramResponse(BaseModel):
    """Schema for spectrogram data"""
    spectrogram: List[List[float]] = Field(..., description="2D spectrogram data (time x frequency)")
    frequency_bins: int = Field(..., description="Number of frequency bins")
    time_frames: int = Field(..., description="Number of time frames")
    sample_rate: int = Field(..., description="Sample rate")
    fft_size: int = Field(..., description="FFT size used")
    timestamp: datetime = Field(..., description="Spectrogram timestamp")
