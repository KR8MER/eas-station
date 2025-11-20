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

from __future__ import annotations

"""
Audio stream analysis for codec and bitrate detection.

Parses frame headers from MP3, AAC, and Ogg streams to automatically
detect codec parameters without relying on HTTP headers.
"""

import logging
from typing import Optional, Dict, Tuple
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class StreamInfo:
    """Detected stream information from frame analysis."""
    codec: Optional[str] = None  # mp3, aac, ogg, etc.
    bitrate_kbps: Optional[int] = None  # Bitrate in kbps
    sample_rate: Optional[int] = None  # Sample rate in Hz
    channels: Optional[int] = None  # Number of channels
    codec_version: Optional[str] = None  # e.g., "MPEG-1 Layer III"
    is_vbr: bool = False  # Variable bitrate flag


class MP3FrameAnalyzer:
    """Analyze MP3 frame headers to detect bitrate and other parameters."""

    # MPEG-1 Layer III bitrate table (kbps)
    MPEG1_LAYER3_BITRATES = [
        0, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320, 0
    ]

    # MPEG-2 Layer III bitrate table (kbps)
    MPEG2_LAYER3_BITRATES = [
        0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160, 0
    ]

    # Sample rate table
    MPEG1_SAMPLE_RATES = [44100, 48000, 32000, 0]
    MPEG2_SAMPLE_RATES = [22050, 24000, 16000, 0]
    MPEG25_SAMPLE_RATES = [11025, 12000, 8000, 0]

    def __init__(self):
        self.detected_bitrates = []  # Track bitrates to detect VBR
        self.frame_count = 0

    def analyze_buffer(self, buffer: bytearray) -> Optional[StreamInfo]:
        """
        Analyze buffer to find and parse MP3 frames.

        Args:
            buffer: Audio data buffer

        Returns:
            StreamInfo if valid MP3 frames found, None otherwise
        """
        if len(buffer) < 4:
            return None

        # Find frame sync
        sync_pos = self._find_frame_sync(buffer)
        if sync_pos == -1:
            return None

        # Parse frame header
        if sync_pos + 4 > len(buffer):
            return None

        header = buffer[sync_pos:sync_pos + 4]
        return self._parse_frame_header(bytes(header))

    def _find_frame_sync(self, buffer: bytearray) -> int:
        """Find MP3 frame sync pattern (11 bits set to 1)."""
        for i in range(len(buffer) - 1):
            if buffer[i] == 0xFF and (buffer[i + 1] & 0xE0) == 0xE0:
                return i
        return -1

    def _parse_frame_header(self, header: bytes) -> Optional[StreamInfo]:
        """
        Parse a 4-byte MP3 frame header.

        Frame header format (32 bits):
        - 11 bits: Frame sync (all set)
        - 2 bits: MPEG version
        - 2 bits: Layer
        - 1 bit: Protection
        - 4 bits: Bitrate index
        - 2 bits: Sample rate index
        - 1 bit: Padding
        - 1 bit: Private
        - 2 bits: Channel mode
        - 2 bits: Mode extension
        - 1 bit: Copyright
        - 1 bit: Original
        - 2 bits: Emphasis
        """
        if len(header) < 4:
            return None

        # Check sync bits
        if header[0] != 0xFF or (header[1] & 0xE0) != 0xE0:
            return None

        # Parse version
        version_bits = (header[1] >> 3) & 0x03
        if version_bits == 0:  # MPEG 2.5
            mpeg_version = "MPEG-2.5"
            sample_rates = self.MPEG25_SAMPLE_RATES
            bitrate_table = self.MPEG2_LAYER3_BITRATES
        elif version_bits == 2:  # MPEG 2
            mpeg_version = "MPEG-2"
            sample_rates = self.MPEG2_SAMPLE_RATES
            bitrate_table = self.MPEG2_LAYER3_BITRATES
        elif version_bits == 3:  # MPEG 1
            mpeg_version = "MPEG-1"
            sample_rates = self.MPEG1_SAMPLE_RATES
            bitrate_table = self.MPEG1_LAYER3_BITRATES
        else:
            return None

        # Parse layer
        layer_bits = (header[1] >> 1) & 0x03
        if layer_bits == 1:
            layer = "Layer III"
        elif layer_bits == 2:
            layer = "Layer II"
        elif layer_bits == 3:
            layer = "Layer I"
        else:
            return None

        # Parse bitrate
        bitrate_index = (header[2] >> 4) & 0x0F
        if bitrate_index == 0 or bitrate_index == 15:
            # Free format or invalid
            return None
        bitrate_kbps = bitrate_table[bitrate_index]

        # Parse sample rate
        sample_rate_index = (header[2] >> 2) & 0x03
        if sample_rate_index == 3:
            return None
        sample_rate = sample_rates[sample_rate_index]

        # Parse channel mode
        channel_mode = (header[3] >> 6) & 0x03
        if channel_mode == 3:
            channels = 1  # Mono
        else:
            channels = 2  # Stereo, Joint Stereo, or Dual Channel

        # Track bitrates to detect VBR
        self.detected_bitrates.append(bitrate_kbps)
        self.frame_count += 1

        # Detect VBR if we've seen multiple different bitrates
        is_vbr = False
        if len(self.detected_bitrates) > 5:
            unique_bitrates = set(self.detected_bitrates[-10:])
            if len(unique_bitrates) > 1:
                is_vbr = True
                # For VBR, report average
                bitrate_kbps = sum(self.detected_bitrates[-10:]) // len(self.detected_bitrates[-10:])

        return StreamInfo(
            codec='mp3',
            bitrate_kbps=bitrate_kbps,
            sample_rate=sample_rate,
            channels=channels,
            codec_version=f"{mpeg_version} {layer}",
            is_vbr=is_vbr
        )


