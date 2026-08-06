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

"""Demodulator factory - maps a modulation type onto a demodulator class."""


from app_core.radio.demod.types import (
    DemodulatorConfig,
)
from app_core.radio.demod.fm import FMDemodulator
from app_core.radio.demod.am import AMDemodulator


def create_demodulator(config: DemodulatorConfig):
    """Factory function to create the appropriate demodulator."""
    # Normalize modulation type to uppercase for consistent comparison
    mod_type = config.modulation_type.upper()

    if mod_type in ('FM', 'WFM', 'NFM'):
        return FMDemodulator(config)
    elif mod_type == 'AM':
        return AMDemodulator(config)
    elif mod_type == 'IQ':
        # No demodulation, return raw IQ
        return None
    else:
        raise ValueError(
            f"Unsupported modulation type: {config.modulation_type}. "
            f"Valid types: FM, WFM, NFM, AM, IQ"
        )
