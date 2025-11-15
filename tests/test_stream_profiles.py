"""
Tests for Stream Profile Management

Tests the stream profile configuration system including:
- Profile creation and validation
- Profile manager operations
- Bandwidth estimation
- FFmpeg argument generation
"""

import json
import tempfile
from pathlib import Path

import pytest

from app_core.audio.stream_profiles import (
    StreamProfile,
    StreamProfileManager,
    StreamFormat,
    StreamQuality,
)


class TestStreamProfile:
    """Test StreamProfile dataclass."""
    
    def test_create_valid_profile(self):
        """Test creating a valid stream profile."""
        profile = StreamProfile(
            name="test",
            mount="/test.mp3",
            format="mp3",
            bitrate=128
        )
        
        assert profile.name == "test"
        assert profile.mount == "/test.mp3"
        assert profile.format == "mp3"
        assert profile.bitrate == 128
        assert profile.sample_rate == 44100
        assert profile.channels == 2
        assert profile.enabled is True
    
    def test_mount_auto_slash(self):
        """Test mount point gets leading slash added."""
        profile = StreamProfile(
            name="test",
            mount="test.mp3",  # No leading slash
            format="mp3",
            bitrate=128
        )
        
        assert profile.mount == "/test.mp3"
    
    def test_invalid_bitrate(self):
        """Test that invalid bitrate raises error."""
        with pytest.raises(ValueError, match="Bitrate.*out of range"):
            StreamProfile(
                name="test",
                mount="/test.mp3",
                format="mp3",
                bitrate=500  # Too high
            )
        
        with pytest.raises(ValueError, match="Bitrate.*out of range"):
            StreamProfile(
                name="test",
                mount="/test.mp3",
                format="mp3",
                bitrate=16  # Too low
            )
    
    def test_invalid_sample_rate(self):
        """Test that invalid sample rate raises error."""
        with pytest.raises(ValueError, match="Invalid sample rate"):
            StreamProfile(
                name="test",
                mount="/test.mp3",
                format="mp3",
                bitrate=128,
                sample_rate=12345  # Invalid
            )
    
    def test_invalid_channels(self):
        """Test that invalid channel count raises error."""
        with pytest.raises(ValueError, match="Invalid channel count"):
            StreamProfile(
                name="test",
                mount="/test.mp3",
                format="mp3",
                bitrate=128,
                channels=5  # Invalid
            )
    
    def test_to_dict(self):
        """Test serialization to dictionary."""
        profile = StreamProfile(
            name="test",
            mount="/test.mp3",
            format="mp3",
            bitrate=128,
            description="Test stream"
        )
        
        data = profile.to_dict()
        
        assert isinstance(data, dict)
        assert data["name"] == "test"
        assert data["mount"] == "/test.mp3"
        assert data["format"] == "mp3"
        assert data["bitrate"] == 128
        assert data["description"] == "Test stream"
    
    def test_from_dict(self):
        """Test deserialization from dictionary."""
        data = {
            "name": "test",
            "mount": "/test.mp3",
            "format": "mp3",
            "bitrate": 128,
            "sample_rate": 44100,
            "channels": 2,
            "description": "Test stream",
            "genre": "Emergency",
            "public": False,
            "enabled": True,
            "fallback_mount": None,
            "max_listeners": 100,
            "burst_size": 65535
        }
        
        profile = StreamProfile.from_dict(data)
        
        assert profile.name == "test"
        assert profile.mount == "/test.mp3"
        assert profile.bitrate == 128
    
    def test_get_ffmpeg_args_mp3(self):
        """Test FFmpeg argument generation for MP3."""
        profile = StreamProfile(
            name="test",
            mount="/test.mp3",
            format="mp3",
            bitrate=128,
            sample_rate=44100,
            channels=2
        )
        
        args = profile.get_ffmpeg_audio_args()
        
        assert "-codec:a" in args
        assert "libmp3lame" in args
        assert "-b:a" in args
        assert "128k" in args
        assert "-ar" in args
        assert "44100" in args
        assert "-ac" in args
        assert "2" in args
    
    def test_get_ffmpeg_args_ogg(self):
        """Test FFmpeg argument generation for OGG Vorbis."""
        profile = StreamProfile(
            name="test",
            mount="/test.ogg",
            format="ogg",
            bitrate=96
        )
        
        args = profile.get_ffmpeg_audio_args()
        
        assert "libvorbis" in args
        assert "96k" in args
    
    def test_bandwidth_estimate(self):
        """Test bandwidth estimation."""
        profile = StreamProfile(
            name="test",
            mount="/test.mp3",
            format="mp3",
            bitrate=128
        )
        
        # Estimate for 1 hour
        mb_per_hour = profile.estimate_bandwidth(3600)
        
        # 128 kbps for 3600 seconds
        # = 128 * 1000 * 3600 bits
        # = 460,800,000 bits
        # = 57,600,000 bytes
        # = 54.93 MB
        assert 54 < mb_per_hour < 56
        
        # Estimate for 1 minute
        mb_per_minute = profile.estimate_bandwidth(60)
        assert 0.9 < mb_per_minute < 1.0


