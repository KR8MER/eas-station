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

"""Demod subsystem (FM/AM demodulation, split out of the audio service).

See ``services/demod/__main__.py`` and ``services/demod/worker.py`` for
the rationale and design.
"""

from services.demod.worker import DemodWorker, unpack_audio_envelope

__all__ = [
    "DemodWorker",
    "unpack_audio_envelope",
]
