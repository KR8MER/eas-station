from __future__ import annotations

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
Centralized Icecast Mount Point Management

This module provides the single source of truth for all Icecast mount point
generation and URL construction. ALL mount point logic must go through here.
"""

import re
from typing import Optional
from enum import Enum


class StreamFormat(Enum):
    """Supported streaming formats."""
    MP3 = "mp3"
    OGG = "ogg"


def sanitize_mount_name(source_name: str) -> str:
    """
    Sanitize a source name for use in mount points.

    - Converts to lowercase
    - Replaces invalid characters with hyphens
    - Removes leading/trailing hyphens
    - Collapses multiple hyphens

    Args:
        source_name: Raw source name

    Returns:
        Sanitized mount name (without extension)
    """
    if not source_name:
        return "stream"

    # Convert to lowercase and replace invalid chars
    sanitized = source_name.lower().strip()

    # Remove existing file extensions
    for ext in ['.mp3', '.ogg', '.wav']:
        if sanitized.endswith(ext):
            sanitized = sanitized[:-len(ext)]

    # Replace invalid characters with hyphens
    sanitized = re.sub(r'[^a-z0-9_-]', '-', sanitized)

    # Remove leading/trailing hyphens
    sanitized = sanitized.strip('-')

    # Collapse multiple hyphens
    sanitized = re.sub(r'-+', '-', sanitized)

    # Ensure we have something
    if not sanitized:
        return "stream"

    return sanitized


def generate_mount_point(source_name: str, format: StreamFormat = StreamFormat.MP3) -> str:
    """
    Generate a complete mount point path for Icecast.

    Mount points MUST include the format extension and leading slash.
    Example: /my-audio-source.mp3

    Args:
        source_name: Source name to convert to mount point
        format: Stream format (default: MP3)

    Returns:
        Complete mount point path with leading slash and extension
    """
    sanitized = sanitize_mount_name(source_name)
    extension = format.value
    return f"/{sanitized}.{extension}"


def build_stream_url(
    hostname: str,
    port: int,
    source_name: str,
    format: StreamFormat = StreamFormat.MP3,
    use_https: bool = False
) -> str:
    """
    Build a complete Icecast stream URL.

    Args:
        hostname: Icecast server hostname or IP
        port: Icecast server port
        source_name: Audio source name
        format: Stream format (default: MP3)
        use_https: Use HTTPS instead of HTTP (default: False)

    Returns:
        Complete stream URL

    Example:
        >>> build_stream_url('icecast', 8001, 'noaa-weather')
        'http://icecast:8001/noaa-weather.mp3'
    """
    protocol = "https" if use_https else "http"
    mount_point = generate_mount_point(source_name, format)
    # Remove leading slash since we'll add it in the URL
    mount_path = mount_point.lstrip('/')
    return f"{protocol}://{hostname}:{port}/{mount_path}"


def extract_source_name_from_mount(mount_point: str) -> str:
    """
    Extract the original source name from a mount point.

    Args:
        mount_point: Mount point path (with or without leading slash)

    Returns:
        Source name without extension or slashes

    Example:
        >>> extract_source_name_from_mount('/my-source.mp3')
        'my-source'
        >>> extract_source_name_from_mount('another-source.ogg')
        'another-source'
    """
    # Remove leading slash
    mount = mount_point.lstrip('/')

    # Remove extension
    for ext in ['.mp3', '.ogg', '.wav']:
        if mount.endswith(ext):
            mount = mount[:-len(ext)]
            break

    return mount


def validate_mount_point(mount_point: str) -> tuple[bool, Optional[str]]:
    """
    Validate that a mount point follows Icecast requirements.

    Args:
        mount_point: Mount point to validate

    Returns:
        Tuple of (is_valid, error_message)

    Example:
        >>> validate_mount_point('/stream.mp3')
        (True, None)
        >>> validate_mount_point('no-leading-slash')
        (False, 'Mount point must start with /')
    """
    if not mount_point:
        return False, "Mount point cannot be empty"

    if not mount_point.startswith('/'):
        return False, "Mount point must start with /"

    # Check for valid extension
    valid_extensions = ['.mp3', '.ogg']
    has_valid_extension = any(mount_point.endswith(ext) for ext in valid_extensions)

    if not has_valid_extension:
        return False, f"Mount point must end with one of: {', '.join(valid_extensions)}"

    # Check for invalid characters (after the leading slash)
    mount_without_slash = mount_point[1:]
    if not re.match(r'^[a-z0-9_-]+\.(mp3|ogg)$', mount_without_slash):
        return False, "Mount point contains invalid characters (use only a-z, 0-9, -, _)"

    return True, None


__all__ = [
    'StreamFormat',
    'sanitize_mount_name',
    'generate_mount_point',
    'build_stream_url',
    'extract_source_name_from_mount',
    'validate_mount_point',
]