class TestStreamProfileManager:
    """Test StreamProfileManager."""
    
    def test_create_manager(self):
        """Test creating manager with temp directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = StreamProfileManager(profiles_dir=Path(tmpdir))
            
            # Should create default profiles
            profiles = manager.get_all_profiles()
            assert len(profiles) > 0
    
    def test_save_and_load_profile(self):
        """Test saving and loading a profile."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = StreamProfileManager(profiles_dir=Path(tmpdir))
            
            profile = StreamProfile(
                name="custom",
                mount="/custom.mp3",
                format="mp3",
                bitrate=192
            )
            
            # Save profile
            assert manager.save_profile(profile) is True
            
            # Load it back
            loaded = manager.get_profile("custom")
            assert loaded is not None
            assert loaded.name == "custom"
            assert loaded.bitrate == 192
    
    def test_save_profile_duplicate_mount(self):
        """Test that duplicate mount points are rejected."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = StreamProfileManager(profiles_dir=Path(tmpdir))
            
            profile1 = StreamProfile(
                name="profile1",
                mount="/test.mp3",
                format="mp3",
                bitrate=128
            )
            
            profile2 = StreamProfile(
                name="profile2",
                mount="/test.mp3",  # Same mount
                format="mp3",
                bitrate=192
            )
            
            # First should succeed
            assert manager.save_profile(profile1) is True
            
            # Second should fail (duplicate mount)
            assert manager.save_profile(profile2) is False
    
    def test_delete_profile(self):
        """Test deleting a profile."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = StreamProfileManager(profiles_dir=Path(tmpdir))
            
            profile = StreamProfile(
                name="temp",
                mount="/temp.mp3",
                format="mp3",
                bitrate=64
            )
            
            manager.save_profile(profile)
            assert manager.get_profile("temp") is not None
            
            # Delete it
            assert manager.delete_profile("temp") is True
            assert manager.get_profile("temp") is None
            
            # Try deleting again (should fail)
            assert manager.delete_profile("temp") is False
    
    def test_enable_disable_profile(self):
        """Test enabling and disabling profiles."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = StreamProfileManager(profiles_dir=Path(tmpdir))
            
            profile = StreamProfile(
                name="toggle",
                mount="/toggle.mp3",
                format="mp3",
                bitrate=128,
                enabled=True
            )
            
            manager.save_profile(profile)
            
            # Disable it
            assert manager.disable_profile("toggle") is True
            profile = manager.get_profile("toggle")
            assert profile.enabled is False
            
            # Enable it
            assert manager.enable_profile("toggle") is True
            profile = manager.get_profile("toggle")
            assert profile.enabled is True
    
    def test_get_active_profiles(self):
        """Test getting only active profiles."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = StreamProfileManager(profiles_dir=Path(tmpdir))
            
            # Create some profiles
            active = StreamProfile(
                name="active",
                mount="/active.mp3",
                format="mp3",
                bitrate=128,
                enabled=True
            )
            
            inactive = StreamProfile(
                name="inactive",
                mount="/inactive.mp3",
                format="mp3",
                bitrate=128,
                enabled=False
            )
            
            manager.save_profile(active)
            manager.save_profile(inactive)
            
            # Get active only
            active_profiles = manager.get_active_profiles()
            active_names = [p.name for p in active_profiles]
            
            # Should include default profiles that are enabled plus our active one
            assert "active" in active_names
            assert "inactive" not in active_names
    
    def test_create_from_preset(self):
        """Test creating profile from quality preset."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = StreamProfileManager(profiles_dir=Path(tmpdir))
            
            # Create low quality profile
            profile = manager.create_profile_from_preset(
                name="low-test",
                quality=StreamQuality.LOW
            )
            
            assert profile.name == "low-test"
            assert profile.bitrate == 64
            assert profile.channels == 1  # Mono for low quality
            assert profile.mount == "/low.mp3"
            
            # Create high quality profile
            profile = manager.create_profile_from_preset(
                name="high-test",
                quality=StreamQuality.HIGH,
                mount="/custom-high.mp3"
            )
            
            assert profile.bitrate == 192
            assert profile.channels == 2  # Stereo for high quality
            assert profile.mount == "/custom-high.mp3"
    
    def test_bandwidth_estimate(self):
        """Test total bandwidth estimation."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = StreamProfileManager(profiles_dir=Path(tmpdir))
            
            # Clear defaults and add known profiles
            for name in list(manager.get_all_profiles().keys()):
                manager.delete_profile(name)
            
            # Add two active profiles
            profile1 = StreamProfile(
                name="p1",
                mount="/p1.mp3",
                format="mp3",
                bitrate=64,
                enabled=True
            )
            
            profile2 = StreamProfile(
                name="p2",
                mount="/p2.mp3",
                format="mp3",
                bitrate=128,
                enabled=True
            )
            
            manager.save_profile(profile1)
            manager.save_profile(profile2)
            
            # Total should be sum of both
            total = manager.get_total_bandwidth_estimate(3600)
            
            # 64 kbps + 128 kbps = 192 kbps
            # For 1 hour = ~82 MB
            assert 80 < total < 85
    
    def test_persistence(self):
        """Test that profiles persist across manager instances."""
        with tempfile.TemporaryDirectory() as tmpdir:
            profiles_dir = Path(tmpdir)
            
            # Create manager and add profile
            manager1 = StreamProfileManager(profiles_dir=profiles_dir)
            profile = StreamProfile(
                name="persist-test",
                mount="/persist.mp3",
                format="mp3",
                bitrate=128
            )
            manager1.save_profile(profile)
            
            # Create new manager instance
            manager2 = StreamProfileManager(profiles_dir=profiles_dir)
            
            # Should load the saved profile
            loaded = manager2.get_profile("persist-test")
            assert loaded is not None
            assert loaded.bitrate == 128


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
