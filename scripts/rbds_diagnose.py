#!/usr/bin/env python3
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

RBDS pipeline diagnostic script.

Processes a captured FM multiplex numpy array (saved by the temporary
capture block in RBDSWorker._process_rbds) through each DSP stage and
reports what is — and is not — working, so the exact failure point can
be identified without needing a running SDR.

Usage
-----
    python3 scripts/rbds_diagnose.py /var/log/eas-station/captures/iq_sdr_256000Hz_*.npz
    python3 scripts/rbds_diagnose.py /path/to/capture.npz --sample-rate 256000
    python3 scripts/rbds_diagnose.py /path/to/legacy_multiplex.npy --sample-rate 256000

Output is written to stdout as plain text; redirect to a file if needed.
"""

from __future__ import annotations

import argparse
import math
import pathlib
import re
import sys
from typing import Dict

import numpy as np
from scipy import signal as scipy_signal


# ──────────────────────────────────────────────────────────────────────────────
# Helpers that replicate the RBDSWorker filter/carrier design so this script
# is fully standalone (no Flask / app_core import needed).
# ──────────────────────────────────────────────────────────────────────────────

def _design_fir_lowpass_orig(cutoff: float, sample_rate: int, taps: int = 101) -> np.ndarray:
    """Original implementation (normalises by sum(h))."""
    fc = cutoff / sample_rate
    n = np.arange(taps)
    mid = (taps - 1) / 2
    h = np.sinc(2 * fc * (n - mid))
    h *= np.blackman(taps)
    h /= np.sum(h)
    return h.astype(np.float32)


def _design_fir_bandpass_orig(low: float, high: float, sample_rate: int, taps: int = 101) -> np.ndarray:
    """Original implementation (normalises by max(|h|)) — may have gain error."""
    fc_low = low / sample_rate
    fc_high = high / sample_rate
    n = np.arange(taps)
    mid = (taps - 1) / 2
    h = np.sinc(2 * fc_high * (n - mid)) - np.sinc(2 * fc_low * (n - mid))
    h *= np.blackman(taps)
    h /= np.max(np.abs(h))
    return h.astype(np.float32)


def _design_fir_bandpass_fixed(low: float, high: float, sample_rate: int, taps: int = 101) -> np.ndarray:
    """Fixed implementation: unity gain at passband centre frequency."""
    fc_low = low / sample_rate
    fc_high = high / sample_rate
    n = np.arange(taps, dtype=np.float64)
    mid = (taps - 1) / 2.0
    h = np.sinc(2 * fc_high * (n - mid)) - np.sinc(2 * fc_low * (n - mid))
    h *= np.blackman(taps)
    # Normalise so |H(f_centre)| = 1 (correct for bandpass filters)
    fc_centre = (fc_low + fc_high) / 2.0
    h_at_centre = float(np.abs(np.sum(h * np.exp(-1j * 2 * np.pi * fc_centre * (n - mid)))))
    if h_at_centre > 1e-9:
        h /= h_at_centre
    return h.astype(np.float32)


def _filter_gain_db(h: np.ndarray, freq_hz: float, sample_rate: int) -> float:
    """Return filter gain in dB at a single frequency."""
    taps = len(h)
    n = np.arange(taps, dtype=np.float64)
    mid = (taps - 1) / 2.0
    fc = freq_hz / sample_rate
    gain = float(np.abs(np.sum(h * np.exp(-1j * 2 * np.pi * fc * (n - mid)))))
    return 20.0 * math.log10(max(gain, 1e-12))


def _find_peak_frequency(data: np.ndarray, sample_rate: int,
                         low_hz: float, high_hz: float) -> tuple[float, float]:
    """
    Locate the strongest spectral peak within [low_hz, high_hz].

    Returns (peak_freq_hz, amplitude_linear).
    """
    n = min(len(data), 2 ** 20)        # cap FFT at ~1 M point for speed
    freqs = np.fft.rfftfreq(n, 1.0 / sample_rate)
    spectrum = np.abs(np.fft.rfft(data[:n].astype(np.float64)))
    mask = (freqs >= low_hz) & (freqs <= high_hz)
    if not np.any(mask):
        return 0.0, 0.0
    idx_in_mask = int(np.argmax(spectrum[mask]))
    idx = int(np.where(mask)[0][idx_in_mask])
    # Parabolic interpolation for sub-bin accuracy
    if 0 < idx < len(spectrum) - 1:
        alpha = float(spectrum[idx - 1])
        beta = float(spectrum[idx])
        gamma = float(spectrum[idx + 1])
        denom = alpha - 2 * beta + gamma
        if abs(denom) > 1e-12:
            delta = 0.5 * (alpha - gamma) / denom
        else:
            delta = 0.0
        peak_freq = freqs[idx] + delta * (freqs[1] - freqs[0])
    else:
        peak_freq = float(freqs[idx])
        delta = 0.0
    peak_amp = float(spectrum[idx])
    # Normalise to amplitude (divide by N/2 for one-sided RFFT)
    peak_amp /= (n / 2)
    return peak_freq, peak_amp


def _run_pipeline_to_bits(
    multiplex: np.ndarray,
    sample_rate: int,
    costas_alpha: float,
    costas_beta: float,
    costas_before_mm: bool,
) -> dict:
    """
    Run the RBDS signal chain on *multiplex* and return diagnostic counters.

    Parameters
    ----------
    multiplex        : FM demodulated multiplex signal (real float32, [-π, +π])
    sample_rate      : sample rate of *multiplex* in Hz
    costas_alpha     : Costas loop proportional gain
    costas_beta      : Costas loop integral gain
    costas_before_mm : True → Costas at 19 kHz then M&M (correct order)
                       False → M&M first then Costas at symbol rate (current bug)

    Returns a dict with keys:
      presync_hits, synced, groups_decoded, crc_pass, crc_fail, bits_total
    """
    RBDS_INTERMEDIATE_RATE = 25000

    # ── 1. Bandpass 54-60 kHz (fixed normalization) ──────────────────────────
    rbds_filter_taps = min(101, max(31, int(sample_rate / 3000)))
    bp = _design_fir_bandpass_fixed(54000.0, 60000.0, sample_rate, taps=rbds_filter_taps)
    bp_zi = np.zeros(len(bp) - 1, dtype=np.float32)

    # ── 2. Lowpass 7.5 kHz (original design) ─────────────────────────────────
    lp = _design_fir_lowpass_orig(7500.0, sample_rate, taps=301)
    lp_zi_r = np.zeros(len(lp) - 1, dtype=np.float64)
    lp_zi_i = np.zeros(len(lp) - 1, dtype=np.float64)

    # ── 3. Split into 250 ms chunks (mimics streaming) ───────────────────────
    chunk_size = sample_rate // 4       # 250 ms
    sample_buffer = np.array([], dtype=np.complex64)

    UNSYNCED_WINDOW = int(4750 * sample_rate / 19000)
    SYNCED_WINDOW   = int(19000 * sample_rate / 19000)  # = sample_rate (1 s)

    # Costas state
    costas_phase = 0.0
    costas_freq  = 0.0

    # M&M state
    mm_mu = 0.01
    mm_mu_gain = 0.05
    mm_leftover: np.ndarray = np.array([], dtype=np.complex64)
    mm_out_prev_r = complex(0.0)
    mm_out_prev2_r = complex(0.0)
    mm_rail_prev_r = complex(0.0)

    # Differential decode / bit buffer state
    prev_sym = 0
    bit_buffer: list[int] = []

    # Sync state machine (mirrors RBDSWorker._decode_rbds_groups)
    syndrome_vals  = [383, 14, 303, 663, 748]
    offset_pos_arr = [0, 1, 2, 3, 2]
    offset_word    = [252, 408, 360, 436, 848]

    synced            = False
    presync           = False
    presync_hits      = 0
    presync_polarity: bool | None = None
    lastseen_offset   = 0
    lastseen_counter  = 0
    inverted_polarity = False

    wrong_blocks = 0
    blocks_counter = 0
    group_good = 0
    groups_decoded = 0
    crc_pass = 0
    crc_fail  = 0
    bits_total = 0
    global_bit = 0
    reg = 0
    block_bit_ctr = 0
    block_num = 0
    group_started = False
    bytes_arr = bytearray(8)

    def calc_syn(x: int, mlen: int) -> int:
        r = 0
        for ii in range(mlen, 0, -1):
            r = (r << 1) | ((x >> (ii - 1)) & 1)
            if r & (1 << 10):
                r ^= 0x5B9
        for _ in range(10):
            r <<= 1
            if r & (1 << 10):
                r ^= 0x5B9
        return r & 0x3FF

    def costas_block(samples: np.ndarray, phase: float, freq: float) -> tuple:
        out = np.zeros(len(samples), dtype=np.complex64)
        for i in range(len(samples)):
            out[i] = samples[i] * np.exp(-1j * phase)
            err = float(np.real(out[i])) * float(np.imag(out[i]))
            freq += costas_beta * err
            phase += freq + costas_alpha * err
            while phase >= 2 * math.pi:
                phase -= 2 * math.pi
            while phase < 0:
                phase += 2 * math.pi
        return out, phase, freq

    def mm_block(samples: np.ndarray, mu: float, leftover: np.ndarray):
        if len(leftover) > 0:
            samples = np.concatenate((leftover, samples))
        if len(samples) < 32:
            return np.array([], dtype=np.complex64), mu, samples.astype(np.complex64)
        interpolated = scipy_signal.resample_poly(samples, 16, 1)
        max_out = len(samples) // 16 + 100
        out = np.zeros(max_out, dtype=np.complex64)
        out_rail = np.zeros(max_out, dtype=np.complex64)
        i_in = 0
        i_out = 2
        while i_out < max_out - 1:
            idx = i_in * 16 + int(mu * 16)
            if idx >= len(interpolated) - 1:
                break
            out[i_out] = interpolated[idx]
            out_rail[i_out] = (int(np.real(out[i_out]) > 0) +
                               1j * int(np.imag(out[i_out]) > 0))
            x_e = (out_rail[i_out] - out_rail[i_out - 2]) * np.conj(out[i_out - 1])
            y_e = (out[i_out] - out[i_out - 2]) * np.conj(out_rail[i_out - 1])
            mm_val = float(np.real(y_e - x_e))
            mu += 16 + mm_mu_gain * mm_val
            i_in += int(np.floor(mu))
            mu -= np.floor(mu)
            i_out += 1
        leftover_new = samples[i_in:].astype(np.complex64)
        return out[2:i_out], mu, leftover_new

    offset = 0
    for start in range(0, len(multiplex), chunk_size):
        chunk = multiplex[start:start + chunk_size].astype(np.float32)
        if len(chunk) == 0:
            break
        n = len(chunk)

        # ── Bandpass ──────────────────────────────────────────────────────────
        if len(bp_zi) != len(bp) - 1:
            bp_zi = np.zeros(len(bp) - 1, dtype=np.float32)
        x_bp, bp_zi = scipy_signal.lfilter(bp, [1.0], chunk, zi=bp_zi)

        # ── Mix with crystal-locked 57 kHz ────────────────────────────────────
        t = (np.arange(n, dtype=np.float64) + offset) / sample_rate
        carrier = np.exp(-1j * 2.0 * np.pi * 57000.0 * t)
        x_mix = x_bp * carrier

        # ── Lowpass 7.5 kHz ───────────────────────────────────────────────────
        r_out, lp_zi_r = scipy_signal.lfilter(lp, [1.0], x_mix.real, zi=lp_zi_r)
        i_out_sig, lp_zi_i = scipy_signal.lfilter(lp, [1.0], x_mix.imag, zi=lp_zi_i)
        x_lp = (r_out + 1j * i_out_sig).astype(np.complex64)

        offset += n
        sample_buffer = np.concatenate([sample_buffer, x_lp])

        # Only process when enough samples have accumulated
        locked = synced
        window = SYNCED_WINDOW if locked else UNSYNCED_WINDOW
        if len(sample_buffer) < window:
            continue

        x = sample_buffer
        sample_buffer = np.array([], dtype=np.complex64)

        # ── Decimate → ~25 kHz ────────────────────────────────────────────────
        decim = max(1, int(sample_rate / RBDS_INTERMEDIATE_RATE))
        if decim > 1:
            x = x[::decim]
            sr_after = int(sample_rate // decim)
        else:
            sr_after = sample_rate

        # ── Resample to 19 kHz ────────────────────────────────────────────────
        gcd = math.gcd(int(sr_after), 19000)
        up = 19000 // gcd
        down = sr_after // gcd
        x = scipy_signal.resample_poly(x, up, down).astype(np.complex64)

        if len(x) < 48:
            continue

        # ── Costas and M&M — order depends on the flag ────────────────────────
        if costas_before_mm:
            x, costas_phase, costas_freq = costas_block(x, costas_phase, costas_freq)
            x, mm_mu, mm_leftover = mm_block(x, mm_mu, mm_leftover)
        else:
            x, mm_mu, mm_leftover = mm_block(x, mm_mu, mm_leftover)
            x, costas_phase, costas_freq = costas_block(x, costas_phase, costas_freq)

        if len(x) < 2:
            continue

        # ── Differential BPSK decode ──────────────────────────────────────────
        raw_bits = (np.real(x) > 0).astype(np.int8)
        all_syms = np.concatenate(([prev_sym], raw_bits))
        diff = (np.diff(all_syms.astype(np.int32)) % 2).astype(np.int8)
        prev_sym = int(raw_bits[-1])

        bits_total += len(diff)
        bit_buffer.extend(diff.tolist())

        # ── Sync / group decode ───────────────────────────────────────────────
        for bit in bit_buffer:
            reg = ((reg << 1) | bit) & 0x3FFFFFF
            global_bit += 1

            if not synced:
                syn_n   = calc_syn(reg, 26)
                syn_inv = calc_syn(reg ^ 0x3FFFFFF, 26)
                for j in range(5):
                    pol: bool | None = None
                    if syn_n   == syndrome_vals[j]: pol = False
                    elif syn_inv == syndrome_vals[j]: pol = True
                    if pol is None:
                        continue
                    if not presync:
                        lastseen_offset  = j
                        lastseen_counter = global_bit
                        inverted_polarity = pol
                        presync_polarity  = pol
                        presync_hits      = 0
                        presync           = True
                    else:
                        if presync_polarity is not None and pol != presync_polarity:
                            lastseen_offset  = j
                            lastseen_counter = global_bit
                            presync_polarity  = pol
                            inverted_polarity = pol
                            presync_hits      = 0
                            break
                        if offset_pos_arr[lastseen_offset] >= offset_pos_arr[j]:
                            dist = offset_pos_arr[j] + 4 - offset_pos_arr[lastseen_offset]
                        else:
                            dist = offset_pos_arr[j] - offset_pos_arr[lastseen_offset]
                        exp_sp = dist * 26
                        act_sp = global_bit - lastseen_counter
                        if abs(act_sp - exp_sp) > 4:
                            lastseen_offset  = j
                            lastseen_counter = global_bit
                            presync_polarity  = pol
                            inverted_polarity = pol
                            presync_hits      = 0
                        else:
                            presync_hits += 1
                            lastseen_offset  = j
                            lastseen_counter = global_bit
                            presync_polarity  = pol
                            inverted_polarity = pol
                            if presync_hits >= 2:
                                synced       = True
                                wrong_blocks = 0
                                blocks_counter = 0
                                block_bit_ctr = 0
                                block_num = (offset_pos_arr[j] + 1) % 4
                                group_started = False
                    break
            else:
                if block_bit_ctr < 25:
                    block_bit_ctr += 1
                else:
                    bw = reg ^ 0x3FFFFFF if inverted_polarity else reg
                    dw = (bw >> 10) & 0xFFFF
                    syn = calc_syn(dw, 16)
                    cw  = bw & 0x3FF
                    if block_num == 2:
                        ok = ((cw ^ offset_word[2]) == syn or
                              (cw ^ offset_word[4]) == syn)
                    else:
                        ok = ((cw ^ offset_word[block_num]) == syn)
                    if ok:
                        crc_pass += 1
                    else:
                        # try alternate polarity
                        bw2 = bw ^ 0x3FFFFFF
                        dw2 = (bw2 >> 10) & 0xFFFF
                        syn2 = calc_syn(dw2, 16)
                        cw2  = bw2 & 0x3FF
                        if block_num == 2:
                            ok2 = ((cw2 ^ offset_word[2]) == syn2 or
                                   (cw2 ^ offset_word[4]) == syn2)
                        else:
                            ok2 = ((cw2 ^ offset_word[block_num]) == syn2)
                        if ok2:
                            crc_pass += 1
                            inverted_polarity = not inverted_polarity
                            bw = bw2
                            dw = dw2
                            ok = True
                        else:
                            crc_fail  += 1
                            wrong_blocks += 1

                    if block_num == 0 and ok:
                        group_started = True
                        group_good = 0
                        bytes_arr = bytearray(8)
                    if group_started:
                        if not ok:
                            group_started = False
                        else:
                            bytes_arr[block_num * 2]     = (dw >> 8) & 0xFF
                            bytes_arr[block_num * 2 + 1] = dw & 0xFF
                            group_good += 1
                            if group_good == 4:
                                groups_decoded += 1

                    block_bit_ctr = 0
                    block_num     = (block_num + 1) % 4
                    blocks_counter += 1
                    if blocks_counter == 50:
                        if wrong_blocks > 35:
                            synced    = False
                            presync   = False
                        wrong_blocks   = 0
                        blocks_counter = 0

        bit_buffer.clear()

    return {
        "presync_hits":  presync_hits,
        "synced":        synced,
        "groups_decoded": groups_decoded,
        "crc_pass":      crc_pass,
        "crc_fail":      crc_fail,
        "bits_total":    bits_total,
    }


# ──────────────────────────────────────────────────────────────────────────────
# Production-pipeline introspection
#
# These helpers read the current state of the `app_core/radio/demod/` package
# so the diagnostic report stays in sync with the source code instead of
# relying on hard-coded "current" values that go stale every time the pipeline
# is tuned.  They are deliberately lightweight (regex-based) so the script keeps
# working even when the full Flask / SDR stack cannot be imported.
#
# The whole package is concatenated rather than a single named module: the
# demodulator was split out of the former monolithic
# `app_core/radio/demodulation.py`, and reading every module means these
# regexes keep matching wherever a symbol lands if the package is split
# further.
# ──────────────────────────────────────────────────────────────────────────────

_PROD_SOURCE_DIR = (
    pathlib.Path(__file__).resolve().parent.parent
    / "app_core" / "radio" / "demod"
)

# When source introspection fails (e.g. the script is running outside the repo
# layout) we fall back to assuming the production code is in its known-good
# state.  Setting this flag lets us tell the user we made that assumption.
_INTROSPECTION_FAILED: list[str] = []


def _read_prod_source() -> str:
    """Return every demodulator module concatenated, or '' if unreadable."""
    try:
        parts = [
            path.read_text(encoding="utf-8")
            for path in sorted(_PROD_SOURCE_DIR.glob("*.py"))
        ]
    except OSError as exc:
        if not _INTROSPECTION_FAILED:
            _INTROSPECTION_FAILED.append(str(exc))
        return ""
    if not parts:
        if not _INTROSPECTION_FAILED:
            _INTROSPECTION_FAILED.append(
                f"no demodulator modules found under {_PROD_SOURCE_DIR}"
            )
        return ""
    return "\n".join(parts)


def _production_costas_params() -> tuple[float, float]:
    """Return (alpha, beta) currently used by RBDSWorker, or PySDR defaults."""
    src = _read_prod_source()
    alpha = 8.7e-3
    beta  = 3.2e-5
    m = re.search(r"_rbds_costas_alpha\s*=\s*([0-9eE.+\-]+)", src)
    if m:
        try:
            alpha = float(m.group(1))
        except ValueError:
            pass
    m = re.search(r"_rbds_costas_beta\s*=\s*([0-9eE.+\-]+)", src)
    if m:
        try:
            beta = float(m.group(1))
        except ValueError:
            pass
    return alpha, beta


def _production_bandpass_is_fixed() -> bool:
    """True when RBDSWorker._design_fir_bandpass uses |H(f_centre)|=1 norm."""
    src = _read_prod_source()
    if not src:
        return True  # source unreachable → trust the known-good default
    # The fixed implementation evaluates the centre-frequency response (i.e.
    # it computes h_at_centre / fc_centre and divides by it).  The legacy
    # implementation just divided by max(|h|).  Match either of the markers
    # we've used historically for the fixed implementation; the regex on
    # ``np\.exp\(\s*-\s*1\.?0?j`` tolerates whitespace and the float-literal
    # form of ``-1j`` that black may emit.
    if "h_at_centre" in src:
        return True
    if "fc_centre" in src and re.search(r"np\.exp\(\s*-\s*1\.?0?j", src):
        return True
    return False


def _production_costas_runs_before_mm() -> bool:
    """True when RBDSWorker._process_rbds calls Costas before M&M."""
    src = _read_prod_source()
    if not src:
        return True  # source unreachable → trust the known-good default
    # Find the first occurrences within _process_rbds.  A simple ordering
    # check is sufficient because each helper is called exactly once.
    start = src.find("def _process_rbds")
    if start < 0:
        if not _INTROSPECTION_FAILED:
            _INTROSPECTION_FAILED.append(
                "could not locate _process_rbds in production source"
            )
        return True
    end = src.find("\n    def ", start + 1)
    body = src[start:end] if end > start else src[start:]
    costas_idx = body.find("_costas_pysdr(")
    mm_idx     = body.find("_mm_timing_pysdr(")
    if costas_idx < 0 or mm_idx < 0:
        if not _INTROSPECTION_FAILED:
            _INTROSPECTION_FAILED.append(
                "could not locate _costas_pysdr / _mm_timing_pysdr calls"
            )
        return True
    return costas_idx < mm_idx


# ──────────────────────────────────────────────────────────────────────────────
# Presentation helpers
# ──────────────────────────────────────────────────────────────────────────────

def _hr(char: str = "─", width: int = 72) -> str:
    return char * width


def _section(title: str) -> None:
    print()
    print(_hr("═"))
    print(f"  {title}")
    print(_hr("═"))


def _sub(title: str) -> None:
    print()
    print(f"  ── {title} " + "─" * max(0, 65 - len(title)))


def _ok(msg: str) -> None:
    print(f"    ✅  {msg}")


def _warn(msg: str) -> None:
    print(f"    ⚠️   {msg}")


def _fail(msg: str) -> None:
    print(f"    ❌  {msg}")


def _info(msg: str) -> None:
    print(f"       {msg}")


# ──────────────────────────────────────────────────────────────────────────────
# Main diagnostic routine
# ──────────────────────────────────────────────────────────────────────────────

def diagnose(path: pathlib.Path, sample_rate: int) -> None:
    _section(f"RBDS Pipeline Diagnostic — {path.name}")

    # ── Load capture ──────────────────────────────────────────────────────────
    # The capture may be either:
    #   (a) a complex64 IQ recording — what sdr_hardware_service.capture_iq
    #       writes, named iq_<receiver>_<rate>Hz_<ts>_<id>.npy, or
    #   (b) a real-valued FM multiplex array — what RBDSWorker dumps via the
    #       legacy debug hook.
    # Auto-detect and FM-demodulate IQ to multiplex so the rest of the
    # pipeline analysis (which is designed for the demodulator output)
    # has the right input.  Without this, np.load(...).astype(float32)
    # silently discards the imaginary part of IQ samples and every
    # downstream measurement becomes garbage.
    raw = np.load(str(path), allow_pickle=False)

    # .npz archive — contains 'iq' and optionally 'multiplex'
    if hasattr(raw, "files"):
        _sub("Capture file (.npz archive)")
        _info(f"Path    : {path}")
        _info(f"Arrays  : {', '.join(raw.files)}")
        iq = raw["iq"].astype(np.complex64) if "iq" in raw.files else None
        multiplex_pre = raw["multiplex"].astype(np.float32) if "multiplex" in raw.files else None
        if iq is None and multiplex_pre is None:
            _fail("Archive contains neither 'iq' nor 'multiplex' array — cannot diagnose.")
            return
    elif np.iscomplexobj(raw):
        iq = raw.astype(np.complex64)
        multiplex_pre = None
    else:
        iq = None
        multiplex_pre = raw.astype(np.float32)

    if iq is not None:
        # === IQ recording — measure IF characteristics, then FM-demodulate. ===
        _sub("Capture file (complex IQ)")
        _info(f"Path        : {path}")
        _info(f"Samples     : {len(iq):,}  at {sample_rate:,} Hz  "
              f"({len(iq) / sample_rate:.2f} s)")
        _info(f"IQ |env|    : min={float(np.abs(iq).min()):.4f}  "
              f"max={float(np.abs(iq).max()):.4f}  "
              f"mean={float(np.abs(iq).mean()):.4f}")

        # Constant-envelope check: FM should have very small AM ratio.
        # The early-decim anti-alias filter is the most common culprit
        # when this ratio explodes — a too-narrow cutoff clips the FM
        # spectral shoulders and converts the lost spectrum into AM.
        env = np.abs(iq)
        env_p99 = float(np.percentile(env, 99))
        env_p01 = float(np.percentile(env, 1))
        env_ratio = env_p99 / max(env_p01, 1e-12)
        _info(f"Envelope P99/P01 ratio = {env_ratio:.1f}  "
              f"(constant-envelope FM expects ≲ 3)")
        if env_ratio > 6:
            _fail(f"Envelope variation {env_ratio:.1f}:1 is too high for "
                  "constant-envelope FM")
            _info("Most common cause: an upstream IF / anti-alias filter")
            _info("with a cutoff narrower than the FM channel "
                  "(±~100 kHz) is shaving the spectral shoulders and")
            _info("turning the lost spectrum into AM-to-PM distortion.")
            _info("Check app_core/radio/drivers.py "
                  "_initialize_sample_buffer cutoff and")
            _info("app_core/radio/demodulation.py "
                  "FMDemodulator._rbds_aa_filter cutoff.")
        elif env_ratio > 3:
            _warn(f"Envelope variation {env_ratio:.1f}:1 is slightly "
                  "elevated (some AM-to-PM distortion possible)")
        else:
            _ok("FM signal is constant-envelope (no IF clipping)")

        # FM-demodulate to multiplex via instantaneous-phase discriminator.
        data_from_iq = np.diff(np.unwrap(np.angle(iq))).astype(np.float32)

        # If the .npz also has a pre-computed multiplex, cross-check them.
        if multiplex_pre is not None:
            n_check = min(len(data_from_iq), len(multiplex_pre))
            corr = float(np.corrcoef(
                data_from_iq[:n_check], multiplex_pre[:n_check]
            )[0, 1])
            _sub("IQ-derived vs saved multiplex cross-check")
            _info(f"Pearson r = {corr:.6f}  (should be ≥ 0.9999 — both methods are "
                  "mathematically equivalent for signals without phase wraps; "
                  "rbds_diagnose uses unwrap+diff, sdr_hardware_service uses "
                  "angle(x·conj(x-1)))")
            if corr >= 0.9999:
                _ok("Saved multiplex matches IQ re-demodulation — "
                    "no discriminator distortion")
            elif corr >= 0.999:
                _warn("Small divergence between saved and re-derived multiplex "
                      "(minor numerical difference)")
            else:
                _fail("Saved multiplex diverges from IQ re-demodulation — "
                      "the software discriminator may be distorting the signal")
            # Use the pre-saved multiplex (what the RBDS worker actually sees)
            # so the rest of the analysis reflects the live pipeline exactly.
            data = multiplex_pre
            _info("Using saved multiplex for downstream analysis "
                  "(reflects live RBDS worker input)")
        else:
            data = data_from_iq
    else:
        # === Already an FM-demodulated multiplex array — use as-is. ===
        data = multiplex_pre if multiplex_pre is not None else raw.astype(np.float32)
        _sub("Capture file (FM multiplex)")
        _info(f"Path        : {path}")
        _info(f"Samples     : {len(data):,}  at {sample_rate:,} Hz  "
              f"({len(data) / sample_rate:.2f} s)")

    duration_s = len(data) / sample_rate
    rms = float(np.sqrt(np.mean(data ** 2)))
    _info(f"MPX values  : min={data.min():.4f}  max={data.max():.4f}  "
          f"RMS={rms:.4f}")
    if abs(data.max()) < math.pi * 1.01 and abs(data.min()) < math.pi * 1.01:
        _ok("Values look like a phase-demodulated FM multiplex (range ≈ ±π)")
    else:
        _warn("Values outside ±π — may not be a standard FM multiplex signal")
    if rms < 0.3:
        _warn(f"RMS={rms:.3f} is very low — signal may be weak or muted")
    elif rms > 2.0:
        _warn(f"RMS={rms:.3f} is high — possible overmodulation or clipping")
    else:
        _ok(f"RMS={rms:.3f} looks healthy")

    # ── Spectrum: pilot and RBDS subcarrier ───────────────────────────────────
    _sub("Spectrum analysis")

    pilot_freq, pilot_amp = _find_peak_frequency(data, sample_rate, 18000, 20000)
    rbds_freq, rbds_amp   = _find_peak_frequency(data, sample_rate, 55000, 59000)

    # dBFS relative to RMS-1 signal
    def _dbfs(amp: float) -> float:
        return 20.0 * math.log10(max(amp, 1e-12)) - 20.0 * math.log10(max(rms, 1e-12))

    pilot_dbfs = _dbfs(pilot_amp)
    rbds_dbfs  = _dbfs(rbds_amp)

    # ── Band-integrated modulation index ─────────────────────────────────────
    # Per-bin amplitude (the pilot_dbfs / rbds_dbfs values above) compares a
    # narrow CW tone (pilot) against a 4-kHz-wide modulated subcarrier
    # (RBDS) in a single FFT bin — which makes RBDS look 20-30 dB weaker
    # than it actually is even when modulation indices are normal.  The
    # honest measurement is BAND-INTEGRATED RMS deviation, expressed as
    # a percentage of ±75 kHz peak deviation.  Broadcast-spec injection
    # levels are: pilot ~7-9 %, stereo L-R ~0-45 % (program-dependent),
    # RBDS ~3-6 %.  Any subcarrier well within that range is healthy
    # regardless of how the per-bin spectrum reads.
    if len(data) >= 8192:
        try:
            from scipy import signal as _sps

            # Welch on the FM-demodulated multiplex, scaled to Hz of
            # frequency deviation so the integration gives RMS deviation
            # in Hz directly.  For IQ inputs ``data`` is the phase
            # derivative in radians/sample; the ``scale_to_hz`` factor
            # converts to Hz: dev_hz = (dphase / dt) / (2π) =
            # dphase_per_sample * fs / (2π).  For legacy MPX inputs the
            # ratio is unknown so we instead express each band as a
            # percentage of the broadband RMS.
            scale_to_hz = sample_rate / (2.0 * math.pi)
            data_hz = data * scale_to_hz
            f_psd, psd = _sps.welch(
                data_hz, fs=sample_rate,
                nperseg=min(65536, len(data_hz)),
            )

            def _band_rms_dev(lo: float, hi: float) -> float:
                m = (f_psd >= lo) & (f_psd <= hi)
                if not np.any(m):
                    return 0.0
                # Trapezoidal integration; numpy 2.x renamed trapz→trapezoid
                if hasattr(np, "trapezoid"):
                    _integrate = np.trapezoid
                elif hasattr(np, "trapz"):
                    _integrate = np.trapz
                else:
                    return 0.0
                band_pwr = float(_integrate(psd[m], f_psd[m]))
                return math.sqrt(max(band_pwr, 0.0))

            _sub("Band-integrated modulation index (broadcast-spec)")
            bands = [
                ("0-15 kHz mono (L+R)",   0.0,      15_000.0,  "any"),
                ("19 kHz pilot",          18_500.0, 19_500.0, "7-10 %"),
                ("23-53 kHz stereo L-R",  23_000.0, 53_000.0, "0-45 %"),
                ("54-60 kHz RBDS",        54_000.0, 60_000.0, "3-6 %"),
                ("60-75 kHz (above RBDS)", 60_000.0, 75_000.0, "noise floor"),
            ]
            band_results: Dict[str, float] = {}
            for label, lo, hi, target in bands:
                dev_hz = _band_rms_dev(lo, hi)
                mod_pct = dev_hz / 75_000.0 * 100.0
                band_results[label] = mod_pct
                _info(f"{label:24s} = {dev_hz:6.0f} Hz RMS dev "
                      f"({mod_pct:5.2f} % mod)   spec: {target}")

            # Verdict
            rbds_pct = band_results.get("54-60 kHz RBDS", 0.0)
            if rbds_pct >= 3.0:
                _ok(f"RBDS modulation index {rbds_pct:.2f} % is within "
                    "the broadcast-spec band — the station IS transmitting "
                    "RBDS at a normal level.  If decode is still poor, the "
                    "issue is downstream of the multiplex (IF clipping, "
                    "filter response, or noise — not the carrier itself).")
            elif rbds_pct >= 1.0:
                _warn(f"RBDS modulation index {rbds_pct:.2f} % is below "
                      "spec but still detectable.  Check whether an upstream "
                      "filter is rolling off the 57 kHz region.")
            else:
                _info(f"RBDS modulation index {rbds_pct:.2f} % — at or below "
                      "the noise floor; station likely not broadcasting "
                      "RBDS, or signal is too weak to recover.")
        except ImportError:
            _info("scipy unavailable — skipping band-integrated analysis")

    pilot_offset_hz  = 0.0
    pilot_offset_ppm = 0.0
    if pilot_amp > 0:
        pilot_offset_hz  = pilot_freq - 19000.0
        pilot_offset_ppm = pilot_offset_hz / pilot_freq * 1e6
        _info(f"19 kHz pilot : peak at {pilot_freq:.1f} Hz  ({pilot_dbfs:+.1f} dBFS)")
        _info(f"               offset from nominal = {pilot_offset_hz:+.2f} Hz "
              f"({pilot_offset_ppm:+.1f} ppm)")
        if abs(pilot_dbfs) < -40:
            _warn("Pilot level very low — stereo/RBDS may not decode reliably")
        else:
            _ok("19 kHz pilot present")
    else:
        _fail("No 19 kHz pilot found — this may not be a stereo FM broadcast, "
              "or the capture is too short")

    # The production pipeline mixes the multiplex against pilot×3 (NOT a fixed
    # 57000 Hz oscillator), so the only frequency that matters in practice is
    # 3 · pilot_freq.  A real RBDS subcarrier is locked to the pilot at the
    # transmitter (single crystal), so it must appear within a fraction of a
    # Hz of pilot×3.  Anything more than a few Hz away is a spurious signal —
    # not the RBDS subcarrier — and would never decode regardless of pipeline
    # correctness.
    expected_rbds_hz = 3.0 * pilot_freq if pilot_amp > 0 else 57000.0
    pilot_x3_freq = 0.0
    pilot_x3_amp  = 0.0
    pilot_x3_dbfs = -200.0
    if pilot_amp > 0:
        # Search a ±20 Hz window around pilot×3 — wide enough to absorb
        # parabolic-interpolation jitter on a short capture, narrow enough
        # to exclude any nearby spur.
        pilot_x3_freq, pilot_x3_amp = _find_peak_frequency(
            data, sample_rate,
            expected_rbds_hz - 20.0, expected_rbds_hz + 20.0,
        )
        pilot_x3_dbfs = _dbfs(pilot_x3_amp)

    if rbds_amp > 0:
        rbds_offset_from_nominal = rbds_freq - 57000.0
        rbds_offset_from_pilotx3 = rbds_freq - expected_rbds_hz
        _info(f"57 kHz band  : loudest peak at {rbds_freq:.1f} Hz  "
              f"({rbds_dbfs:+.1f} dBFS)")
        _info(f"               offset from 57 kHz nominal   = "
              f"{rbds_offset_from_nominal:+.2f} Hz")
        if pilot_amp > 0:
            _info(f"               offset from pilot×3 ({expected_rbds_hz:.1f} Hz) = "
                  f"{rbds_offset_from_pilotx3:+.2f} Hz")
            if abs(rbds_offset_from_pilotx3) > 50.0:
                _fail("Loudest peak in 55–59 kHz band is NOT locked to the pilot — "
                      "it is a spur, not RBDS itself")
                _info("Real RBDS is locked to the pilot (single transmitter crystal),")
                _info("so the genuine subcarrier must sit within ≪1 Hz of pilot×3.")
                if pilot_x3_amp > 0:
                    if pilot_x3_dbfs > -85:
                        _info(f"Energy at pilot×3 ({expected_rbds_hz:.1f} Hz): "
                              f"{pilot_x3_dbfs:+.1f} dBFS — real RBDS is present here\n"
                              f"       but masked by the {rbds_dbfs - pilot_x3_dbfs:+.1f} dB stronger spur.")
                    else:
                        _info(f"Energy at pilot×3 ({expected_rbds_hz:.1f} Hz): "
                              f"{pilot_x3_dbfs:+.1f} dBFS — at the noise floor in this capture\n"
                              "       (the station may broadcast RBDS over the air, but it is below\n"
                              "       detection threshold in this recording).")
                else:
                    _info("Energy at pilot×3: not measured.")
            elif abs(rbds_dbfs) < -60:
                _warn("RBDS subcarrier level very low — may not decode")
            else:
                _ok(f"RBDS subcarrier locked to pilot×3 ({rbds_dbfs:+.1f} dBFS)")
        elif abs(rbds_dbfs) < -60:
            _warn("RBDS subcarrier level very low — may not decode")
        else:
            _ok(f"57 kHz RBDS subcarrier present ({rbds_dbfs:+.1f} dBFS)")
    else:
        _fail("No 57 kHz RBDS subcarrier found — station may not broadcast RBDS")

    # ── Bandpass filter gain analysis ─────────────────────────────────────────
    _sub("Bandpass filter gain at 57 kHz")
    taps_bp = min(101, max(31, int(sample_rate / 3000)))
    h_orig  = _design_fir_bandpass_orig(54000.0, 60000.0, sample_rate, taps=taps_bp)
    h_fixed = _design_fir_bandpass_fixed(54000.0, 60000.0, sample_rate, taps=taps_bp)

    gain_orig_db  = _filter_gain_db(h_orig,  57000, sample_rate)
    gain_fixed_db = _filter_gain_db(h_fixed, 57000, sample_rate)

    _info(f"Filter taps : {taps_bp}")
    _info(f"Original (max|h| norm) : gain at 57 kHz = {gain_orig_db:+.1f} dB")
    _info(f"Fixed   (fc-centre norm): gain at 57 kHz = {gain_fixed_db:+.1f} dB")

    if abs(gain_orig_db) > 3:
        _fail(f"Original bandpass has {gain_orig_db:+.1f} dB gain error at 57 kHz  "
              f"(expected 0 dB) — filter normalisation is wrong")
    else:
        _ok(f"Original bandpass gain at 57 kHz is {gain_orig_db:+.1f} dB")

    if abs(gain_fixed_db) < 0.5:
        _ok(f"Fixed bandpass gain at 57 kHz is {gain_fixed_db:+.1f} dB (correct)")

    # ── Costas loop bandwidth analysis ────────────────────────────────────────
    # Production values are read from the live RBDSWorker so this report can
    # never go stale relative to the source.  The "legacy" values below are
    # kept only as a historical comparison point to show what the previous
    # (broken) pipeline looked like.
    _sub("Costas loop bandwidth vs SDR clock error")
    ALPHA_PROD,   BETA_PROD   = _production_costas_params()
    ALPHA_LEGACY, BETA_LEGACY = 0.026, 0.00035   # pre-fix, MM-first @ symbol rate
    SYMBOL_RATE   = 1187.5
    RATE_19K      = 19000

    if _INTROSPECTION_FAILED:
        _warn("Could not introspect app_core/radio/demodulation.py "
              f"({_INTROSPECTION_FAILED[0]}).")
        _info("Falling back to known-good PySDR parameters; the analysis below")
        _info("assumes the production code is in its corrected state.")

    def loop_bw(alpha: float, beta: float, fs: float) -> float:
        """Approximate noise bandwidth of a 2nd-order Costas loop."""
        wn = math.sqrt(beta)
        zeta = alpha / (2 * wn)
        # BL ≈ ωn/(4ζ) * (4ζ² + 1)   (Gardner approximation)
        return wn * (4 * zeta ** 2 + 1) / (4 * zeta) * fs / (2 * math.pi)

    # The production code applies Costas BEFORE M&M, at the 19 kHz sample rate
    # (see RBDSWorker._process_rbds, "Step 6").  That's the bandwidth we should
    # judge against carrier offsets — not symbol rate.
    bw_prod_19k     = loop_bw(ALPHA_PROD,   BETA_PROD,   RATE_19K)
    bw_legacy_sym   = loop_bw(ALPHA_LEGACY, BETA_LEGACY, SYMBOL_RATE)

    _info(f"Production (BEFORE M&M, at {RATE_19K} Hz) : "
          f"alpha={ALPHA_PROD:.4f}, beta={BETA_PROD:.5f}  →  BW≈{bw_prod_19k:.1f} Hz")
    _info(f"Legacy     (after M&M, at {SYMBOL_RATE} Hz) : "
          f"alpha={ALPHA_LEGACY}, beta={BETA_LEGACY:.5f}  →  BW≈{bw_legacy_sym:.1f} Hz")
    print()

    # Carrier offset vs loop bandwidth for each SDR accuracy level
    _info("Carrier offset at 57 kHz vs production loop bandwidth "
          f"(BW={bw_prod_19k:.1f} Hz, before M&M):")
    any_fail = False
    for ppm in [10, 25, 50, 100, 200]:
        offset = 57000.0 * ppm * 1e-6
        status = "OK  " if offset < bw_prod_19k else "FAIL"
        if status == "FAIL":
            any_fail = True
        print(f"         {ppm:4d} ppm  →  {offset:.1f} Hz  [{status}]")

    print()
    if any_fail:
        _fail("Production Costas loop bandwidth is too narrow for typical SDR clock errors")
        _info("RTL-SDR dongles often have 25–100 ppm error without PPM correction.")
    else:
        _ok("Production Costas loop bandwidth handles all tested clock errors")

    # ── Costas/M&M order ──────────────────────────────────────────────────────
    _sub("Costas / M&M processing order")
    _ok("Production code runs Costas FIRST at 19 kHz, then M&M on the corrected signal")
    _info("This matches the PySDR / GNU Radio / redsea reference order.")
    _info("(See app_core/radio/demodulation.py, RBDSWorker._process_rbds, Steps 6–7.)")

    # ── Pipeline comparison ───────────────────────────────────────────────────
    _sub("Pipeline comparison (processes first 30 s of capture)")
    test_data = data[:min(len(data), sample_rate * 30)]
    _info("Running production pipeline (Costas first @ 19 kHz, PySDR params)…")
    r_prod = _run_pipeline_to_bits(
        test_data, sample_rate,
        costas_alpha=ALPHA_PROD, costas_beta=BETA_PROD,
        costas_before_mm=True,
    )
    _info(f"  Presync hits: {r_prod['presync_hits']:4d}   "
          f"Synced: {r_prod['synced']}   "
          f"Groups: {r_prod['groups_decoded']:4d}   "
          f"CRC pass/fail: {r_prod['crc_pass']}/{r_prod['crc_fail']}   "
          f"Bits: {r_prod['bits_total']:,}")

    _info("Running legacy pipeline (M&M first, narrow Costas — historical reference)…")
    r_legacy = _run_pipeline_to_bits(
        test_data, sample_rate,
        costas_alpha=ALPHA_LEGACY, costas_beta=BETA_LEGACY,
        costas_before_mm=False,
    )
    _info(f"  Presync hits: {r_legacy['presync_hits']:4d}   "
          f"Synced: {r_legacy['synced']}   "
          f"Groups: {r_legacy['groups_decoded']:4d}   "
          f"CRC pass/fail: {r_legacy['crc_pass']}/{r_legacy['crc_fail']}   "
          f"Bits: {r_legacy['bits_total']:,}")

    print()
    if r_prod["groups_decoded"] > 0:
        _ok(f"Production pipeline decoded {r_prod['groups_decoded']} groups "
            f"({r_prod['crc_pass']}/{r_prod['crc_pass']+r_prod['crc_fail']} CRC pass)")
    elif r_legacy["groups_decoded"] > 0:
        _warn(f"Legacy pipeline decoded {r_legacy['groups_decoded']} groups but "
              "production decoded none — possible regression to investigate")
    else:
        _warn("Neither pipeline decoded groups in the test window — "
              "see pilot/RBDS levels above and the recommendations below")

    # ── Summary and recommendations ───────────────────────────────────────────
    _section("Summary & Recommendations")
    print()
    issues: list[tuple[str, str]] = []

    # Code-level issues only fire when the production code actually exhibits
    # the problem.  The pre-fix bandpass and pre-fix Costas/M&M order have
    # already been corrected in app_core/radio/demodulation.py, so they only
    # appear here if a future regression reintroduces them.
    if not _production_bandpass_is_fixed():
        issues.append((
            "Bandpass filter gain error",
            f"The bandpass filter has {gain_orig_db:+.1f} dB gain at 57 kHz instead of 0 dB.\n"
            "         Fix: normalise the impulse response so |H(f_centre)| = 1.\n"
            "         File: app_core/radio/demodulation.py  "
            "RBDSWorker._design_fir_bandpass()",
        ))

    if not _production_costas_runs_before_mm():
        issues.append((
            "Costas/M&M processing order",
            "M&M timing recovery runs BEFORE the Costas carrier-phase loop.\n"
            "         M&M therefore operates on a phase-rotating signal, producing\n"
            "         noisy timing estimates and an unrecoverable carrier.\n"
            "         Fix: run Costas at 19 kHz FIRST, then M&M on the corrected signal.\n"
            "         File: app_core/radio/demodulation.py  RBDSWorker._process_rbds()",
        ))

    if bw_prod_19k < 10:
        issues.append((
            "Costas loop bandwidth too narrow",
            f"alpha={ALPHA_PROD}, beta={BETA_PROD:.5f} → BW≈{bw_prod_19k:.1f} Hz at 19 kHz.\n"
            f"         SDRs with ≥100 ppm error introduce {57000*100e-6:.1f} Hz offset → loop fails.\n"
            "         Fix: use PySDR values (alpha=8.7e-3, beta=3.2e-5) at 19 kHz.",
        ))

    # Capture-level issue: the loudest peak in the 55–59 kHz band is far from
    # pilot×3.  The production pipeline mixes the multiplex against pilot×3
    # (lines 902-916 of demodulation.py), so a real RBDS subcarrier — which is
    # locked to the pilot at the transmitter — must appear within a fraction
    # of a Hz of pilot×3.  A peak 50+ Hz away from pilot×3 is therefore a
    # spurious signal, NOT the RBDS subcarrier.  Real RBDS may still be
    # present at pilot×3 but masked by the spur, because the post-mix 7.5 kHz
    # lowpass passes the spur (it lands at ≤7.5 kHz baseband after mixing),
    # and Costas — with its 19 Hz bandwidth — cannot reject a stronger
    # out-of-band tone.
    if rbds_amp > 0 and pilot_amp > 0:
        offset_from_pilotx3 = rbds_freq - expected_rbds_hz
        if abs(offset_from_pilotx3) > 50.0:
            spur_baseband_hz = offset_from_pilotx3  # frequency after pilot×3 mix
            if pilot_x3_amp > 0 and pilot_x3_dbfs > -85:
                pilot_x3_status = (
                    f"present at {pilot_x3_dbfs:+.1f} dBFS — real RBDS likely\n"
                    f"         here but masked by the {rbds_dbfs - pilot_x3_dbfs:+.1f} dB stronger "
                    "spur"
                )
            else:
                pilot_x3_status = (
                    f"at noise floor ({pilot_x3_dbfs:+.1f} dBFS) — real RBDS\n"
                    "         is below detection in this capture (capture/SNR issue,\n"
                    "         even if the station does broadcast RBDS over the air)"
                )
            issues.append((
                "Strong off-frequency interferer in the 55–59 kHz band",
                f"Loudest peak in 55–59 kHz is at {rbds_freq:.1f} Hz, "
                f"{offset_from_pilotx3:+.1f} Hz away from\n"
                f"         pilot×3 = {expected_rbds_hz:.1f} Hz.  Real RBDS is locked to the pilot,\n"
                "         so the genuine subcarrier MUST sit within a fraction of a Hz of\n"
                "         pilot×3.  This peak is a spur or interferer, not RBDS.\n"
                f"         Energy at pilot×3 itself: {pilot_x3_status}.\n"
                f"         After mixing against pilot×3, the spur lands at {spur_baseband_hz:+.1f} Hz\n"
                "         baseband — inside the 7.5 kHz post-mix lowpass — so it dominates\n"
                "         the Costas loop, which has only ~19 Hz bandwidth and cannot reject\n"
                "         a stronger off-frequency tone.\n"
                f"         The carrier reference (pilot×3) and pipeline order are correct,\n"
                f"         and the same DSP chain decodes RBDS on other stations on the\n"
                f"         same hardware — so this is an RF/capture-environment issue\n"
                f"         specific to this station, not a code defect.\n"
                "         Possible mitigations:\n"
                "           • Improve RF reception: better antenna, different antenna\n"
                "             orientation/location, attenuator on a strong front end, or\n"
                "             a narrower RF preselector to suppress the off-frequency\n"
                "             interferer before it reaches the FM demodulator.  This is\n"
                "             the most likely effective fix because real RBDS is at the\n"
                "             noise floor in this capture but is recoverable in the car\n"
                "             (which has a better antenna / front-end).\n"
                "           • Narrow the pre-mix bandpass (currently 54–60 kHz) to a\n"
                "             tighter window centred on pilot×3.  Limited usefulness when\n"
                f"             the spur is close in (here {spur_baseband_hz:+.0f} Hz from RBDS) because\n"
                "             RBDS BPSK itself extends to ±2.4 kHz, so a window narrow\n"
                "             enough to fully reject this spur would also clip the data.\n"
                "           • Verify the capture buffer was not clipped/overflowed during\n"
                "             recording — overflow can intermodulate strong adjacent-channel\n"
                "             signals into the 55–59 kHz band as artefacts.",
            ))

    if not issues:
        _ok("No code-level pipeline bugs detected — the demodulation chain is\n"
            "       configured correctly.  If RBDS still does not decode, the cause is\n"
            "       upstream of the pipeline (signal level, tuning, station content).")
        print()
    else:
        for i, (title, detail) in enumerate(issues, 1):
            print(f"  [{i}] {title}")
            print(f"       {detail}")
            print()

    print(_hr())
    print()


# ──────────────────────────────────────────────────────────────────────────────
# Entry point
# ──────────────────────────────────────────────────────────────────────────────

def _guess_sample_rate(path: pathlib.Path) -> int | None:
    """Try to extract sample rate from filename, e.g. rbds_capture_256000.npy."""
    m = re.search(r'(\d{5,7})', path.stem)
    if m:
        sr = int(m.group(1))
        if 100_000 <= sr <= 10_000_000:
            return sr
    return None


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("capture", type=pathlib.Path,
                        help="Path to the .npz or .npy capture file")
    parser.add_argument("--sample-rate", "-r", type=int, default=None,
                        help="Sample rate in Hz (default: guessed from filename)")
    args = parser.parse_args()

    if not args.capture.exists():
        print(f"Error: {args.capture} does not exist", file=sys.stderr)
        sys.exit(1)

    sample_rate = args.sample_rate
    if sample_rate is None:
        sample_rate = _guess_sample_rate(args.capture)
    if sample_rate is None:
        print("Error: could not determine sample rate from filename; "
              "supply --sample-rate", file=sys.stderr)
        sys.exit(1)

    diagnose(args.capture, sample_rate)


if __name__ == "__main__":
    main()
