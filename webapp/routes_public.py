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

"""Backwards-compatible shim for the public route surface.

The implementation now lives in the webapp.public package, one module per
surface.  This module is kept so existing imports — notably the route-module
registry in webapp/__init__.py — keep resolving unchanged.
"""

from webapp.public import register

__all__ = ["register"]
