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

"""
Audio demodulation for SDR receivers.

Supports FM (wideband and narrowband), AM, and includes stereo decoding and RBDS extraction.

The implementation lives in the :mod:`app_core.radio.demod` package - see its
docstring for the module layout. This module stays as a re-export shim so the
long-standing ``from app_core.radio.demodulation import ...`` import path keeps
working; import from ``app_core.radio.demod`` in new code.
"""

import logging

from app_core.radio.demod import (  # noqa: F401  (re-exported for compatibility)
    AMDemodulator,
    DemodulatorConfig,
    DemodulatorStatus,
    FMDemodulator,
    RBDSData,
    RBDSDecoder,
    RBDSDecoderStats,
    RBDSWorker,
    RBDS_LANGUAGE_CODES,
    RT_PLUS_AID,
    RT_PLUS_CONTENT_TYPES,
    StreamingResampler,
    create_demodulator,
    design_fir_bandpass,
    design_fir_lowpass,
    fast_decimate,
    fm_discriminator,
    fm_discriminator_declick,
    pi_to_call_sign,
    resample_to,
)

# Private names that pre-package callers reach for. ``webapp/routes_monitoring``
# imports ``_NUMBA_AVAILABLE`` to report JIT availability on the diagnostics
# page; the rest are kept so nothing that patched them by name breaks.
from app_core.radio.demod.kernels import (  # noqa: F401
    _NUMBA_AVAILABLE,
    _RBDS_SYNDROMES,
    _calc_syndrome_numba,
    _costas_loop_numba,
    _fm_discriminator_declick_numba,
    _fm_discriminator_numba,
    _mm_timing_loop_numba,
    _presync_scan_numba,
)
from app_core.radio.demod.rbds_constants import (  # noqa: F401
    _NRSC4_THREE_LETTER_CALLSIGNS,
)
from app_core.radio.demod.rbds_decoder import _CONFIRM_UNSET  # noqa: F401

logger = logging.getLogger(__name__)

__all__ = [
    'AMDemodulator',
    'DemodulatorConfig',
    'DemodulatorStatus',
    'FMDemodulator',
    'RBDSData',
    'RBDSDecoder',
    'RBDSDecoderStats',
    'RBDSWorker',
    'RBDS_LANGUAGE_CODES',
    'RT_PLUS_AID',
    'RT_PLUS_CONTENT_TYPES',
    'StreamingResampler',
    'create_demodulator',
    'design_fir_bandpass',
    'design_fir_lowpass',
    'fast_decimate',
    'fm_discriminator',
    'fm_discriminator_declick',
    'pi_to_call_sign',
    'resample_to',
]
