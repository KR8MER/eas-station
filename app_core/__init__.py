"""Core application modules for the NOAA alerts system."""

# The package exposes commonly used symbols so callers can import from
# ``app_core`` without having to know the concrete module layout.

from .extensions import db  # noqa: F401
from . import models  # noqa: F401

__all__ = [
    "db",
    "models",
]
