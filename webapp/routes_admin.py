"""Compatibility wrapper re-exporting admin route registration helpers."""

from __future__ import annotations

from .admin import calculate_coverage_percentages, register

__all__ = ['calculate_coverage_percentages', 'register']