class AACFrameAnalyzer:
    """Analyze AAC ADTS frame headers."""

    # AAC sample rate table
    SAMPLE_RATES = [
        96000, 88200, 64000, 48000, 44100, 32000, 24000, 22050,
        16000, 12000, 11025, 8000, 7350, 0, 0, 0
    ]

    def analyze_buffer(self, buffer: bytearray) -> Optional[StreamInfo]:
        """
        Analyze buffer to find and parse AAC ADTS frames.

        Args:
            buffer: Audio data buffer

        Returns:
            StreamInfo if valid AAC frames found, None otherwise
        """
        if len(buffer) < 7:
            return None

        # Find ADTS sync
        sync_pos = self._find_adts_sync(buffer)
        if sync_pos == -1:
            return None

        if sync_pos + 7 > len(buffer):
            return None

        header = buffer[sync_pos:sync_pos + 7]
        return self._parse_adts_header(bytes(header))

    def _find_adts_sync(self, buffer: bytearray) -> int:
        """Find ADTS sync pattern (0xFFF)."""
        for i in range(len(buffer) - 1):
            if buffer[i] == 0xFF and (buffer[i + 1] & 0xF0) == 0xF0:
                return i
        return -1

    def _parse_adts_header(self, header: bytes) -> Optional[StreamInfo]:
        """
        Parse a 7-byte AAC ADTS header.

        ADTS header format:
        - 12 bits: Sync (0xFFF)
        - 1 bit: MPEG version (0=MPEG-4, 1=MPEG-2)
        - 2 bits: Layer (always 00)
        - 1 bit: Protection absent
        - 2 bits: Profile
        - 4 bits: Sample rate index
        - 1 bit: Private
        - 3 bits: Channel configuration
        - ...
        """
        if len(header) < 7:
            return None

        # Check sync
        if header[0] != 0xFF or (header[1] & 0xF0) != 0xF0:
            return None

        # MPEG version
        mpeg_version = "MPEG-4" if (header[1] & 0x08) == 0 else "MPEG-2"

        # Profile
        profile = (header[2] >> 6) & 0x03
        profile_names = ["Main", "LC", "SSR", "LTP"]
        profile_name = profile_names[profile] if profile < 4 else "Unknown"

        # Sample rate
        sample_rate_index = (header[2] >> 2) & 0x0F
        if sample_rate_index >= len(self.SAMPLE_RATES):
            return None
        sample_rate = self.SAMPLE_RATES[sample_rate_index]

        # Channel configuration
        channel_config = ((header[2] & 0x01) << 2) | ((header[3] >> 6) & 0x03)

        # Frame length (used to estimate bitrate)
        frame_length = ((header[3] & 0x03) << 11) | (header[4] << 3) | ((header[5] >> 5) & 0x07)

        # Estimate bitrate: bitrate = (frame_length * 8 * sample_rate) / 1024
        if sample_rate > 0:
            bitrate_kbps = (frame_length * 8 * sample_rate) // (1024 * 1000)
        else:
            bitrate_kbps = None

        return StreamInfo(
            codec='aac',
            bitrate_kbps=bitrate_kbps,
            sample_rate=sample_rate,
            channels=channel_config if channel_config > 0 else 2,
            codec_version=f"{mpeg_version} AAC-{profile_name}",
            is_vbr=False  # AAC is typically CBR in ADTS
        )


class OggStreamAnalyzer:
    """Analyze Ogg Vorbis stream headers."""

    def analyze_buffer(self, buffer: bytearray) -> Optional[StreamInfo]:
        """
        Analyze buffer to find and parse Ogg page headers.

        Args:
            buffer: Audio data buffer

        Returns:
            StreamInfo if valid Ogg stream found, None otherwise
        """
        if len(buffer) < 27:
            return None

        # Look for Ogg page header
        if buffer[:4] != b'OggS':
            # Search for OggS magic
            ogg_pos = buffer.find(b'OggS')
            if ogg_pos == -1:
                return None
            buffer = buffer[ogg_pos:]

        if len(buffer) < 27:
            return None

        # This is a simplified parser - full Vorbis identification header
        # parsing would require more extensive work
        return StreamInfo(
            codec='ogg',
            codec_version='Ogg Vorbis',
            # Bitrate detection for Ogg requires parsing identification header
            # which is more complex - return None for now
            bitrate_kbps=None,
            sample_rate=None,
            channels=None,
            is_vbr=True  # Vorbis is typically VBR
        )


def analyze_stream(buffer: bytearray, hint_codec: Optional[str] = None) -> Optional[StreamInfo]:
    """
    Analyze audio stream buffer to detect codec and parameters.

    Args:
        buffer: Audio data buffer
        hint_codec: Optional codec hint from Content-Type header

    Returns:
        StreamInfo with detected parameters, or None if detection failed
    """
    if len(buffer) < 4:
        return None

    # Try analyzers based on hint or in order
    if hint_codec == 'mp3' or hint_codec is None:
        analyzer = MP3FrameAnalyzer()
        info = analyzer.analyze_buffer(buffer)
        if info:
            return info

    if hint_codec == 'aac' or hint_codec is None:
        analyzer = AACFrameAnalyzer()
        info = analyzer.analyze_buffer(buffer)
        if info:
            return info

    if hint_codec == 'ogg' or hint_codec is None:
        analyzer = OggStreamAnalyzer()
        info = analyzer.analyze_buffer(buffer)
        if info:
            return info

    return None
