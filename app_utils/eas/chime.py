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

"""Alert-attention chime synthesis: bell/beep/three-tone/QC-II/DTMF/MDC1200."""

import math
from typing import Dict, List, Optional, Tuple

from ..eas_fsk import apply_edge_ramp, apply_low_pass_filter

# Standard DTMF tone-pair frequency map: digit -> (low Hz, high Hz).
# Source: ITU-T Recommendation Q.23 / Q.24.
_DTMF_FREQUENCIES: Dict[str, Tuple[float, float]] = {
    '1': (697.0, 1209.0), '2': (697.0, 1336.0), '3': (697.0, 1477.0), 'A': (697.0, 1633.0),
    '4': (770.0, 1209.0), '5': (770.0, 1336.0), '6': (770.0, 1477.0), 'B': (770.0, 1633.0),
    '7': (852.0, 1209.0), '8': (852.0, 1336.0), '9': (852.0, 1477.0), 'C': (852.0, 1633.0),
    '*': (941.0, 1209.0), '0': (941.0, 1336.0), '#': (941.0, 1477.0), 'D': (941.0, 1633.0),
}


def _generate_chime(
    profile: Optional[str],
    duration: float,
    sample_rate: int,
    amplitude: float,
    qc2_tone_a_freq: float = 1000.0,
    qc2_tone_b_freq: float = 1500.0,
    dtmf_sequence: str = '',
    qc2_long_tone_enabled: bool = False,
    qc2_long_tone_seconds: float = 10.0,
    mdc1200_op_code: str = 'ptt_id_pre',
    mdc1200_op_code_raw: Optional[int] = None,
    mdc1200_arg_raw: Optional[int] = None,
    mdc1200_unit_id: int = 1,
    mdc1200_target_unit_id: Optional[int] = None,
) -> List[int]:
    """Generate a short attention chime to play before/after an EAS broadcast.

    The chime is *not* part of the SAME/FSK signaling and is purely cosmetic —
    it is inserted before the first SAME header burst (pre-alert) or after the
    final EOM sequence (post-alert) when the operator has configured one.

    Supported profiles:
        - 'none' / 'off' / falsy: returns an empty list (no audio).
        - 'bell':       single 880 Hz sine with exponential decay envelope.
        - 'beep':       sustained 1000 Hz sine for the full duration.
        - 'three_tone': three ascending tones (440, 880, 1320 Hz),
                        each occupying ~1/3 of the duration.
        - 'qc2':        Motorola Quick Call II two-tone paging — fixed
                        1 s Tone A (``qc2_tone_a_freq``) followed by
                        4 s Tone B (``qc2_tone_b_freq``), 5 s total.
                        ``duration`` is ignored to keep timing on-spec.
                        When ``qc2_long_tone_enabled`` is ``True``, an
                        additional steady tone at ``qc2_tone_b_freq`` is
                        appended for ``qc2_long_tone_seconds`` seconds.
        - 'dtmf':       Plays each character of ``dtmf_sequence`` (digits
                        0-9, letters A-D, * or #) as its standard DTMF
                        low+high tone pair, using ITU-T Q.24 timing
                        (100 ms tone, 50 ms gap).  ``duration`` is ignored.
        - 'mdc1200':    Motorola MDC1200 selective-calling FFSK packet at
                        1200 baud (mark = 1200 Hz, space = 1800 Hz).
                        Encodes ``mdc1200_unit_id`` with the op-code
                        derived from ``mdc1200_op_code`` (or the explicit
                        ``mdc1200_op_code_raw`` / ``mdc1200_arg_raw``
                        overrides).  ``duration`` is ignored — packet
                        timing is fixed by the protocol (~147 ms).

    Args:
        profile: Chime profile name (case-insensitive).
        duration: Total duration in seconds (clamped to 0.1–10.0).
            Ignored when ``profile`` is ``'dtmf'`` or ``'qc2'`` — both use
            standardized fixed timings.
        sample_rate: Output sample rate in Hz.
        amplitude: Peak signed-int amplitude (e.g. 0.7 * 32767).
        qc2_tone_a_freq: Tone A frequency in Hz when ``profile == 'qc2'``.
        qc2_tone_b_freq: Tone B frequency in Hz when ``profile == 'qc2'``.
        dtmf_sequence: Digit string when ``profile == 'dtmf'``.  Unrecognised
            characters are ignored.  Limited to the first 32 valid digits.
        qc2_long_tone_enabled: When ``True`` and ``profile == 'qc2'``, a
            sustained tone at ``qc2_tone_b_freq`` is appended after the
            standard A + B sequence.
        qc2_long_tone_seconds: Duration in seconds for the optional QC-II
            long tone (clamped to 1.0–120.0).  Ignored when
            ``qc2_long_tone_enabled`` is ``False``.

    Returns:
        A list of int16-range PCM samples, or an empty list when disabled.
    """
    if not profile:
        return []
    name = str(profile).strip().lower()
    if name in ('', 'none', 'off', 'omit', 'disabled'):
        return []

    # DTMF has its own timing and ignores `duration`.
    if name == 'dtmf':
        digits = [c for c in str(dtmf_sequence or '').upper() if c in _DTMF_FREQUENCIES]
        if not digits:
            return []
        digits = digits[:32]
        # ITU-T Q.24 minimum: 70 ms tone / 65 ms gap.  We use the slightly
        # more conservative 100 ms tone / 50 ms gap commonly emitted by
        # commercial dialers for clean detection.
        tone_samples = max(1, int(0.10 * sample_rate))
        gap_samples = max(1, int(0.05 * sample_rate))
        # Sum of two unit-amplitude sines can reach 2.0; scale by 0.5 so the
        # combined waveform never exceeds the supplied peak amplitude.
        per_tone_amp = amplitude * 0.5
        out: List[int] = []
        for idx, digit in enumerate(digits):
            f_low, f_high = _DTMF_FREQUENCIES[digit]
            digit_samples: List[int] = []
            for n in range(tone_samples):
                t = n / sample_rate
                value = (
                    math.sin(2 * math.pi * f_low * t)
                    + math.sin(2 * math.pi * f_high * t)
                )
                digit_samples.append(int(value * per_tone_amp))
            out.extend(apply_edge_ramp(apply_low_pass_filter(digit_samples, sample_rate), sample_rate))
            if idx < len(digits) - 1:
                out.extend([0] * gap_samples)
        return out

    try:
        duration = float(duration)
    except (TypeError, ValueError):
        duration = 2.0
    duration = max(0.1, min(10.0, duration))

    total_samples = max(1, int(duration * sample_rate))
    samples: List[int] = []

    if name == 'beep':
        freq = 1000.0
        for n in range(total_samples):
            t = n / sample_rate
            samples.append(int(math.sin(2 * math.pi * freq * t) * amplitude))
        return apply_edge_ramp(apply_low_pass_filter(samples, sample_rate), sample_rate)

    if name == 'bell':
        # 880 Hz sine with an exponential amplitude decay (-decay_rate * t).
        # Decay rate is tuned so a 2 s chime fades to ~5% of peak amplitude.
        freq = 880.0
        decay_rate = 3.0
        for n in range(total_samples):
            t = n / sample_rate
            envelope = math.exp(-decay_rate * t)
            samples.append(int(math.sin(2 * math.pi * freq * t) * envelope * amplitude))
        return apply_edge_ramp(apply_low_pass_filter(samples, sample_rate), sample_rate)

    if name in ('three_tone', 'threetone', '3tone', '3_tone'):
        freqs = (440.0, 880.0, 1320.0)
        per_tone = max(1, total_samples // len(freqs))
        for idx, freq in enumerate(freqs):
            # Last tone absorbs any rounding remainder so the total length matches.
            tone_len = per_tone if idx < len(freqs) - 1 else (total_samples - per_tone * (len(freqs) - 1))
            tone_len = max(1, tone_len)
            segment: List[int] = []
            for n in range(tone_len):
                t = n / sample_rate
                segment.append(int(math.sin(2 * math.pi * freq * t) * amplitude))
            # Filtered and ramped per-segment (not just at the ends of the whole
            # chime) so the 440->880->1320 Hz jumps between tones don't
            # themselves click.
            samples.extend(apply_edge_ramp(apply_low_pass_filter(segment, sample_rate), sample_rate))
        return samples

    if name in ('qc2', 'qcii', 'quickcall', 'quick_call', 'two_tone'):
        # Motorola Quick Call II is a standardized two-tone paging protocol
        # with fixed timing: 1 s Tone A followed by 4 s Tone B (5 s total).
        # `duration` is intentionally ignored — pagers time against the
        # absolute 1 s / 4 s segments, so any other ratio produces a
        # non-spec signal that real receivers may refuse to decode.
        try:
            freq_a = float(qc2_tone_a_freq)
        except (TypeError, ValueError):
            freq_a = 1000.0
        try:
            freq_b = float(qc2_tone_b_freq)
        except (TypeError, ValueError):
            freq_b = 1500.0
        freq_a = max(50.0, min(4000.0, freq_a))
        freq_b = max(50.0, min(4000.0, freq_b))

        a_samples = max(1, int(1.0 * sample_rate))
        b_samples = max(1, int(4.0 * sample_rate))
        tone_a: List[int] = []
        for n in range(a_samples):
            t = n / sample_rate
            tone_a.append(int(math.sin(2 * math.pi * freq_a * t) * amplitude))
        tone_b: List[int] = []
        for n in range(b_samples):
            t = n / sample_rate
            tone_b.append(int(math.sin(2 * math.pi * freq_b * t) * amplitude))
        # Filtered and ramped individually so the Tone A -> Tone B handoff
        # doesn't click.
        out: List[int] = (
            apply_edge_ramp(apply_low_pass_filter(tone_a, sample_rate), sample_rate)
            + apply_edge_ramp(apply_low_pass_filter(tone_b, sample_rate), sample_rate)
        )

        # Optional long tone: a sustained steady tone at Tone B frequency
        # appended after the standard A + B sequence.
        if qc2_long_tone_enabled:
            try:
                long_secs = float(qc2_long_tone_seconds)
            except (TypeError, ValueError):
                long_secs = 10.0
            long_secs = max(1.0, min(120.0, long_secs))
            long_samples = max(1, int(long_secs * sample_rate))
            long_tone: List[int] = []
            for n in range(long_samples):
                t = n / sample_rate
                long_tone.append(int(math.sin(2 * math.pi * freq_b * t) * amplitude))
            out.extend(apply_edge_ramp(apply_low_pass_filter(long_tone, sample_rate), sample_rate))

        return out

    if name in ('mdc1200', 'mdc-1200', 'mdc'):
        # Motorola MDC1200 selective-calling FFSK packet (1200 baud,
        # 1200 Hz mark / 1800 Hz space).  Packet timing is fixed by the
        # protocol so `duration` is intentionally ignored.
        from app_utils.mdc1200 import (
            generate_mdc1200_samples,
            resolve_op_preset,
        )
        try:
            unit_id_int = int(mdc1200_unit_id)
        except (TypeError, ValueError):
            unit_id_int = 1
        unit_id_int = max(1, min(0xFFFF, unit_id_int))

        if mdc1200_op_code_raw is not None and mdc1200_arg_raw is not None:
            try:
                op = int(mdc1200_op_code_raw) & 0xFF
                arg = int(mdc1200_arg_raw) & 0xFF
            except (TypeError, ValueError):
                op, arg = resolve_op_preset(mdc1200_op_code or '')
        else:
            op, arg = resolve_op_preset(mdc1200_op_code or '')

        # Coerce the target unit ID; ``None``, blank string, or out-of-range
        # values force single-packet emission (the encoder treats 0/None as
        # "no target configured").
        target_int: Optional[int] = None
        if mdc1200_target_unit_id not in (None, ''):
            try:
                _t = int(mdc1200_target_unit_id)
            except (TypeError, ValueError):
                _t = 0
            if 1 <= _t <= 0xFFFF:
                target_int = _t

        return apply_edge_ramp(
            apply_low_pass_filter(
                generate_mdc1200_samples(
                    opcode=op,
                    arg=arg,
                    unit_id=unit_id_int,
                    sample_rate=sample_rate,
                    amplitude=amplitude,
                    target_unit_id=target_int,
                ),
                sample_rate,
            ),
            sample_rate,
        )

    # Unknown profile: be safe and emit no chime rather than raise.
    return []
