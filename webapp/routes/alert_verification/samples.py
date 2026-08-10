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

"""The bundled sample recordings offered by the self test."""

from pathlib import Path
from typing import Tuple


DEFAULT_SAMPLE_FILES: Tuple[Path, ...] = (
    Path("samples/ZCZC-EAS-RWT-039137+0015-3042020-KR8MER.wav"),
    Path("samples/ZCZC-EAS-RWT-042001-042071-042133+0300-3040858-WJONTV.wav"),
)
