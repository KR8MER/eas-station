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

"""Formatting helpers for user-facing values."""

from typing import Union
from urllib.parse import urlparse, urlunparse

Number = Union[int, float]


def mask_database_url(url: str) -> str:
    """
    Mask password in a database URL for safe logging.
    
    Args:
        url: Database connection URL (e.g., postgresql://user:pass@host:port/db)
        
    Returns:
        URL with password replaced by '***' (e.g., postgresql://user:***@host:port/db)
        
    Examples:
        >>> mask_database_url('postgresql://user:secret@localhost:5432/db')
        'postgresql://user:***@localhost:5432/db'
        >>> mask_database_url('postgresql://user@localhost:5432/db')
        'postgresql://user@localhost:5432/db'
    """
    try:
        parsed = urlparse(url)
        if parsed.password:
            # Reconstruct URL with masked password
            netloc = f"{parsed.username}:***@{parsed.hostname}"
            if parsed.port:
                netloc += f":{parsed.port}"
            # Use urlunparse with explicit tuple to avoid using private _replace
            return urlunparse((
                parsed.scheme,
                netloc,
                parsed.path,
                parsed.params,
                parsed.query,
                parsed.fragment
            ))
        return url
    except Exception:
        # If parsing fails, return as-is to avoid breaking logging
        return url


def format_bytes(bytes_value: Number) -> str:
    """Format a byte value into a human readable string."""

    if bytes_value == 0:
        return "0 B"

    size_names = ["B", "KB", "MB", "GB", "TB", "PB"]

    import math

    i = int(math.floor(math.log(bytes_value, 1024)))
    p = math.pow(1024, i)
    s = round(bytes_value / p, 2)
    return f"{s} {size_names[i]}"


def format_uptime(seconds: Number) -> str:
    """Format uptime seconds into a human readable string."""

    days = int(seconds // 86400)
    hours = int((seconds % 86400) // 3600)
    minutes = int((seconds % 3600) // 60)

    if days > 0:
        return f"{days}d {hours}h {minutes}m"
    if hours > 0:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"
