#!/usr/bin/env python3
"""
EAS Station - Emergency Alert System
Copyright (c) 2025-2026 Timothy Kramer (KR8MER)

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
    python3 scripts/rbds_diagnose.py /var/log/eas-station/rbds_capture_256000.npy
    python3 scripts/rbds_diagnose.py /path/to/rbds_capture_RATE.npy --sample-rate RATE

Output is written to stdout as plain text; redirect to a file if needed.
"""

from __future__ import annotations

import argparse
import math
import pathlib
import re
import sys

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
    data = np.load(str(path)).astype(np.float32)
    duration_s = len(data) / sample_rate
    rms = float(np.sqrt(np.mean(data ** 2)))
    _sub("Capture file")
    _info(f"Path        : {path}")
    _info(f"Samples     : {len(data):,}  at {sample_rate:,} Hz  ({duration_s:.2f} s)")
    _info(f"Values      : min={data.min():.4f}  max={data.max():.4f}  RMS={rms:.4f}")
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

    if rbds_amp > 0:
        rbds_offset_hz = rbds_freq - 57000.0
        _info(f"57 kHz RBDS  : peak at {rbds_freq:.1f} Hz  ({rbds_dbfs:+.1f} dBFS)")
        _info(f"               offset from nominal = {rbds_offset_hz:+.2f} Hz")
        # Estimate SDR clock error from the RBDS subcarrier offset
        if pilot_amp > 0 and abs(pilot_offset_hz) < 10:
            # More accurate: use pilot frequency to infer clock error
            clock_ppm = pilot_offset_ppm
            expected_rbds_offset = 57000.0 * clock_ppm * 1e-6
            _info(f"               expected offset from SDR clock error = "
                  f"{expected_rbds_offset:+.1f} Hz")
        if abs(rbds_dbfs) < -60:
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
    _sub("Costas loop bandwidth vs SDR clock error")
    ALPHA_CURRENT = 0.026
    BETA_CURRENT  = 0.00035
    ALPHA_PYSDR   = 8.7e-3
    BETA_PYSDR    = 3.2e-5
    SYMBOL_RATE   = 1187.5
    RATE_19K      = 19000

    def loop_bw(alpha: float, beta: float, fs: float) -> float:
        """Approximate noise bandwidth of a 2nd-order Costas loop."""
        wn = math.sqrt(beta)
        zeta = alpha / (2 * wn)
        # BL ≈ ωn/(4ζ) * (4ζ² + 1)   (Gardner approximation)
        return wn * (4 * zeta ** 2 + 1) / (4 * zeta) * fs / (2 * math.pi)

    bw_curr_sym  = loop_bw(ALPHA_CURRENT, BETA_CURRENT, SYMBOL_RATE)
    bw_pysdr_sym = loop_bw(ALPHA_PYSDR,  BETA_PYSDR,   SYMBOL_RATE)
    bw_pysdr_19k = loop_bw(ALPHA_PYSDR,  BETA_PYSDR,   RATE_19K)

    _info(f"Current  (after M&M, at {SYMBOL_RATE} Hz) : "
          f"alpha={ALPHA_CURRENT}, beta={BETA_CURRENT:.5f}  →  BW≈{bw_curr_sym:.1f} Hz")
    _info(f"PySDR    (after M&M, at {SYMBOL_RATE} Hz) : "
          f"alpha={ALPHA_PYSDR:.4f}, beta={BETA_PYSDR:.5f}  →  BW≈{bw_pysdr_sym:.1f} Hz")
    _info(f"PySDR  (BEFORE M&M, at {RATE_19K} Hz) : "
          f"alpha={ALPHA_PYSDR:.4f}, beta={BETA_PYSDR:.5f}  →  BW≈{bw_pysdr_19k:.1f} Hz")
    print()

    # Carrier offset vs loop bandwidth for each SDR accuracy level
    _info("Carrier offset at 57 kHz vs current loop bandwidth "
          f"(BW={bw_curr_sym:.1f} Hz, after M&M):")
    any_fail = False
    for ppm in [10, 25, 50, 100, 200]:
        offset = 57000.0 * ppm * 1e-6
        status = "OK  " if offset < bw_curr_sym else "FAIL"
        if status == "FAIL":
            any_fail = True
        print(f"         {ppm:4d} ppm  →  {offset:.1f} Hz  [{status}]")

    print()
    if any_fail:
        _fail("Current Costas loop bandwidth is too narrow for typical SDR clock errors")
        _info("RTL-SDR dongles often have 25–100 ppm error without PPM correction.")
        _info("Even with correction, ±25 ppm leaves 1.4 Hz offset — marginal at 3.5 Hz BW.")
    else:
        _ok("Current Costas loop bandwidth handles all tested clock errors")

    _info(f"With PySDR parameters at 19 kHz (BW≈{bw_pysdr_19k:.0f} Hz), all SDR errors fit easily")

    # ── Costas/M&M order ──────────────────────────────────────────────────────
    _sub("Costas / M&M processing order")
    _fail("Current code runs M&M FIRST then Costas (at symbol rate)")
    _info("Standard order (PySDR, GNU Radio, redsea) is Costas FIRST at 19 kHz,")
    _info("then M&M on the carrier-corrected signal.")
    _info("Running M&M on a phase-rotating signal causes noisy timing error estimates")
    _info("and prevents the Costas loop from ever acquiring a stable carrier lock.")

    # ── Pipeline comparison ───────────────────────────────────────────────────
    _sub("Pipeline comparison (processes first 30 s of capture)")
    test_data = data[:min(len(data), sample_rate * 30)]
    _info("Running pipeline with current parameters (M&M first, narrow Costas)…")
    r_current = _run_pipeline_to_bits(
        test_data, sample_rate,
        costas_alpha=ALPHA_CURRENT, costas_beta=BETA_CURRENT,
        costas_before_mm=False,
    )
    _info(f"  Presync hits: {r_current['presync_hits']:4d}   "
          f"Synced: {r_current['synced']}   "
          f"Groups: {r_current['groups_decoded']:4d}   "
          f"CRC pass/fail: {r_current['crc_pass']}/{r_current['crc_fail']}   "
          f"Bits: {r_current['bits_total']:,}")

    _info("Running pipeline with fixed order (Costas first at 19 kHz, PySDR params)…")
    r_fixed = _run_pipeline_to_bits(
        test_data, sample_rate,
        costas_alpha=ALPHA_PYSDR, costas_beta=BETA_PYSDR,
        costas_before_mm=True,
    )
    _info(f"  Presync hits: {r_fixed['presync_hits']:4d}   "
          f"Synced: {r_fixed['synced']}   "
          f"Groups: {r_fixed['groups_decoded']:4d}   "
          f"CRC pass/fail: {r_fixed['crc_pass']}/{r_fixed['crc_fail']}   "
          f"Bits: {r_fixed['bits_total']:,}")

    def decode_rate(r: dict) -> str:
        total = r["crc_pass"] + r["crc_fail"]
        if total == 0:
            return "n/a"
        return f"{100 * r['crc_pass'] / total:.0f}%"

    print()
    if r_fixed["groups_decoded"] > r_current["groups_decoded"]:
        _ok(f"Fixed pipeline decoded more groups "
            f"({r_fixed['groups_decoded']} vs {r_current['groups_decoded']})")
    elif r_fixed["groups_decoded"] == r_current["groups_decoded"] > 0:
        _ok(f"Both pipelines decoded {r_current['groups_decoded']} groups — "
            "issue may be elsewhere")
    else:
        _warn("Neither pipeline decoded groups in the test window — "
              "check pilot/RBDS levels above")

    # ── Summary and recommendations ───────────────────────────────────────────
    _section("Summary & Recommendations")
    print()
    issues = []

    if abs(gain_orig_db) > 3:
        issues.append((
            "Bandpass filter gain error",
            f"The bandpass filter has {gain_orig_db:+.1f} dB gain at 57 kHz instead of 0 dB.\n"
            "         Fix: normalise the impulse response so |H(f_centre)| = 1.\n"
            "         File: app_core/radio/demodulation.py  "
            "RBDSWorker._design_fir_bandpass()",
        ))

    issues.append((
        "Costas/M&M processing order (primary cause)",
        "M&M timing recovery runs BEFORE the Costas carrier-phase loop.\n"
        "         M&M therefore operates on a phase-rotating signal, producing\n"
        "         noisy timing estimates and an unrecoverable carrier.\n"
        "         Fix: run Costas at 19 kHz FIRST, then M&M on the corrected signal.\n"
        "         File: app_core/radio/demodulation.py  RBDSWorker._process_rbds()",
    ))

    if bw_curr_sym < 10:
        issues.append((
            "Costas loop bandwidth too narrow",
            f"alpha={ALPHA_CURRENT}, beta={BETA_CURRENT:.5f} → BW≈{bw_curr_sym:.1f} Hz at symbol rate.\n"
            f"         SDRs with ≥100 ppm error introduce {57000*100e-6:.1f} Hz offset → loop fails.\n"
            f"         Fix: use PySDR values (alpha={ALPHA_PYSDR}, beta={BETA_PYSDR:.5f})\n"
            f"         applied at 19 kHz (BW≈{bw_pysdr_19k:.0f} Hz) after the order swap above.",
        ))

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
                        help="Path to the .npy capture file")
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
