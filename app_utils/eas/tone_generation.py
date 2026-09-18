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

"""Synthesizing attention-tone and MDC1200 selective-calling sample buffers.

The alert-attention chime (bell/beep/three-tone/QC-II/DTMF/MDC1200) lives in
``chime.py``, not here -- it was split out separately to stay under the
400-line guidance."""

import math
from typing import Iterable, List, Optional

from ..eas_fsk import (
    SAME_BAUD,
    SAME_MARK_FREQ,
    SAME_SPACE_FREQ,
    encode_terminator_bits,
    generate_fsk_samples,
)



def _generate_tone(freqs: Iterable[float], duration: float, sample_rate: int, amplitude: float) -> List[int]:
    total_samples = max(1, int(duration * sample_rate))
    freqs = list(freqs)
    samples: List[int] = []
    for n in range(total_samples):
        t = n / sample_rate
        value = sum(math.sin(2 * math.pi * freq * t) for freq in freqs)
        value /= max(len(freqs), 1)
        samples.append(int(value * amplitude))
    return samples




def _generate_silence(duration: float, sample_rate: int) -> List[int]:
    return [0] * max(1, int(duration * sample_rate))




# Allowed chime profile values for pre/post-alert chimes.
ALERT_CHIME_PROFILES = ('none', 'bell', 'beep', 'three_tone', 'qc2', 'dtmf', 'mdc1200')



# Silence inserted between the EOM sequence and the post-alert signal (chime /
# MDC1200 PTT-ID).  A 1.0 s gap separates the End-of-Message from the
# post-alert signaling, matching the standard 1.0 s end-of-message tail that
# is emitted when no post-alert signal follows.
POST_ALERT_SIGNAL_GAP_SECONDS = 1.0




def _resolve_mdc1200_op_for_position(op_code: str, position: str) -> str:
    """Auto-pair MDC1200 PTT-ID Pre/Post when used as bookend chimes.

    When an operator selects ``ptt_id_pre`` (the default) for both pre- and
    post-alert MDC1200 chimes, a real Motorola subscriber radio expects the
    post-side packet to be ``ptt_id_post`` — the bookend pair is what closes
    the call cleanly on the receiver's display.  This helper substitutes the
    matching post-side preset automatically so operators don't have to think
    about it.

    The substitution is intentionally narrow:

    * ``position='post'`` AND ``op_code == 'ptt_id_pre'``  →  ``'ptt_id_post'``

    All other presets (``emergency``, ``request_to_talk``, ``remote_monitor``,
    ``ptt_id_post`` already chosen, or ``custom``) pass through unchanged so
    operators who deliberately want the same op-code on both sides — for
    example sandwiching a broadcast in two emergency-alarm packets — keep
    that behaviour.
    """
    if (position or '').strip().lower() == 'post' and (op_code or '').strip().lower() == 'ptt_id_pre':
        return 'ptt_id_post'
    return op_code




def _mdc1200_meta_target_unit_id(
    op_code: Optional[str],
    op_code_raw: Optional[int],
    arg_raw: Optional[int],
    target_unit_id: Optional[int],
) -> Optional[int]:
    """Return the target unit ID to advertise in signaling metadata, or ``None``.

    The target unit ID is only carried on the wire by the **double-packet**
    ops (Call Alert / Selective Call) — see ``MDC1200_DOUBLE_PACKET_OPS`` and
    ``generate_mdc1200_samples``.  Single-packet ops (PTT-ID Pre/Post,
    Emergency, Request-to-Talk, Remote Monitor) have no destination field, so
    the encoder silently ignores any configured target.

    This mirrors that behaviour for the UI / PDF / log: a target is only
    surfaced when the resolved op-code actually transmits one.  Without this
    gate the manual-activation page advertised a phantom destination (for
    example ``PTT-ID → 65535`` / ``0xFFFF``) that never goes on air, which
    misled operators into thinking PTT-ID had a destination.

    Raw op/arg bytes (the ``custom`` preset) take precedence over the named
    preset, matching the op/arg resolution in :func:`_generate_chime`.
    """
    from app_utils.mdc1200 import is_double_packet_op, resolve_op_preset

    if op_code_raw is not None and arg_raw is not None:
        try:
            op = int(op_code_raw) & 0xFF
            arg = int(arg_raw) & 0xFF
        except (TypeError, ValueError):
            op, arg = resolve_op_preset(op_code or '')
    else:
        op, arg = resolve_op_preset(op_code or '')

    if not is_double_packet_op(op, arg):
        return None
    if target_unit_id in (None, 0):
        return None
    try:
        return int(target_unit_id)
    except (TypeError, ValueError):
        return None












def _generate_station_terminator_samples(amplitude: float, sample_rate: int) -> List[int]:
    """Generate the KR8MER EAS Station FSK fingerprint: 3 × 0xA9 terminator bytes.

    0xA9 (10101001 binary) is not used by any known ENDEC hardware.  EAS-Tools
    only recognises 0x00 and 0xFF, so third-party decoders gracefully exit
    post-message mode on the first 0xA9 byte (the message is already fully
    decoded).  Our own decoder captures the run and reports ENDEC_MODE_EAS_STATION.
    """
    bits = encode_terminator_bits(0xA9, 3)
    return generate_fsk_samples(
        bits,
        sample_rate=sample_rate,
        bit_rate=float(SAME_BAUD),
        mark_freq=SAME_MARK_FREQ,
        space_freq=SAME_SPACE_FREQ,
        amplitude=amplitude,
    )




def _normalize_audio_amplitude(samples: List[int], target_amplitude: float) -> List[int]:
    """Normalize audio samples to match the target amplitude using RMS.

    This ensures TTS audio has the same perceived loudness as SAME/AFSK tones.
    Uses RMS (Root Mean Square) normalization which better represents perceived
    loudness compared to peak normalization.
    """
    if not samples:
        return samples

    # Calculate RMS (Root Mean Square) of the input samples
    sum_squares = sum(s * s for s in samples)
    rms = math.sqrt(sum_squares / len(samples))

    # Avoid division by zero
    if rms == 0:
        return samples

    # For sine wave tones (SAME/attention), RMS ≈ peak / sqrt(2)
    # So target RMS should be target_amplitude / sqrt(2)
    target_rms = target_amplitude / math.sqrt(2)

    # Calculate the scaling factor needed to reach target RMS
    scale = target_rms / rms

    # Speech has a much higher peak-to-RMS ratio (crest factor) than the sine
    # tones this function was modeled on, so a pure RMS match can drive
    # transients (sibilants, plosives) well past full scale. Cap the gain so
    # the loudest sample in this clip lands at or under full scale instead of
    # hard-clipping; loudness then falls a bit short of target_rms only for
    # unusually peaky source audio.
    peak = max(abs(s) for s in samples)
    if peak > 0:
        scale = min(scale, 32767 / peak)

    # Apply scaling to all samples
    # Clamp to prevent overflow beyond int16 range
    return [max(-32768, min(32767, int(s * scale))) for s in samples]
