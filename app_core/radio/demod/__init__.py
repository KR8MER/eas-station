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

Supports FM (wideband and narrowband), AM, and includes stereo decoding and
RBDS extraction.

This package was split out of the former single-file
``app_core/radio/demodulation.py``. The layering is strictly one-directional:

    kernels          Numba JIT hot-path kernels (no package deps)
    rbds_constants   RT+/RBDS reference tables, PI -> call sign
    types            configuration, status and RBDS payload dataclasses
    dsp              -> kernels
    rbds_decoder     -> rbds_constants, types
    rbds_worker      -> kernels, dsp, types, rbds_decoder
    fm               -> dsp, types, rbds_worker
    am               -> dsp, types
    factory          -> types, fm, am

``app_core.radio.demodulation`` remains as a re-export shim, so existing
``from app_core.radio.demodulation import FMDemodulator`` imports keep working.
"""

# The private kernel names are re-exported deliberately: they are not part of
# __all__, but `app_core.radio.demodulation` and callers that predate the
# package split reach for them by name (webapp/routes_monitoring reads
# _NUMBA_AVAILABLE for the diagnostics page).
from .kernels import (  # noqa: F401
    _NUMBA_AVAILABLE,
    _RBDS_SYNDROMES,
    _calc_syndrome_numba,
    _costas_loop_numba,
    _fm_discriminator_declick_numba,
    _fm_discriminator_numba,
    _mm_timing_loop_numba,
    _presync_scan_numba,
    jit,
    prange,
)
from .dsp import (
    StreamingResampler,
    design_fir_bandpass,
    design_fir_lowpass,
    fast_decimate,
    fm_discriminator,
    fm_discriminator_declick,
    resample_to,
)
from .rbds_constants import (
    RBDS_LANGUAGE_CODES,
    RT_PLUS_AID,
    RT_PLUS_CONTENT_TYPES,
    pi_to_call_sign,
)
from .types import (
    DemodulatorConfig,
    DemodulatorStatus,
    RBDSData,
    RBDSDecoderStats,
)
from .rbds_decoder import RBDSDecoder
from .rbds_worker import RBDSWorker
from .fm import FMDemodulator
from .am import AMDemodulator
from .factory import create_demodulator

__all__ = [
    # Configuration and payload types
    'DemodulatorConfig',
    'DemodulatorStatus',
    'RBDSData',
    'RBDSDecoderStats',
    # Demodulators
    'AMDemodulator',
    'FMDemodulator',
    'create_demodulator',
    # RBDS
    'RBDSDecoder',
    'RBDSWorker',
    'RBDS_LANGUAGE_CODES',
    'RT_PLUS_AID',
    'RT_PLUS_CONTENT_TYPES',
    'pi_to_call_sign',
    # DSP helpers
    'StreamingResampler',
    'design_fir_bandpass',
    'design_fir_lowpass',
    'fast_decimate',
    'fm_discriminator',
    'fm_discriminator_declick',
    'resample_to',
]
