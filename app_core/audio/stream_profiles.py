"""
Stream Profile Configuration for Icecast

Manages multiple streaming profiles with different bitrates, formats, and quality settings.
Allows operators to configure:
- Multiple stream endpoints (e.g., low/medium/high quality)
- Different formats (MP3, OGG)
- Per-source encoding profiles
- Adaptive bitrate strategies

Usage:
    from app_core.audio.stream_profiles import StreamProfileManager, StreamProfile
    
    manager = StreamProfileManager()
    
    # Create profiles
    low_quality = StreamProfile(
        name="low-quality",
        format="mp3",
        bitrate=64,
        mount="/low.mp3"
    )
    
    high_quality = StreamProfile(
        name="high-quality",
        format="mp3",
        bitrate=320,
        mount="/high.mp3"
    )
    
    # Save profiles
    manager.save_profile(low_quality)
    manager.save_profile(high_quality)
    
    # Get active profiles
    profiles = manager.get_active_profiles()
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# Default profiles directory
DEFAULT_PROFILES_DIR = Path("/app-config/stream-profiles")


class StreamFormat(Enum):
    """Supported streaming formats."""
    MP3 = "mp3"
    OGG_VORBIS = "ogg"
    OPUS = "opus"
    AAC = "aac"


class StreamQuality(Enum):
    """Predefined quality presets."""
    LOW = "low"         # 64 kbps - Low bandwidth
    MEDIUM = "medium"   # 128 kbps - Standard quality
    HIGH = "high"       # 192 kbps - High quality
    PREMIUM = "premium" # 320 kbps - Maximum quality


@dataclass
class StreamProfile:
    """
    Configuration for a single stream profile.
    
    Defines encoding parameters for an Icecast stream endpoint.
    """
    # Identity
    name: str
    mount: str  # Mount point (e.g., "/high.mp3")
    
    # Encoding
    format: str  # "mp3", "ogg", "opus", "aac"
    bitrate: int  # kbps (e.g., 64, 128, 192, 320)
    
    # Audio settings
    sample_rate: int = 44100  # Hz
    channels: int = 2  # 1 = mono, 2 = stereo
    
    # Metadata
    description: Optional[str] = None
    genre: str = "Emergency Alert"
    public: bool = False  # Publicly listed
    
    # Behavior
    enabled: bool = True
    fallback_mount: Optional[str] = None  # Fallback stream if this fails
    
    # Advanced
    max_listeners: int = 100
    burst_size: int = 65535  # Bytes sent to new listeners
    
    def __post_init__(self):
        """Validate profile configuration."""
        if self.bitrate < 32 or self.bitrate > 320:
            raise ValueError(f"Bitrate {self.bitrate} kbps out of range (32-320)")
        
        if self.sample_rate not in [8000, 16000, 22050, 32000, 44100, 48000]:
            raise ValueError(f"Invalid sample rate {self.sample_rate} Hz")
        
        if self.channels not in [1, 2]:
            raise ValueError(f"Invalid channel count {self.channels}")
        
        if not self.mount.startswith("/"):
            self.mount = "/" + self.mount
    
    def to_dict(self) -> Dict:
        """Convert to dictionary for serialization."""
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict) -> StreamProfile:
        """Create from dictionary."""
        return cls(**data)
    
    def get_ffmpeg_audio_args(self) -> List[str]:
        """
        Generate FFmpeg audio encoding arguments for this profile.
        
        Returns:
            List of FFmpeg command-line arguments
        """
        args = []
        
        # Audio codec and bitrate
        if self.format == "mp3":
            args.extend(["-codec:a", "libmp3lame"])
            args.extend(["-b:a", f"{self.bitrate}k"])
            args.extend(["-q:a", "2"])  # VBR quality
        
        elif self.format == "ogg":
            args.extend(["-codec:a", "libvorbis"])
            args.extend(["-b:a", f"{self.bitrate}k"])
        
        elif self.format == "opus":
            args.extend(["-codec:a", "libopus"])
            args.extend(["-b:a", f"{self.bitrate}k"])
            args.extend(["-vbr", "on"])
        
        elif self.format == "aac":
            args.extend(["-codec:a", "aac"])
            args.extend(["-b:a", f"{self.bitrate}k"])
        
        # Sample rate
        args.extend(["-ar", str(self.sample_rate)])
        
        # Channels
        args.extend(["-ac", str(self.channels)])
        
        return args
    
    def estimate_bandwidth(self, duration_seconds: int = 3600) -> float:
        """
        Estimate bandwidth usage in MB for given duration.
        
        Args:
            duration_seconds: Duration to estimate (default 1 hour)
        
        Returns:
            Estimated MB of data
        """
        bits_per_second = self.bitrate * 1000
        total_bits = bits_per_second * duration_seconds
        total_mb = total_bits / (8 * 1024 * 1024)
        return round(total_mb, 2)


class StreamProfileManager:
    """
    Manages stream profile configurations.
    
    Handles loading, saving, and validating stream profiles.
    """
    
    def __init__(self, profiles_dir: Optional[Path] = None):
        """
        Initialize profile manager.
        
        Args:
            profiles_dir: Directory for profile storage (default: /app-config/stream-profiles)
        """
        self.profiles_dir = profiles_dir or DEFAULT_PROFILES_DIR
        self.profiles_dir.mkdir(parents=True, exist_ok=True)
        self.profiles_file = self.profiles_dir / "profiles.json"
        
        # In-memory cache
        self._profiles: Dict[str, StreamProfile] = {}
        
        # Load existing profiles
        self._load_profiles()
    
    def _load_profiles(self):
        """Load profiles from disk."""
        if not self.profiles_file.exists():
            logger.info("No existing stream profiles found, using defaults")
            self._create_default_profiles()
            return
        
        try:
            with open(self.profiles_file, 'r') as f:
                data = json.load(f)
            
            for name, profile_data in data.items():
                try:
                    profile = StreamProfile.from_dict(profile_data)
                    self._profiles[name] = profile
                except Exception as e:
                    logger.error(f"Failed to load profile '{name}': {e}")
            
            logger.info(f"Loaded {len(self._profiles)} stream profile(s)")
        
        except Exception as e:
            logger.error(f"Failed to load stream profiles: {e}")
            self._create_default_profiles()
    
    def _save_profiles(self):
        """Save profiles to disk."""
        try:
            data = {name: profile.to_dict() for name, profile in self._profiles.items()}
            
            with open(self.profiles_file, 'w') as f:
                json.dump(data, f, indent=2)
            
            logger.debug(f"Saved {len(self._profiles)} stream profile(s)")
        
        except Exception as e:
            logger.error(f"Failed to save stream profiles: {e}")
    
    def _create_default_profiles(self):
        """Create default stream profiles."""
        defaults = [
            StreamProfile(
                name="standard",
                mount="/stream.mp3",
                format="mp3",
                bitrate=128,
                description="Standard quality monitoring stream",
                enabled=True
            ),
            StreamProfile(
                name="low-bandwidth",
                mount="/low.mp3",
                format="mp3",
                bitrate=64,
                channels=1,  # Mono for lower bandwidth
                description="Low bandwidth stream for remote monitoring",
                enabled=False
            ),
            StreamProfile(
                name="high-quality",
                mount="/high.mp3",
                format="mp3",
                bitrate=192,
                description="High quality stream for production monitoring",
                enabled=False
            ),
        ]
        
        for profile in defaults:
            self._profiles[profile.name] = profile
        
        self._save_profiles()
        logger.info(f"Created {len(defaults)} default stream profile(s)")
    
    def get_profile(self, name: str) -> Optional[StreamProfile]:
        """Get a profile by name."""
        return self._profiles.get(name)
    
    def get_all_profiles(self) -> Dict[str, StreamProfile]:
        """Get all profiles."""
        return self._profiles.copy()
    
    def get_active_profiles(self) -> List[StreamProfile]:
        """Get all enabled profiles."""
        return [p for p in self._profiles.values() if p.enabled]
    
    def save_profile(self, profile: StreamProfile) -> bool:
        """
        Save or update a profile.
        
        Args:
            profile: Profile to save
        
        Returns:
            True if successful
        """
        try:
            # Validate mount point uniqueness
            for existing_name, existing_profile in self._profiles.items():
                if existing_name != profile.name and existing_profile.mount == profile.mount:
                    logger.error(
                        f"Mount point '{profile.mount}' already used by profile '{existing_name}'"
                    )
                    return False
            
            self._profiles[profile.name] = profile
            self._save_profiles()
            logger.info(f"Saved stream profile '{profile.name}'")
            return True
        
        except Exception as e:
            logger.error(f"Failed to save profile '{profile.name}': {e}")
            return False
    
    def delete_profile(self, name: str) -> bool:
        """
        Delete a profile.
        
        Args:
            name: Profile name to delete
        
        Returns:
            True if successful
        """
        if name not in self._profiles:
            logger.warning(f"Profile '{name}' not found")
            return False
        
        try:
            del self._profiles[name]
            self._save_profiles()
            logger.info(f"Deleted stream profile '{name}'")
            return True
        
        except Exception as e:
            logger.error(f"Failed to delete profile '{name}': {e}")
            return False
    
    def enable_profile(self, name: str) -> bool:
        """Enable a profile."""
        profile = self.get_profile(name)
        if not profile:
            return False
        
        profile.enabled = True
        return self.save_profile(profile)
    
    def disable_profile(self, name: str) -> bool:
        """Disable a profile."""
        profile = self.get_profile(name)
        if not profile:
            return False
        
        profile.enabled = False
        return self.save_profile(profile)
    
    def create_profile_from_preset(
        self, 
        name: str, 
        quality: StreamQuality,
        mount: Optional[str] = None
    ) -> StreamProfile:
        """
        Create a profile from a quality preset.
        
        Args:
            name: Profile name
            quality: Quality preset
            mount: Mount point (auto-generated if not provided)
        
        Returns:
            New StreamProfile instance
        """
        quality_settings = {
            StreamQuality.LOW: {"bitrate": 64, "channels": 1},
            StreamQuality.MEDIUM: {"bitrate": 128, "channels": 2},
            StreamQuality.HIGH: {"bitrate": 192, "channels": 2},
            StreamQuality.PREMIUM: {"bitrate": 320, "channels": 2},
        }
        
        settings = quality_settings[quality]
        
        if not mount:
            mount = f"/{quality.value}.mp3"
        
        return StreamProfile(
            name=name,
            mount=mount,
            format="mp3",
            bitrate=settings["bitrate"],
            channels=settings["channels"],
            description=f"{quality.value.title()} quality stream",
        )
    
    def get_total_bandwidth_estimate(self, duration_seconds: int = 3600) -> float:
        """
        Estimate total bandwidth for all active profiles.
        
        Args:
            duration_seconds: Duration to estimate (default 1 hour)
        
        Returns:
            Total estimated MB
        """
        total = 0.0
        for profile in self.get_active_profiles():
            total += profile.estimate_bandwidth(duration_seconds)
        return round(total, 2)


# Convenience function to get singleton instance
_manager_instance: Optional[StreamProfileManager] = None


def get_stream_profile_manager() -> StreamProfileManager:
    """Get the global StreamProfileManager instance."""
    global _manager_instance
    if _manager_instance is None:
        _manager_instance = StreamProfileManager()
    return _manager_instance


__all__ = [
    "StreamProfile",
    "StreamProfileManager",
    "StreamFormat",
    "StreamQuality",
    "get_stream_profile_manager",
]
