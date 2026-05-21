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
"""

"""
SDR Hardware Service

This service handles ONLY SDR hardware operations (exclusive USB access):
- SoapySDR device management (open, configure, read)
- Dual-thread USB reading for reliable operation
- Publishing IQ samples to Redis for downstream consumers
- Publishing SDR health metrics to Redis

Architecture:
                    ┌─────────────────┐
                    │   SoapySDR      │
                    │   USB Device    │
                    └────────┬────────┘
                             │
            ┌───────────────────┴─────────────────┐
            │   sdr_hardware_service.py        │
            │   (This file - USB access)       │
            │                                  │
            │  ┌───────────┐  ┌────────────┐  │
            │  │USB Reader │──│Ring Buffer │  │
            │  │  Thread   │  └─────┬──────┘  │
            │  └───────────┘        │         │
            │                       ▼         │
            │              ┌────────────┐     │
            │              │ Publisher  │     │
            │              │   Thread   │     │
            │              └─────┬──────┘     │
            └────────────────────┼────────────┘
                                 │ Redis pub/sub
                                 │ sdr:samples:{id}
                                 ▼
            ┌────────────────────────────────────┐
            │   eas_monitoring_service.py        │
            │   (No USB access needed)           │
            │                                    │
            │  - IQ demodulation (FM/AM/NFM)     │
            │  - EAS/SAME decoding               │
            │  - Icecast streaming               │
            └────────────────────────────────────┘

Benefits:
- SDR crashes don't affect audio processing
- SDR service can be restarted without losing audio pipeline state
- Clear separation of concerns
- USB-specific permissions isolated to SDR container
- Audio processing can run on separate hardware if needed
"""

import os
import sys
import time
import signal
import logging
import json
import threading
from typing import Optional, Dict, Any
from dataclasses import dataclass, field
from dotenv import load_dotenv

# Configure logging early
from app_core.logging_context import (
    LOG_FORMAT_WITH_ALERT,
    install_alert_filter,
)
logging.basicConfig(
    level=logging.DEBUG,  # Changed from INFO to DEBUG to show diagnostic logs
    format=LOG_FORMAT_WITH_ALERT,
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
install_alert_filter()

logger = logging.getLogger(__name__)

# Load environment variables from persistent config volume
_config_path = os.environ.get('CONFIG_PATH')
if _config_path:
    if os.path.exists(_config_path):
        load_dotenv(_config_path, override=True)
        logger.info(f"✅ Loaded environment from: {_config_path}")
    else:
        logger.warning(f"⚠️  CONFIG_PATH set but file not found: {_config_path}")
        load_dotenv(override=True)
else:
    load_dotenv(override=True)

# Import centralized Redis configuration
from app_core.config.redis_config import get_redis_host, get_redis_port, get_redis_db

# Redis configuration
REDIS_HOST = get_redis_host()
REDIS_PORT = get_redis_port()
REDIS_DB = get_redis_db()

# SDR sample publishing configuration
# IQ samples are published in chunks to balance latency vs overhead.
#
# SDR_SAMPLE_CHUNK_SIZE is an *upper bound* on samples per Redis message
# (caps memory / payload size). The actual per-chunk size is computed
# from the receiver's effective sample rate so that every published
# chunk represents roughly ``SDR_SAMPLE_CHUNK_DURATION_SEC`` of audio
# regardless of native SDR rate.
#
# Why duration-based sizing matters: Airspy R2 only supports 2.5 MHz /
# 10 MHz native, both of which trip the early-decimation path
# (``_SoapySDRReceiver._start_stream`` in app_core/radio/drivers.py)
# down to a 250 kHz effective rate. A fixed 32768-sample request at
# 250 kHz is ~131 ms of audio per Redis message — combined with
# SoapyAirspy's bursty USB transfers this produced audible stutter and
# starved the RBDS carrier-recovery loop, which has to re-converge
# across each chunk boundary. RTL-SDR users typically run at higher
# native rates (240 kHz–2.4 MHz with no early decimation), so the
# fixed-count chunk represented a much shorter wall-clock interval and
# the symptom never appeared on RTL-SDR.
SDR_SAMPLE_CHUNK_SIZE = 32768  # Hard cap on samples per Redis message
SDR_SAMPLE_CHUNK_DURATION_SEC = 0.032  # Target ~32 ms of audio per message
SDR_SAMPLE_CHUNK_MIN = 2048  # Floor; must be >= FFT_SIZE so spectrum still works
SDR_SAMPLE_CHANNEL = "sdr:samples"  # Redis pub/sub channel for IQ data
SDR_METRICS_KEY = "sdr:metrics"  # Redis hash for SDR health metrics
SDR_SPECTRUM_KEY_PREFIX = "sdr:spectrum:"  # Per-receiver spectrum data

# Publisher loop timing - adaptive based on buffer fill level
PUBLISHER_SLEEP_MIN_MS = 1   # Minimum sleep when buffer is filling up
PUBLISHER_SLEEP_MAX_MS = 10  # Maximum sleep when buffer is low

# Spectrum computation constants
FFT_SIZE = 2048
FFT_MIN_MAGNITUDE = 1e-10
SPECTRUM_DB_MIN = -80.0
SPECTRUM_DB_MAX = 0.0

# IQ capture configuration (capture_iq command)
# Captures are written as complex64 .npy files for use with
# scripts/rbds_diagnose.py and other offline analysis tools (GNU Radio,
# inspectrum, custom Python). Default location is under /var/log so it
# co-locates with existing eas-station logs; can be overridden via env.
RADIO_CAPTURE_DIR = os.environ.get(
    "RADIO_CAPTURE_DIR", "/var/log/eas-station/captures"
)
# Hard cap on samples per capture to bound memory/disk:
# 30 M complex64 = ~240 MB on disk; ~30 s at 1 MHz, ~120 s at 250 kHz.
# The webapp side enforces a tighter per-request duration cap
# (RADIO_CAPTURE_MAX_DURATION_SEC) but this is the absolute safety net.
RADIO_CAPTURE_MAX_SAMPLES = 30_000_000
# Maximum wall-clock time we will wait for the publisher tap to deliver a
# capture's samples, including a small slack on top of the requested
# duration. Captures run in real-time so the elapsed wall-clock is roughly
# duration_sec; the slack covers scheduling jitter and the disk write.
RADIO_CAPTURE_WALLCLOCK_SLACK_SEC = 10.0


# ---------------------------------------------------------------------------
# Capture tap registry
# ---------------------------------------------------------------------------
# capture_iq is implemented as a *tap* off the publisher thread (which
# already drains the ring buffer in real time). The command handler
# registers an entry here keyed by receiver identifier; the publisher
# appends a copy of each chunk it reads until the target sample count is
# reached, then sets the completion event. This avoids a destructive
# second consumer racing the publisher for ring-buffer samples (which is
# how the original single-call implementation ended up with one USB
# packet, ~8 ms, instead of the requested duration).
_active_captures: Dict[str, Dict[str, Any]] = {}
_active_captures_lock = threading.Lock()


def _capture_tap_append(identifier: str, samples) -> None:
    """Append a chunk of samples to the active capture for ``identifier``.

    Called from the publisher thread on every chunk it reads. No-op when
    no capture is in flight for this receiver. Signals the capture's
    completion event once the requested sample count has been collected.

    Samples are copied to keep them alive after the producer buffer wraps.
    """
    with _active_captures_lock:
        entry = _active_captures.get(identifier)
        if entry is None or entry.get("done"):
            return
        try:
            target = int(entry["target_samples"])
            collected = int(entry.get("collected", 0))
            remaining = target - collected
            if remaining <= 0:
                return
            # Take at most ``remaining`` samples from the chunk so we don't
            # overshoot the requested length. Copy to detach from the
            # producer's buffer.
            chunk_len = len(samples)
            take = chunk_len if chunk_len <= remaining else remaining
            entry["chunks"].append(samples[:take].copy())
            entry["collected"] = collected + take
            if entry["collected"] >= target:
                entry["done"] = True
                event = entry.get("event")
                if event is not None:
                    event.set()
        except Exception as exc:  # pragma: no cover - defensive
            entry["error"] = str(exc)
            entry["done"] = True
            event = entry.get("event")
            if event is not None:
                event.set()


def _compute_capture_spectral_diagnostics(
    samples: "np.ndarray",
    sample_rate: int,
) -> tuple:
    """FM-demodulate *samples* and return ``(diag_dict, multiplex_array)``.

    ``diag_dict`` contains band-level SNR figures that immediately reveal
    whether the 19 kHz pilot, 38 kHz stereo subcarrier, and 57 kHz RBDS
    subcarrier are present in the capture, together with an estimate of where
    the IQ passband rolls off (which exposes narrow hardware bandwidth settings
    that can silently kill RBDS decoding even though the nominal sample rate
    looks adequate).

    ``multiplex_array`` is the float32 FM discriminator output (rad/sample)
    at *sample_rate*.  Saving it alongside the raw IQ means the capture gives
    two independent diagnostic angles:

    * The IQ file shows whether the hardware IF analogue filter is already
      rolling off the 57 kHz band *before* any software runs.
    * The multiplex file shows what the RBDS worker actually receives after
      FM demodulation — if 57 kHz is missing here but present in the IQ,
      the fault is in the software FM discriminator or early-decimation path.

    Both return values are best-effort; any unexpected error returns
    ``({}, None)`` so the capture is never blocked.
    """
    try:
        import numpy as _np
        from scipy import signal as _sig
    except ImportError:
        return {}, None
    try:
        diag: Dict[str, Any] = {}
        iq = samples.astype(_np.complex64)
        n = len(iq)

        # ── 1. IQ passband rolloff estimate ──────────────────────────────────
        # Use Welch PSD of the raw IQ to find where the hardware's analogue
        # IF filter starts to roll off.  A setBandwidth(256000) on an R820T2
        # produces a -3 dB point near ±115 kHz rather than ±128 kHz; this
        # shows up clearly in the IQ PSD and explains why RBDS is filtered
        # even though the Nyquist is nominally sufficient.
        nperseg = min(4096, n // 4)
        if nperseg >= 64:
            f_w, psd_w = _sig.welch(
                iq, fs=sample_rate, nperseg=nperseg, return_onesided=False
            )
            psd_w = _np.fft.fftshift(psd_w)
            f_w = _np.fft.fftshift(f_w)
            # Reference: median power of the central ±30 kHz (flat FM body)
            ref_mask = _np.abs(f_w) <= 30_000
            if _np.any(ref_mask):
                ref_db = float(10 * _np.log10(_np.median(psd_w[ref_mask]) + 1e-30))
                # Walk outward from 0 Hz and find the highest frequency where
                # PSD is still within 20 dB of the central reference.
                pos_mask = f_w >= 0
                f_pos = f_w[pos_mask]
                p_pos = psd_w[pos_mask]
                valid = p_pos > 0
                if _np.any(valid):
                    db_pos = 10 * _np.log10(p_pos + 1e-30) - ref_db
                    in_band = db_pos >= -20.0
                    if _np.any(in_band):
                        diag["iq_passband_20db_hz"] = int(
                            f_pos[_np.where(in_band)[0][-1]]
                        )

        # ── 2. FM discriminator → multiplex ──────────────────────────────────
        # Instantaneous-phase discriminator: arg(x[n] · conj(x[n-1])).
        # Mathematically equivalent to diff(unwrap(angle(x))) for signals
        # well within the ±π phase-difference range (i.e. no phase wraps),
        # which holds for any FM signal whose per-sample frequency deviation
        # is << fs/2.  The unwrap path in rbds_diagnose.py handles edge cases
        # where large noise spikes could alias the phase, but both methods
        # produce Pearson r ≥ 0.9999 on real FM captures.
        multiplex = _np.angle(iq[1:] * _np.conj(iq[:-1])).astype(_np.float32)
        sr = sample_rate
        n_mp = len(multiplex)
        if n_mp < 4096 or sr < 60_000:
            return diag, multiplex

        # ── 3. Spectral analysis of multiplex ────────────────────────────────
        # Use a large power-of-2 FFT for sub-Hz resolution on long captures.
        n_fft = min(1 << 18, 1 << int(_np.floor(_np.log2(n_mp))))
        window = _np.hanning(n_fft)
        spectrum = _np.abs(_np.fft.rfft(multiplex[:n_fft] * window))
        freqs = _np.fft.rfftfreq(n_fft, d=1.0 / sr)

        def _band_snr(center: float, half_bw: float, noise_lo: float, noise_hi: float):
            """Peak amplitude in [center±half_bw] vs median of [noise_lo, noise_hi]."""
            sig_mask = (freqs >= center - half_bw) & (freqs <= center + half_bw)
            noise_mask = (freqs >= noise_lo) & (freqs <= noise_hi)
            if not (_np.any(sig_mask) and _np.any(noise_mask)):
                return None, None
            sig_amp = float(_np.max(spectrum[sig_mask]))
            noise_med = float(_np.median(spectrum[noise_mask]))
            if noise_med <= 0:
                return None, None
            snr_db = float(20 * _np.log10(sig_amp / noise_med + 1e-12))
            peak_freq = float(freqs[sig_mask][_np.argmax(spectrum[sig_mask])])
            return round(snr_db, 1), round(peak_freq, 2)

        # Noise reference: 28–32 kHz (above stereo pilot, below stereo sideband)
        noise_lo, noise_hi = 28_000.0, 32_000.0

        # 19 kHz pilot (pure tone; use ±200 Hz window)
        pilot_snr, pilot_hz = _band_snr(19_000, 200, noise_lo, noise_hi)
        if pilot_snr is not None:
            diag["pilot_snr_db"] = pilot_snr
            diag["pilot_hz"] = pilot_hz

        # 38 kHz stereo DSB-SC envelope (±500 Hz around 38 kHz)
        stereo_snr, _ = _band_snr(38_000, 500, noise_lo, noise_hi)
        if stereo_snr is not None:
            diag["stereo_38k_snr_db"] = stereo_snr

        # 57 kHz RBDS subcarrier.  BPSK spreads ±1.2 kHz around 57 kHz so use
        # ±1.5 kHz window; noise reference stays at 28–32 kHz.
        rbds_snr, _ = _band_snr(57_000, 1_500, noise_lo, noise_hi)
        if rbds_snr is not None:
            diag["rbds_57k_snr_db"] = rbds_snr

        # Also measure at 57 kHz from the IQ directly (before FM discriminator)
        # so we can compare IQ-domain vs multiplex-domain 57 kHz presence.
        if nperseg >= 64:
            try:
                f_iq, psd_iq = _sig.welch(
                    iq, fs=sample_rate, nperseg=min(4096, n // 4),
                    return_onesided=False,
                )
                psd_iq = _np.fft.fftshift(psd_iq)
                f_iq = _np.fft.fftshift(f_iq)
                # IQ power at +57 kHz vs central reference
                ref_iq_mask = _np.abs(f_iq) <= 20_000
                rbds_iq_mask = (_np.abs(f_iq) >= 55_000) & (_np.abs(f_iq) <= 59_000)
                if _np.any(ref_iq_mask) and _np.any(rbds_iq_mask):
                    ref_iq = float(_np.median(psd_iq[ref_iq_mask]))
                    rbds_iq = float(_np.max(psd_iq[rbds_iq_mask]))
                    if ref_iq > 0:
                        diag["iq_57k_vs_center_db"] = round(
                            10 * _np.log10(rbds_iq / ref_iq + 1e-30), 1
                        )
            except Exception:
                pass

        # Overall multiplex noise floor (median of 28–50 kHz)
        mid_mask = (freqs >= 28_000) & (freqs <= 50_000)
        if _np.any(mid_mask):
            diag["multiplex_noise_floor_db"] = round(
                float(20 * _np.log10(_np.median(spectrum[mid_mask]) + 1e-30)), 1
            )

        return diag, multiplex
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("capture spectral diagnostics failed: %s", exc)
        return {}, None


def _measure_iq_levels(receiver, num_samples: int = 8192) -> Optional[Dict[str, float]]:
    """Briefly drain the receiver and return RMS / peak / clipping stats.

    Returns ``None`` if no samples were available. RMS and peak are
    reported in dBFS where 0 dBFS == |x| == 1.0 (the SoapySDR / libairspy
    drivers in this repo deliver normalized complex64 with that scale).
    """
    try:
        import numpy as np  # local import to keep startup cost low
    except ImportError:  # pragma: no cover
        return None

    samples = receiver.get_samples(num_samples=num_samples) if hasattr(
        receiver, "get_samples"
    ) else None
    if samples is None or len(samples) == 0:
        return None
    mag = np.abs(samples)
    if mag.size == 0:
        return None
    rms = float(np.sqrt(np.mean(mag * mag)))
    peak = float(np.max(mag))
    rms_dbfs = 20.0 * np.log10(rms) if rms > 0 else -120.0
    peak_dbfs = 20.0 * np.log10(peak) if peak > 0 else -120.0
    clip = float(np.mean(mag > 0.95))
    return {
        "samples": int(mag.size),
        "rms_dbfs": float(rms_dbfs),
        "peak_dbfs": float(peak_dbfs),
        "clipping_fraction": clip,
    }


def _auto_gain_calibrate(
    *,
    receiver,
    receiver_id: str,
    command_id: str,
    settle_sec: float = 0.20,
    measure_sec: float = 0.50,
    target_rms_dbfs: float = -12.0,
    clipping_threshold: float = 0.01,
) -> Dict[str, Any]:
    """Sweep supported gain values and choose the highest non-clipping one.

    Algorithm (one-shot, online):
      1. Discover the device's gain range via SoapySDR.
      2. For each candidate gain (ascending), set the gain, briefly let
         samples flow, then measure IQ RMS / peak / clipping ratio.
      3. Pick the highest gain whose ``clipping_fraction`` stays below
         ``clipping_threshold``. Tie-break by preferring the one whose
         RMS sits closest to (but not above) ``target_rms_dbfs`` so we
         leave headroom for modulation peaks.
      4. Apply the chosen gain.

    Requires a SoapySDR-backed receiver (handle.device / handle.sdr).
    Hardware AGC is disabled for the duration of and after calibration:
    AGC has no visibility into outboard amplifiers and would fight any
    manual gain we apply.
    """

    handle = getattr(receiver, "_handle", None)
    config = getattr(receiver, "config", None)
    channel = getattr(config, "channel", None) if config is not None else None
    if channel is None:
        channel = 0

    if handle is None or not hasattr(handle, "device") or not hasattr(handle, "sdr"):
        return {
            "command_id": command_id,
            "success": False,
            "error": (
                "Auto-gain currently requires a SoapySDR-backed receiver "
                "(device handle not available)."
            ),
        }

    device = handle.device
    sdr_module = handle.sdr
    rx = sdr_module.SOAPY_SDR_RX

    # Read the configured external LNA contribution so the headroom target
    # represents *system* gain (SDR tuner stage + LNA), not just the SDR's
    # tuner stage in isolation.  Falls back to 0 dB when the receiver
    # config is missing or the field is unset.
    try:
        external_lna_db = float(getattr(config, "external_lna_db", 0.0) or 0.0)
    except (TypeError, ValueError):
        external_lna_db = 0.0

    candidate_gains: list = []
    try:
        gain_range = device.getGainRange(rx, channel)
        g_min = float(gain_range.minimum())
        g_max = float(gain_range.maximum())
        if g_max > g_min:
            step = 1.0
            n_steps = int(round((g_max - g_min) / step)) + 1
            candidate_gains = [round(g_min + i * step, 1) for i in range(n_steps)]
            # Cap pathological ranges so the sweep is bounded.
            if len(candidate_gains) > 80:
                stride = max(1, len(candidate_gains) // 40)
                candidate_gains = candidate_gains[::stride]
        else:
            candidate_gains = [g_min]
    except Exception as exc:
        return {
            "command_id": command_id,
            "success": False,
            "error": f"Could not read gain range: {exc}",
        }

    if not candidate_gains:
        return {
            "command_id": command_id,
            "success": False,
            "error": "Device reports no usable gain range.",
        }

    try:
        if device.hasGainMode(rx, channel):
            device.setGainMode(rx, channel, False)
    except Exception as exc:  # pragma: no cover - device-specific
        logger.debug(
            "auto_gain: could not disable AGC for %s: %s",
            receiver_id, exc,
        )

    try:
        starting_gain = float(device.getGain(rx, channel))
    except Exception:
        starting_gain = None

    measurements: list = []
    effective_rate = (
        int(getattr(receiver, "_effective_sample_rate", 0) or 0)
        or int(getattr(config, "sample_rate", 0) or 0)
        or 250_000
    )
    measure_samples = max(2048, int(measure_sec * effective_rate))

    logger.info(
        "auto_gain: sweeping %d candidate gain(s) on %s (range %.1f..%.1f dB, "
        "measure %d samples each)",
        len(candidate_gains), receiver_id,
        candidate_gains[0], candidate_gains[-1], measure_samples,
    )

    for gain_db in candidate_gains:
        try:
            device.setGain(rx, channel, float(gain_db))
        except Exception as exc:
            measurements.append({"gain_db": float(gain_db), "error": str(exc)})
            continue

        # Let the gain settle and let new samples flow through the
        # pipeline. The first chunk read right after a gain change may
        # still contain old-gain samples, so drain once before measuring.
        time.sleep(max(0.0, float(settle_sec)))
        try:
            receiver.get_samples(num_samples=measure_samples)
        except Exception:
            pass

        stats = _measure_iq_levels(receiver, num_samples=measure_samples)
        if stats is None:
            measurements.append({"gain_db": float(gain_db), "error": "no samples available"})
            continue
        stats["gain_db"] = float(gain_db)
        measurements.append(stats)

    usable = [
        m for m in measurements
        if "rms_dbfs" in m and m.get("clipping_fraction", 1.0) <= clipping_threshold
    ]
    # When an external LNA is in front of the SDR, the digital RMS we
    # measure includes the LNA's gain.  The "leave headroom for FM
    # modulation peaks" rationale behind ``target_rms_dbfs`` is about
    # the SDR ADC — the LNA itself can be driven into compression long
    # before any single ADC sample saturates, because LNAs compress
    # softly above their P1dB point.  Tighten the headroom target by
    # half the LNA's contribution so the chosen SDR gain leaves the
    # same SDR-stage operating point regardless of LNA size.
    effective_target_dbfs = target_rms_dbfs - max(0.0, external_lna_db) * 0.5

    if usable:
        below_target = [m for m in usable if m["rms_dbfs"] <= effective_target_dbfs]
        if below_target:
            chosen = max(below_target, key=lambda m: m["gain_db"])
            decision = "headroom-target"
        else:
            chosen = max(usable, key=lambda m: m["gain_db"])
            decision = "highest-non-clipping"
    else:
        ok = [m for m in measurements if "rms_dbfs" in m]
        if not ok:
            if starting_gain is not None:
                try:
                    device.setGain(rx, channel, starting_gain)
                except Exception:
                    pass
            return {
                "command_id": command_id,
                "success": False,
                "error": "No usable IQ samples observed during sweep",
                "measurements": measurements,
            }
        chosen = min(ok, key=lambda m: m["gain_db"])
        decision = "fallback-lowest"

    chosen_gain = float(chosen["gain_db"])
    try:
        device.setGain(rx, channel, chosen_gain)
        applied = True
    except Exception as exc:
        applied = False
        logger.warning(
            "auto_gain: failed to apply selected gain %.1f dB for %s: %s",
            chosen_gain, receiver_id, exc,
        )
        if starting_gain is not None:
            try:
                device.setGain(rx, channel, starting_gain)
            except Exception:
                pass

    logger.info(
        "auto_gain: chose %.1f dB for %s (decision=%s, rms=%.1f dBFS, "
        "peak=%.1f dBFS, clip=%.2f%%, applied=%s)",
        chosen_gain, receiver_id, decision,
        chosen.get("rms_dbfs", float("nan")),
        chosen.get("peak_dbfs", float("nan")),
        chosen.get("clipping_fraction", 0.0) * 100.0,
        applied,
    )

    return {
        "command_id": command_id,
        "success": True,
        "applied": applied,
        "selected_gain_db": chosen_gain,
        "previous_gain_db": starting_gain,
        "decision": decision,
        "target_rms_dbfs": float(target_rms_dbfs),
        "effective_target_rms_dbfs": float(effective_target_dbfs),
        "external_lna_db": float(external_lna_db),
        "clipping_threshold": float(clipping_threshold),
        "measurements": measurements,
        "selected_measurement": chosen,
    }


@dataclass
class SDRServiceState:
    """Global state for the SDR service with thread-safe access via lock."""
    running: bool = True
    redis_client: Optional[Any] = None
    radio_manager: Optional[Any] = None
    publisher_thread: Optional[threading.Thread] = None
    flask_app: Optional[Any] = None  # Store Flask app for database access
    last_metrics_time: float = 0.0
    metrics_interval: float = 1.0  # Publish metrics every second
    # Per-receiver snapshot of total_samples_written at the last metrics
    # publish.  Used by publish_sdr_metrics() to derive a "samples flowing"
    # signal from the delta, since the instantaneous ring-buffer fill level
    # is ~0 immediately after the publisher thread drains it.
    prev_total_samples_written: Dict[str, int] = field(default_factory=dict)
    lock: threading.Lock = field(default_factory=threading.Lock)


_state = SDRServiceState()


def signal_handler(signum, frame):
    """Handle shutdown signals gracefully."""
    logger.info(f"Received signal {signum}, initiating graceful shutdown...")
    _state.running = False


def verify_soapysdr_installation():
    """Verify SoapySDR and NumPy are properly installed."""
    logger.info("Verifying SDR dependencies...")
    
    # Get Python version for diagnostics
    import sys
    python_version = f"{sys.version_info.major}.{sys.version_info.minor}"
    logger.info(f"Running Python {python_version}")

    # Check SoapySDR Python bindings
    try:
        import SoapySDR
        logger.info(f"✅ SoapySDR Python bindings installed (API version: {SoapySDR.getAPIVersion()})")
    except ImportError as e:
        logger.error("❌ SoapySDR Python bindings NOT installed")
        logger.error("")
        logger.error("=" * 80)
        logger.error("CRITICAL: SoapySDR Python bindings are missing")
        logger.error("=" * 80)
        logger.error("")
        
        # Python 3.13 specific guidance
        if sys.version_info.major == 3 and sys.version_info.minor >= 13:
            logger.error(f"⚠️  You are running Python {python_version}")
            logger.error("   The python3-soapysdr package may not be available for Python 3.13 yet.")
            logger.error("")
            logger.error("Solutions:")
            logger.error("  1. Check if python3-soapysdr is available for your Python version:")
            logger.error(f"     apt-cache policy python3-soapysdr")
            logger.error("")
            logger.error("  2. If not available, you need to build SoapySDR Python bindings from source:")
            logger.error("     # Install build dependencies")
            logger.error("     sudo apt-get install cmake g++ libpython3-dev swig")
            logger.error("     # Clone and build SoapySDR")
            logger.error("     git clone https://github.com/pothosware/SoapySDR.git")
            logger.error("     cd SoapySDR && mkdir build && cd build")
            logger.error(f"     cmake .. -DPYTHON3_EXECUTABLE=/usr/bin/python3")
            logger.error("     make -j4 && sudo make install")
            logger.error("     sudo ldconfig")
            logger.error("")
            logger.error("  3. Alternatively, downgrade to Python 3.11 or 3.12:")
            logger.error("     sudo apt-get install python3.12 python3.12-venv")
            logger.error("     Then reinstall EAS Station using Python 3.12")
        else:
            logger.error("Standard installation (Python 3.11/3.12):")
            logger.error("  1. Install the package:")
            logger.error("     sudo apt-get update")
            logger.error("     sudo apt-get install python3-soapysdr")
            logger.error("")
            logger.error("  2. Verify installation:")
            logger.error(f"     python{python_version} -c 'import SoapySDR; print(SoapySDR.getAPIVersion())'")
        
        logger.error("")
        logger.error("  3. Ensure PYTHONPATH includes system site-packages:")
        logger.error("     Run: sudo ./update.sh")
        logger.error("     This will configure PYTHONPATH for your Python version")
        logger.error("=" * 80)
        logger.error(f"   Error details: {e}")
        return False

    # Check NumPy
    try:
        import numpy as np
        logger.info(f"✅ NumPy installed (version: {np.__version__})")
    except ImportError as e:
        logger.error("❌ NumPy NOT installed")
        logger.error(f"   Error: {e}")
        return False

    # Test USB device enumeration
    try:
        devices = SoapySDR.Device.enumerate()
        logger.info(f"✅ USB device enumeration working ({len(devices)} device(s) found)")
        if devices:
            for idx, dev in enumerate(devices):
                dev_dict = dict(dev)
                driver = dev_dict.get('driver', 'unknown')
                serial = dev_dict.get('serial', 'N/A')
                logger.info(f"   Device {idx}: {driver} (serial: {serial})")
        else:
            logger.warning("⚠️  No SDR devices found - check USB connections and permissions")
    except Exception as e:
        logger.error(f"❌ USB device enumeration failed: {e}")
        logger.error("   Check USB permissions: devices=/dev/bus/usb, privileged=true")
        return False

    return True


def get_redis_client(retry=True):
    """Get or create Redis client with retry logic."""
    if _state.redis_client is not None:
        try:
            # Verify connection is still alive
            _state.redis_client.ping()
            return _state.redis_client
        except Exception:
            logger.warning("Redis connection lost, reconnecting...")
            _state.redis_client = None

    max_retries = 5 if retry else 1
    for attempt in range(max_retries):
        try:
            import redis

            # Use app_core redis client for robust connection handling
            from app_core.redis_client import get_redis_client as get_robust_client

            _state.redis_client = get_robust_client(
                max_retries=5,
                initial_backoff=1.0,
                max_backoff=30.0
            )
            logger.info(f"✅ Connected to Redis at {REDIS_HOST}:{REDIS_PORT}")
            return _state.redis_client
        except Exception as e:
            if attempt < max_retries - 1:
                wait_time = min(2 ** attempt, 30)
                logger.warning(f"Failed to connect to Redis (attempt {attempt + 1}/{max_retries}): {e}")
                logger.info(f"Retrying in {wait_time} seconds...")
                time.sleep(wait_time)
            else:
                logger.error(f"❌ Failed to connect to Redis after {max_retries} attempts: {e}")
                raise


def initialize_database():
    """Initialize database connection for receiver configuration with retry logic."""
    from app_core.extensions import db
    from flask import Flask

    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise ValueError("DATABASE_URL environment variable is required")

    # Log connection info without credentials (extract username@host:port/db from URL)
    import re
    match = re.match(r'postgresql.*://([^:]+):.*@([^:]+):(\d+)/(.+)', database_url)
    if match:
        user, host, port, db_name = match.groups()
        logger.info(f"Connecting to database: {user}@{host}:{port}/{db_name}")
    else:
        logger.info(f"Connecting to database with provided DATABASE_URL")

    # Retry database connection with exponential backoff
    max_retries = 10
    for attempt in range(max_retries):
        try:
            app = Flask(__name__)
            app.config["SQLALCHEMY_DATABASE_URI"] = database_url
            app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
            app.config["SQLALCHEMY_ECHO"] = False

            db.init_app(app)

            # Test connection by executing a simple query
            with app.app_context():
                from sqlalchemy import text
                db.session.execute(text("SELECT 1"))

            logger.info(f"✅ Database connection established")
            # Store app instance for later use (e.g., reload_receivers command)
            _state.flask_app = app
            return app

        except Exception as e:
            if attempt < max_retries - 1:
                wait_time = min(2 ** attempt, 30)
                logger.warning(f"Database connection failed (attempt {attempt + 1}/{max_retries}): {e}")
                logger.info(f"Retrying in {wait_time} seconds...")
                time.sleep(wait_time)
            else:
                logger.error(f"❌ Failed to connect to database after {max_retries} attempts")
                logger.error(f"   Error: {e}")
                raise


def _auto_detect_and_configure_receivers(app):
    """Auto-detect connected SDR devices and create receiver configurations.

    Called when no receivers are configured in the database. Discovers connected
    SDR hardware and creates default configurations for NOAA Weather Radio monitoring.

    Returns:
        List of RadioReceiver objects that were auto-configured, or empty list if none found.
    """
    from app_core.radio.discovery import enumerate_devices
    from app_core.models import RadioReceiver
    from app_core.extensions import db

    # Default NOAA Weather Radio frequency (WX7 - most common)
    DEFAULT_FREQUENCY_HZ = 162_550_000

    # Driver-specific defaults
    DRIVER_DEFAULTS = {
        'airspy': {
            'sample_rate': 2_500_000,  # Airspy R2 only supports 2.5 MHz or 10 MHz
            'gain': 21,
            'modulation_type': 'NFM',
            'audio_sample_rate': 48000,
        },
        'rtlsdr': {
            'sample_rate': 2_400_000,
            'gain': 49.6,
            'modulation_type': 'NFM',
            'audio_sample_rate': 48000,
        },
        'hackrf': {
            'sample_rate': 2_000_000,
            'gain': 40,
            'modulation_type': 'NFM',
            'audio_sample_rate': 48000,
        },
    }

    try:
        devices = enumerate_devices()
        if not devices:
            logger.info("📡 Auto-detection: No SDR devices found")
            return []

        logger.info(f"📡 Auto-detection: Found {len(devices)} device(s)")

        configured_receivers = []

        # Note: We're already inside an app context from initialize_radio_receivers
        for device in devices:
            driver = device.get('driver', 'unknown').lower()
            serial = device.get('serial')
            label = device.get('label', f'SDR Device')

            if not serial:
                logger.warning(f"  Skipping device without serial: {label}")
                continue

            # Check if already configured (by serial)
            existing = RadioReceiver.query.filter_by(serial=serial).first()
            if existing:
                logger.info(f"  Device {serial} already configured as '{existing.identifier}'")
                if existing.enabled:
                    configured_receivers.append(existing)
                continue

            # Get driver-specific defaults
            defaults = DRIVER_DEFAULTS.get(driver, {
                'sample_rate': 2_400_000,
                'gain': 30,
                'modulation_type': 'NFM',
                'audio_sample_rate': 48000,
            })

            # Create unique identifier
            identifier = f"{driver}-{serial[-8:]}" if len(serial) > 8 else f"{driver}-{serial}"
            display_name = f"{label} (Auto-configured)"

            logger.info(f"  📻 Auto-configuring: {identifier}")
            logger.info(f"     Driver: {driver}, Serial: {serial}")
            logger.info(f"     Frequency: {DEFAULT_FREQUENCY_HZ / 1e6:.3f} MHz (NOAA WX7)")
            logger.info(f"     Sample rate: {defaults['sample_rate'] / 1e6:.1f} MHz")

            # Create receiver configuration
            receiver = RadioReceiver(
                identifier=identifier,
                display_name=display_name,
                driver=driver,
                serial=serial,
                frequency_hz=DEFAULT_FREQUENCY_HZ,
                sample_rate=defaults['sample_rate'],
                audio_sample_rate=defaults.get('audio_sample_rate', 48000),
                gain=defaults.get('gain'),
                modulation_type=defaults.get('modulation_type', 'NFM'),
                audio_output=True,
                enabled=True,
                auto_start=True,
                notes=f"Auto-configured on {time.strftime('%Y-%m-%d %H:%M:%S')}. "
                      f"Tune frequency in Settings → Radio Receivers for your area.",
            )

            db.session.add(receiver)
            configured_receivers.append(receiver)

        if configured_receivers:
            db.session.commit()
            logger.info(f"✅ Auto-configured {len(configured_receivers)} receiver(s)")

            # Publish status to Redis
            try:
                redis_client = get_redis_client(retry=False)
                redis_client.setex(
                    "sdr:status",
                    300,
                    json.dumps({
                        "status": "auto_configured",
                        "message": f"Auto-configured {len(configured_receivers)} receiver(s)",
                        "receivers": [r.identifier for r in configured_receivers],
                        "timestamp": time.time()
                    })
                )
            except Exception:
                pass

        return configured_receivers

    except Exception as e:
        logger.error(f"Auto-detection failed: {e}", exc_info=True)
        return []


def initialize_radio_receivers(app):
    """Initialize and start SDR receivers from database configuration."""
    try:
        with app.app_context():
            from app_core.models import RadioReceiver
            from app_core.extensions import get_radio_manager, db

            receivers = RadioReceiver.query.filter_by(enabled=True).all()
            if not receivers:
                # No receivers configured - try auto-detection
                logger.info("No receivers configured - attempting auto-detection...")
                receivers = _auto_detect_and_configure_receivers(app)

            if not receivers:
                logger.error("=" * 80)
                logger.error("❌ NO SDR RECEIVERS CONFIGURED OR DETECTED")
                logger.error("=" * 80)
                logger.error("The SDR service will run but will NOT receive any radio signals.")
                logger.error("")
                logger.error("To configure receivers:")
                logger.error("  1. Go to the web interface: Settings → Radio Receivers")
                logger.error("  2. Add at least one receiver configuration")
                logger.error("  3. Enable the receiver and set auto_start=true")
                logger.error("  4. Restart the SDR hardware service process")
                logger.error("")
                logger.error("Or connect an SDR device (Airspy, RTL-SDR) and restart the service.")
                logger.error("The service will continue running and wait for configuration via")
                logger.error("the 'reload_receivers' command through Redis.")
                logger.error("=" * 80)

                # Publish warning status to Redis so UI can show alert
                try:
                    redis_client = get_redis_client(retry=False)
                    redis_client.setex(
                        "sdr:status",
                        300,  # 5 minute TTL
                        json.dumps({
                            "status": "no_receivers_configured",
                            "message": "No SDR receivers configured or detected",
                            "timestamp": time.time()
                        })
                    )
                except Exception:
                    pass  # Don't fail if Redis publish fails

                return None

            radio_manager = get_radio_manager()
            _state.radio_manager = radio_manager

            radio_manager.configure_from_records(receivers)
            logger.info(f"Configured {len(receivers)} radio receiver(s) from database")

            auto_start = [r for r in receivers if r.auto_start]
            if auto_start:
                radio_manager.start_all()
                logger.info(f"✅ Started {len(auto_start)} receiver(s) with auto_start")
            else:
                logger.warning("⚠️  No receivers have auto_start enabled - they must be started manually")

            return radio_manager

    except Exception as exc:
        logger.error(f"❌ Failed to initialize radio receivers: {exc}", exc_info=True)
        raise


def compute_spectrum(samples, numpy_module) -> Optional[list]:
    """Compute normalized spectrum from IQ samples."""
    try:
        if len(samples) < FFT_SIZE:
            return None
        
        # Remove DC offset
        samples_slice = samples[:FFT_SIZE]
        samples_centered = samples_slice - numpy_module.mean(samples_slice)
        
        # Apply window and compute FFT
        window = numpy_module.hanning(FFT_SIZE)
        windowed = samples_centered * window
        fft_result = numpy_module.fft.fftshift(numpy_module.fft.fft(windowed))
        
        # Convert to magnitude (dB)
        magnitude = numpy_module.abs(fft_result)
        magnitude = numpy_module.where(magnitude > 0, magnitude, FFT_MIN_MAGNITUDE)
        magnitude_db = 20 * numpy_module.log10(magnitude)
        
        # Normalize to 0-1 range
        normalized = numpy_module.clip(
            (magnitude_db - SPECTRUM_DB_MIN) / (SPECTRUM_DB_MAX - SPECTRUM_DB_MIN),
            0.0, 1.0
        )
        
        return normalized.tolist()
    except Exception as e:
        logger.debug(f"Spectrum computation error: {e}")
        return None


def publish_samples_and_metrics():
    """Publisher thread: reads from receivers and publishes to Redis."""
    logger.info("Sample publisher thread started")
    
    try:
        import numpy as np
        import base64
        import zlib
    except ImportError:
        logger.error("NumPy not available, cannot publish samples")
        return
    
    redis_client = get_redis_client()
    last_spectrum_time = {}  # Per-receiver spectrum update tracking
    spectrum_interval = 0.1  # 100ms spectrum updates
    
    while _state.running:
        try:
            radio_manager = _state.radio_manager
            if radio_manager is None or not hasattr(radio_manager, '_receivers'):
                time.sleep(0.1)
                continue
            
            current_time = time.time()
            
            for identifier, receiver in radio_manager._receivers.items():
                try:
                    # Check if receiver is running
                    is_running = receiver._running.is_set() if hasattr(receiver, '_running') else False
                    if not is_running:
                        continue
                    
                    # Get samples from receiver
                    if hasattr(receiver, 'get_samples'):
                        # Size the read by *duration*, not a fixed sample
                        # count, so receivers with low effective rates
                        # (e.g. Airspy at 250 kHz after early decimation)
                        # don't emit one fat 131 ms blob per message.
                        # See SDR_SAMPLE_CHUNK_DURATION_SEC docstring.
                        if hasattr(receiver, 'get_effective_sample_rate'):
                            try:
                                effective_rate_for_chunk = int(receiver.get_effective_sample_rate())
                            except Exception:
                                effective_rate_for_chunk = int(receiver.config.sample_rate)
                        else:
                            effective_rate_for_chunk = int(receiver.config.sample_rate)
                        target_chunk = int(effective_rate_for_chunk * SDR_SAMPLE_CHUNK_DURATION_SEC)
                        chunk_samples = max(
                            SDR_SAMPLE_CHUNK_MIN,
                            min(SDR_SAMPLE_CHUNK_SIZE, target_chunk),
                        )
                        samples = receiver.get_samples(num_samples=chunk_samples)
                        
                        if samples is not None and len(samples) > 0:
                            # Tap samples into any in-flight capture for this
                            # receiver BEFORE the rest of the publish pipeline.
                            # The publisher already drains the ring buffer in
                            # real-time, so this is the only place where a
                            # second consumer can observe every sample without
                            # racing the first.
                            _capture_tap_append(identifier, samples)

                            # Publish IQ samples to Redis channel
                            # Use compressed base64 encoding for efficiency
                            # Complex samples are interleaved as [real, imag, real, imag, ...]
                            interleaved = np.empty(len(samples) * 2, dtype=np.float32)
                            interleaved[0::2] = samples.real
                            interleaved[1::2] = samples.imag
                            compressed = zlib.compress(interleaved.tobytes(), level=1)  # Fast compression
                            encoded = base64.b64encode(compressed).decode('ascii')
                            
                            # Get effective sample rate (after early decimation for high-rate SDRs)
                            if hasattr(receiver, 'get_effective_sample_rate'):
                                effective_rate = receiver.get_effective_sample_rate()
                            else:
                                effective_rate = receiver.config.sample_rate

                            sample_data = {
                                'receiver_id': identifier,
                                'timestamp': current_time,
                                'sample_count': len(samples),
                                'sample_rate': effective_rate,  # Use effective rate after decimation
                                'center_frequency': receiver.config.frequency_hz,
                                'encoding': 'zlib+base64',  # Indicate encoding method
                                'samples': encoded,
                            }
                            
                            redis_client.publish(
                                f"{SDR_SAMPLE_CHANNEL}:{identifier}",
                                json.dumps(sample_data)
                            )
                            
                            # Compute and publish spectrum (rate-limited)
                            # Note: Spectrum computed from decimated samples, so uses effective rate
                            last_time = last_spectrum_time.get(identifier, 0)
                            if current_time - last_time >= spectrum_interval:
                                spectrum = compute_spectrum(samples, np)
                                if spectrum is not None:
                                    spectrum_payload = {
                                        'identifier': identifier,
                                        'spectrum': spectrum,
                                        'fft_size': FFT_SIZE,
                                        'sample_rate': effective_rate,  # Use effective rate for decimated samples
                                        'center_frequency': receiver.config.frequency_hz,
                                        'timestamp': current_time,
                                        'status': 'available'
                                    }
                                    redis_client.setex(
                                        f"{SDR_SPECTRUM_KEY_PREFIX}{identifier}",
                                        5,  # 5 second TTL
                                        json.dumps(spectrum_payload)
                                    )
                                last_spectrum_time[identifier] = current_time
                    
                    # Get and publish ring buffer stats if available
                    if hasattr(receiver, 'get_ring_buffer_stats'):
                        ring_stats = receiver.get_ring_buffer_stats()
                        if ring_stats:
                            redis_client.hset(
                                f"sdr:ring_buffer:{identifier}",
                                mapping={k: json.dumps(v) if isinstance(v, (dict, list)) else str(v)
                                        for k, v in ring_stats.items()}
                            )
                            redis_client.expire(f"sdr:ring_buffer:{identifier}", 10)
                
                except Exception as e:
                    logger.debug(f"Error publishing for receiver {identifier}: {e}")
            
            # Publish aggregated metrics periodically
            if current_time - _state.last_metrics_time >= _state.metrics_interval:
                publish_sdr_metrics(redis_client)
                _state.last_metrics_time = current_time
            
            # Adaptive sleep based on buffer status
            # Sleep less when buffers are filling up, more when they're low
            sleep_time_ms = PUBLISHER_SLEEP_MAX_MS
            if radio_manager and hasattr(radio_manager, '_receivers'):
                for receiver in radio_manager._receivers.values():
                    if hasattr(receiver, 'get_ring_buffer_stats'):
                        stats = receiver.get_ring_buffer_stats()
                        if stats and stats.get('fill_percentage', 0) > 50:
                            # Buffer filling up, reduce sleep time
                            sleep_time_ms = PUBLISHER_SLEEP_MIN_MS
                            break
            time.sleep(sleep_time_ms / 1000.0)
            
        except Exception as e:
            logger.error(f"Publisher thread error: {e}", exc_info=True)
            time.sleep(1.0)
    
    logger.info("Sample publisher thread exiting")


def publish_sdr_metrics(redis_client):
    """Publish aggregated SDR health metrics to Redis."""
    try:
        radio_manager = _state.radio_manager
        if radio_manager is None:
            return
        
        metrics = {
            'service': 'sdr_service',
            'timestamp': time.time(),
            'pid': os.getpid(),
            'receivers': {}
        }
        
        if hasattr(radio_manager, '_receivers'):
            for identifier, receiver in radio_manager._receivers.items():
                try:
                    status = receiver.get_status()
                    is_running = receiver._running.is_set() if hasattr(receiver, '_running') else False

                    # Determine whether samples are actively flowing.
                    #
                    # The instantaneous ring-buffer fill_level is misleading
                    # here: the publisher thread above drains the ring buffer
                    # on every iteration (via receiver.get_samples()), so by
                    # the time we read stats the fill level is ~0 even on a
                    # perfectly healthy receiver.  That produced the "No
                    # samples" / "Sample Buffer: Not available" badge on the
                    # SDR Diagnostics dashboard while the downstream RBDS
                    # decoder was simultaneously reporting a healthy score and
                    # thousands of group counts on the very same stream.
                    #
                    # The non-destructive signal is total_samples_written
                    # (a monotonic counter the ring buffer increments inside
                    # write()).  If it has grown since the previous metrics
                    # publish, samples are flowing.
                    fill_level = 0
                    total_written = 0
                    samples_available = False
                    if hasattr(receiver, 'get_ring_buffer_stats'):
                        try:
                            ring_stats = receiver.get_ring_buffer_stats()
                            if ring_stats:
                                fill_level = int(ring_stats.get('samples_available', 0) or 0)
                                total_written = int(ring_stats.get('total_samples_written', 0) or 0)
                        except Exception:
                            pass

                    prev_written = _state.prev_total_samples_written.get(identifier, 0)
                    if total_written < prev_written:
                        # Counter went backwards — receiver was restarted /
                        # re-opened and its ring buffer reset.  Don't clamp
                        # the delta to 0 (that would falsely report "No
                        # samples" for one interval); instead resync the
                        # snapshot and use the fill_level fallback below.
                        delta_written = 0
                        prev_written = 0
                    else:
                        delta_written = total_written - prev_written
                    if total_written > 0:
                        _state.prev_total_samples_written[identifier] = total_written

                    if delta_written > 0:
                        # Samples have been written to the ring buffer since
                        # the last metrics publish — the SDR is producing.
                        samples_available = True
                        sample_count = delta_written
                    elif fill_level > 0:
                        # Producer counter unavailable (e.g. simple buffer
                        # fallback path that hard-codes total_samples_written
                        # to 0) — fall back to the instantaneous level.
                        samples_available = True
                        sample_count = fill_level
                    else:
                        sample_count = 0

                    # Build config object (webapp expects nested structure)
                    config = {
                        'frequency_hz': receiver.config.frequency_hz,
                        'sample_rate': receiver.config.sample_rate,
                        'driver': receiver.config.driver,
                        'modulation_type': receiver.config.modulation_type if hasattr(receiver.config, 'modulation_type') else None,
                    }

                    receiver_metrics = {
                        'running': is_running,
                        'locked': status.locked,
                        'signal_strength': float(status.signal_strength) if status.signal_strength else 0.0,
                        'last_error': status.last_error,
                        'samples_available': samples_available,
                        'sample_count': sample_count,
                        'reported_at': time.time(),
                        'config': config,
                    }

                    # Add ring buffer stats if available
                    if hasattr(receiver, 'get_ring_buffer_stats'):
                        ring_stats = receiver.get_ring_buffer_stats()
                        if ring_stats:
                            receiver_metrics['ring_buffer'] = ring_stats

                    # Add connection health if available
                    if hasattr(receiver, 'get_connection_health'):
                        health = receiver.get_connection_health()
                        if health:
                            receiver_metrics['connection_health'] = health

                    metrics['receivers'][identifier] = receiver_metrics
                    
                except Exception as e:
                    logger.debug(f"Error getting metrics for {identifier}: {e}")
        
        # Publish to Redis
        redis_client.setex(
            SDR_METRICS_KEY,
            30,  # 30 second TTL
            json.dumps(metrics)
        )
        
        # Also publish heartbeat
        redis_client.setex(
            "sdr:heartbeat",
            10,
            json.dumps({
                'timestamp': time.time(),
                'pid': os.getpid(),
                'receiver_count': len(metrics.get('receivers', {}))
            })
        )
        
    except Exception as e:
        logger.error(f"Error publishing SDR metrics: {e}")


def process_commands(redis_client):
    """Process control commands from Redis."""
    try:
        command_json = redis_client.lpop("sdr:commands")
        if not command_json:
            return
        
        command = json.loads(command_json)
        action = command.get("action")
        receiver_id = command.get("receiver_id")
        command_id = command.get("command_id", "unknown")
        
        logger.info(f"Processing command: {action} for {receiver_id}")

        # Handle actions that don't require radio_manager first
        if action == "discover_devices":
            # Enumerate all connected SoapySDR devices
            try:
                from app_core.radio.discovery import enumerate_devices
                devices = enumerate_devices()
                if devices:
                    logger.info(f"📡 Device discovery found {len(devices)} device(s):")
                    for dev in devices:
                        driver = dev.get('driver', 'unknown')
                        serial = dev.get('serial', 'N/A')
                        label = dev.get('label', 'Unknown')
                        logger.info(f"   - {driver}: {label} (serial={serial})")
                else:
                    logger.warning("📡 Device discovery: No SDR devices found. Check USB connections and permissions.")
                result = {
                    "command_id": command_id,
                    "success": True,
                    "devices": devices,
                    "count": len(devices)
                }
            except Exception as e:
                logger.error(f"Failed to enumerate devices: {e}")
                result = {
                    "command_id": command_id,
                    "success": False,
                    "error": str(e),
                    "devices": []
                }
        elif action == "reload_receivers":
            # Reload receiver configuration from database
            # This is called when receivers are added/updated/deleted via webapp
            try:
                from app_core.models import RadioReceiver
                from app_core.extensions import get_radio_manager

                # Get the Flask app instance (stored during initialization)
                # This ensures proper database session management
                if not _state.flask_app:
                    raise RuntimeError("Flask app not initialized - cannot reload receivers")

                with _state.flask_app.app_context():
                    receivers = RadioReceiver.query.filter_by(enabled=True).all()

                    radio_manager = _state.radio_manager
                    if not radio_manager:
                        radio_manager = get_radio_manager()
                        _state.radio_manager = radio_manager

                    # Stop all existing receivers
                    if hasattr(radio_manager, '_receivers'):
                        for identifier in list(radio_manager._receivers.keys()):
                            try:
                                receiver = radio_manager.get_receiver(identifier)
                                if receiver:
                                    receiver.stop()
                            except Exception as e:
                                logger.warning(f"Error stopping receiver {identifier}: {e}")

                    # Reconfigure from database
                    radio_manager.configure_from_records(receivers)
                    logger.info(f"Reloaded {len(receivers)} receiver(s) from database")

                    # Auto-start enabled receivers
                    auto_start_count = 0
                    for r in receivers:
                        if r.auto_start:
                            instance = radio_manager.get_receiver(r.identifier)
                            if instance:
                                try:
                                    instance.start()
                                    auto_start_count += 1
                                except Exception as e:
                                    logger.error(f"Failed to auto-start {r.identifier}: {e}")

                    result = {
                        "command_id": command_id,
                        "success": True,
                        "receivers_configured": len(receivers),
                        "receivers_started": auto_start_count
                    }
            except Exception as e:
                logger.error(f"Failed to reload receivers: {e}", exc_info=True)
                result = {
                    "command_id": command_id,
                    "success": False,
                    "error": str(e)
                }
        else:
            # Actions below require radio_manager to be initialized
            radio_manager = _state.radio_manager
            if not radio_manager:
                result = {
                    "command_id": command_id,
                    "success": False,
                    "error": "Radio manager not initialized"
                }
            elif action == "restart":
                receiver = radio_manager.get_receiver(receiver_id)
                if receiver:
                    try:
                        receiver.stop()
                        time.sleep(0.5)
                        receiver.start()
                        status = {
                            "locked": getattr(receiver, 'locked', False),
                            "signal_strength": getattr(receiver, 'signal_strength', 0),
                            "running": getattr(receiver, 'running', False)
                        }
                        result = {
                            "command_id": command_id,
                            "success": True,
                            "message": f"Receiver {receiver_id} restarted",
                            "status": status
                        }
                    except Exception as e:
                        result = {
                            "command_id": command_id,
                            "success": False,
                            "error": str(e)
                        }
                else:
                    result = {
                        "command_id": command_id,
                        "success": False,
                        "error": f"Receiver {receiver_id} not found"
                    }
            elif action == "tune_frequency":
                # Live retune of an active receiver — does NOT stop the stream
                # so the audio system keeps decoding without interruption.
                # On failure the webapp can fall back to reload_receivers.
                receiver = radio_manager.get_receiver(receiver_id)
                if not receiver:
                    result = {
                        "command_id": command_id,
                        "success": False,
                        "error": f"Receiver {receiver_id} not found",
                    }
                else:
                    freq_hz = command.get("frequency_hz")
                    try:
                        freq_hz = float(freq_hz) if freq_hz is not None else None
                    except (TypeError, ValueError):
                        freq_hz = None
                    if freq_hz is None or freq_hz <= 0:
                        result = {
                            "command_id": command_id,
                            "success": False,
                            "error": "frequency_hz is required and must be positive",
                        }
                    else:
                        try:
                            tuned = receiver.set_frequency(freq_hz)
                        except Exception as e:
                            logger.error(
                                "tune_frequency failed for %s: %s",
                                receiver_id, e, exc_info=True,
                            )
                            tuned = False
                        if tuned:
                            # Persist to database so a future restart keeps the tune.
                            try:
                                if _state.flask_app:
                                    with _state.flask_app.app_context():
                                        from app_core.models import RadioReceiver
                                        from app_core.extensions import db
                                        row = RadioReceiver.query.filter_by(
                                            identifier=receiver_id
                                        ).first()
                                        if row is not None:
                                            row.frequency_hz = freq_hz
                                            db.session.commit()
                            except Exception as e:
                                logger.warning(
                                    "tune_frequency: retune ok but DB update failed for %s: %s",
                                    receiver_id, e,
                                )
                            result = {
                                "command_id": command_id,
                                "success": True,
                                "frequency_hz": freq_hz,
                                "live": True,
                            }
                        else:
                            # Driver can't live-retune (or device not running) —
                            # caller should fall back to reload_receivers.
                            result = {
                                "command_id": command_id,
                                "success": False,
                                "live": False,
                                "error": (
                                    "Live retune not supported or device not running; "
                                    "caller should fall back to reload_receivers"
                                ),
                            }
            elif action == "stop":
                receiver = radio_manager.get_receiver(receiver_id)
                if receiver:
                    receiver.stop()
                    result = {"command_id": command_id, "success": True}
                else:
                    result = {"command_id": command_id, "success": False, "error": "Not found"}
            elif action == "start":
                receiver = radio_manager.get_receiver(receiver_id)
                if receiver:
                    receiver.start()
                    result = {"command_id": command_id, "success": True}
                else:
                    result = {"command_id": command_id, "success": False, "error": "Not found"}
            elif action == "get_spectrum":
                # Get spectrum data for waterfall display
                receiver = radio_manager.get_receiver(receiver_id)
                if not receiver:
                    result = {
                        "command_id": command_id,
                        "success": False,
                        "error": f"Receiver '{receiver_id}' not found"
                    }
                else:
                    try:
                        num_samples = command.get("num_samples", 2048)
                        iq_samples = receiver.get_samples(num_samples=num_samples)

                        if iq_samples is None or len(iq_samples) == 0:
                            result = {
                                "command_id": command_id,
                                "success": False,
                                "error": "No samples available from receiver"
                            }
                        else:
                            # Convert complex samples to list of [real, imag] pairs
                            samples_list = [[float(s.real), float(s.imag)] for s in iq_samples[:num_samples]]
                            result = {
                                "command_id": command_id,
                                "success": True,
                                "samples": samples_list,
                                "num_samples": len(samples_list)
                            }
                    except Exception as e:
                        logger.error(f"Failed to get spectrum for receiver {receiver_id}: {e}")
                        result = {
                            "command_id": command_id,
                            "success": False,
                            "error": str(e)
                        }
            elif action == "capture_iq":
                # Capture raw IQ samples to a .npy file on disk for offline
                # analysis (rbds_diagnose.py, inspectrum, etc.). The web layer
                # triggers this and then streams the resulting file back to the
                # browser via /api/radio/diagnostics/capture/<id>/download.
                #
                # Implementation note: the SDR producer is real-time, so we
                # cannot pull N seconds of samples in a single call. Instead
                # we register a tap with the publisher thread (which already
                # drains the ring buffer continuously) and wait wall-clock
                # ~= duration for it to deliver exactly the requested count.
                receiver = radio_manager.get_receiver(receiver_id)
                if not receiver:
                    result = {
                        "command_id": command_id,
                        "success": False,
                        "error": f"Receiver '{receiver_id}' not found"
                    }
                else:
                    try:
                        import numpy as np

                        effective_rate = int(
                            getattr(receiver, "_effective_sample_rate", None)
                            or getattr(receiver, "sample_rate", 0)
                            or 250_000
                        )

                        requested = int(command.get("num_samples", 0) or 0)
                        if requested <= 0:
                            # Default: ~1 second at the receiver's effective rate.
                            requested = effective_rate
                        num_samples = min(requested, RADIO_CAPTURE_MAX_SAMPLES)

                        # Set up the tap entry the publisher will fill.
                        entry: Dict[str, Any] = {
                            "target_samples": int(num_samples),
                            "collected": 0,
                            "chunks": [],
                            "done": False,
                            "event": threading.Event(),
                            "started_at": time.time(),
                            "error": None,
                            "command_id": command_id,
                        }
                        with _active_captures_lock:
                            # Cancel any previous capture for the same
                            # identifier so a stuck one cannot block a new
                            # request indefinitely.
                            prior = _active_captures.get(receiver_id)
                            if prior is not None:
                                prior["done"] = True
                                prior_event = prior.get("event")
                                if prior_event is not None:
                                    prior_event.set()
                            _active_captures[receiver_id] = entry

                        # Wait for the publisher to deliver every sample,
                        # bounded by duration + slack. Real-time capture
                        # so the wall-clock budget is roughly the requested
                        # duration plus a generous slack for jitter.
                        duration_sec = num_samples / max(effective_rate, 1)
                        wait_budget = duration_sec + RADIO_CAPTURE_WALLCLOCK_SLACK_SEC
                        logger.info(
                            "📼 capture_iq registered tap for %s: %d samples "
                            "(~%.2fs @ %d Hz, wait budget %.1fs)",
                            receiver_id, num_samples, duration_sec,
                            effective_rate, wait_budget,
                        )
                        completed = entry["event"].wait(timeout=wait_budget)

                        # Detach the tap regardless of outcome so the
                        # publisher stops appending to this entry.
                        with _active_captures_lock:
                            if _active_captures.get(receiver_id) is entry:
                                del _active_captures[receiver_id]
                            entry["done"] = True

                        if entry.get("error"):
                            result = {
                                "command_id": command_id,
                                "success": False,
                                "error": entry["error"],
                            }
                        elif entry["collected"] == 0:
                            result = {
                                "command_id": command_id,
                                "success": False,
                                "error": (
                                    "No samples delivered by publisher tap "
                                    f"within {wait_budget:.1f}s — is the "
                                    "receiver running?"
                                ),
                            }
                        else:
                            chunks = entry["chunks"]
                            if len(chunks) == 1:
                                samples_array = np.ascontiguousarray(
                                    chunks[0], dtype=np.complex64
                                )
                            else:
                                samples_array = np.concatenate(chunks).astype(
                                    np.complex64, copy=False
                                )
                            actual = int(samples_array.size)
                            if not completed:
                                logger.warning(
                                    "capture_iq tap for %s timed out: "
                                    "collected %d / %d samples in %.1fs",
                                    receiver_id, actual, num_samples,
                                    wait_budget,
                                )

                            frequency_hz = int(
                                getattr(receiver, "frequency_hz", 0) or 0
                            )

                            # Capture-time provenance.  Recording the active
                            # SDR gain, the configured external LNA, and the
                            # bias-T state inside a JSON sidecar lets offline
                            # analysis answer "was the front end correctly
                            # gained when this was taken?" without guessing
                            # from IQ levels.
                            capture_gain_db: Optional[float] = None
                            try:
                                rx_handle = getattr(receiver, "_handle", None)
                                rx_config = getattr(receiver, "config", None)
                                rx_channel = (
                                    getattr(rx_config, "channel", 0)
                                    if rx_config is not None else 0
                                ) or 0
                                if (
                                    rx_handle is not None
                                    and hasattr(rx_handle, "device")
                                    and hasattr(rx_handle, "sdr")
                                ):
                                    capture_gain_db = float(
                                        rx_handle.device.getGain(
                                            rx_handle.sdr.SOAPY_SDR_RX,
                                            rx_channel,
                                        )
                                    )
                            except Exception:
                                capture_gain_db = None

                            try:
                                capture_external_lna_db = float(
                                    getattr(
                                        getattr(receiver, "config", None),
                                        "external_lna_db",
                                        0.0,
                                    ) or 0.0
                                )
                            except (TypeError, ValueError):
                                capture_external_lna_db = 0.0

                            capture_bias_t = bool(
                                getattr(
                                    getattr(receiver, "config", None),
                                    "bias_t_enabled",
                                    False,
                                )
                            )

                            os.makedirs(RADIO_CAPTURE_DIR, exist_ok=True)
                            safe_receiver_id = "".join(
                                ch if ch.isalnum() or ch in ("-", "_") else "_"
                                for ch in str(receiver_id)
                            )[:64] or "receiver"
                            # .npz — numpy zip archive holding both the raw IQ
                            # and the FM-demodulated multiplex in one file.
                            # Load with: data = np.load(f); iq = data['iq'];
                            #            multiplex = data['multiplex']
                            filename = (
                                f"iq_{safe_receiver_id}_"
                                f"{effective_rate}Hz_"
                                f"{int(time.time())}_{command_id[:8]}.npz"
                            )
                            output_path = os.path.join(RADIO_CAPTURE_DIR, filename)

                            # ── Compute multiplex + spectral diagnostics ──
                            # Done before the sidecar write so the spectral
                            # results can be embedded in the JSON at the same
                            # time the .npz is written.
                            spectral, multiplex_array = (
                                _compute_capture_spectral_diagnostics(
                                    samples_array, effective_rate
                                )
                            )

                            # Save both arrays in a single .npz archive.
                            # 'iq'        — complex64, post-hardware-IF-filter,
                            #               post-early-decim (if any). No FM
                            #               demodulation applied.
                            # 'multiplex' — float32, FM discriminator output
                            #               (rad/sample). Same signal the RBDS
                            #               worker sees. If 57 kHz is absent
                            #               here but present in 'iq', the fault
                            #               is in the software FM discriminator.
                            save_kwargs: Dict[str, Any] = {
                                "iq": samples_array,
                            }
                            if multiplex_array is not None:
                                save_kwargs["multiplex"] = multiplex_array
                            np.savez(output_path, **save_kwargs)

                            sidecar_path = output_path + ".json"
                            try:
                                cfg = getattr(receiver, "config", None)

                                # ── Hardware sample rate (before any software
                                # decimation).  The tap fires *after* the early
                                # decimation FIR that high-rate SDRs (Airspy
                                # 10 MHz) use to reduce data to ~250 kHz, so
                                # sample_rate == effective_rate for all current
                                # captures.  We record both so it is obvious
                                # when they differ.
                                hw_sample_rate = int(
                                    getattr(cfg, "sample_rate", effective_rate)
                                    or effective_rate
                                )
                                early_decim = int(
                                    getattr(receiver, "_early_decim_factor", 1) or 1
                                )

                                # ── Signal path note ─────────────────────────
                                # The capture tap fires in publish_samples_and_metrics
                                # immediately after receiver.get_samples().
                                # get_samples() returns IQ that has already passed
                                # through the early-decimation anti-alias FIR (if
                                # early_decim_factor > 1) and the hardware IF
                                # analogue filter set by setBandwidth().  No FM
                                # demodulation or audio processing has been applied.
                                # All software RBDS / audio filters run downstream
                                # in eas_monitoring_service, NOT in this file.
                                signal_path = (
                                    "post_hardware_if_filter"
                                    if early_decim == 1
                                    else "post_hardware_if_filter+post_early_decim_fir"
                                )

                                # ── Frequency correction applied ─────────────
                                ppm = float(
                                    getattr(cfg, "frequency_correction_ppm", 0.0) or 0.0
                                )
                                applied_offset_hz = (
                                    round(frequency_hz * ppm / 1_000_000.0, 3)
                                    if ppm else 0.0
                                )

                                # ── Hardware-accepted analogue bandwidth ──────
                                hw_bw = getattr(receiver, "_hardware_bandwidth_hz", None)

                                # ── Demodulator / RBDS config ─────────────────
                                modulation = str(
                                    getattr(cfg, "modulation_type", None) or "unknown"
                                ).upper()
                                rbds_enabled = bool(
                                    getattr(cfg, "enable_rbds", False)
                                )
                                stereo_enabled = bool(
                                    getattr(cfg, "stereo_enabled", False)
                                )
                                deemphasis_us = float(
                                    getattr(cfg, "deemphasis_us", 75.0) or 75.0
                                )
                                driver = str(
                                    getattr(cfg, "driver", None) or "unknown"
                                )
                                channel_index = int(
                                    getattr(cfg, "channel_index", 0) or 0
                                )

                                # ── Spectral diagnostics (best-effort) ────────
                                # Already computed above; embedded here.

                                sidecar = {
                                    # ── Identity / timing ─────────────────────
                                    "receiver_id": str(receiver_id),
                                    "command_id": command_id,
                                    "captured_at_unix": int(time.time()),

                                    # ── Signal provenance ──────────────────────
                                    # Explains exactly what processing has (and
                                    # has not) been applied to these samples.
                                    "signal_path": signal_path,
                                    "signal_path_note": (
                                        "IQ captured after hardware IF analogue filter "
                                        "and (if early_decim_factor>1) software anti-alias "
                                        "FIR decimation. FM demodulation, RBDS, and audio "
                                        "filters have NOT been applied."
                                    ),

                                    # ── Sample geometry ────────────────────────
                                    "dtype": "complex64",
                                    "num_samples": int(actual),
                                    "duration_sec": actual / max(effective_rate, 1),

                                    # ── Frequency ──────────────────────────────
                                    "frequency_hz": int(frequency_hz),
                                    "frequency_correction_ppm": ppm,
                                    "applied_frequency_offset_hz": applied_offset_hz,

                                    # ── Sample rates ───────────────────────────
                                    "sample_rate": int(effective_rate),
                                    "hardware_sample_rate": hw_sample_rate,
                                    "early_decim_factor": early_decim,

                                    # ── Hardware analogue IF bandwidth ─────────
                                    # The value setBandwidth() asked for equals
                                    # hardware_sample_rate.  hardware_bandwidth_hz
                                    # is what the tuner actually accepted (e.g.
                                    # R820T2 rounds to discrete steps).  A value
                                    # much narrower than sample_rate/2 will roll
                                    # off the FM multiplex before 57 kHz and
                                    # silently kill RBDS even though Nyquist looks
                                    # fine on paper.
                                    "requested_bandwidth_hz": hw_sample_rate,
                                    "hardware_bandwidth_hz": hw_bw,

                                    # ── RF gain chain ──────────────────────────
                                    "gain_db": capture_gain_db,
                                    "external_lna_db": capture_external_lna_db,
                                    "bias_t_enabled": capture_bias_t,

                                    # ── Driver / hardware ──────────────────────
                                    "driver": driver,
                                    "channel_index": channel_index,

                                    # ── Demodulator config ─────────────────────
                                    "modulation_type": modulation,
                                    "enable_rbds": rbds_enabled,
                                    "stereo_enabled": stereo_enabled,
                                    "deemphasis_us": deemphasis_us,

                                    # ── Spectral diagnostics ───────────────────
                                    # Computed from this capture's IQ; gives an
                                    # immediate read on pilot / stereo / RBDS
                                    # signal presence without loading the .npz.
                                    "spectral": spectral,
                                }
                                with open(sidecar_path, "w") as fp:
                                    json.dump(sidecar, fp, indent=2)
                            except Exception as exc:
                                logger.debug(
                                    "Could not write capture sidecar %s: %s",
                                    sidecar_path, exc,
                                )

                            size_bytes = os.path.getsize(output_path)

                            logger.info(
                                "📼 Captured %d IQ samples (%.2f MB, %.2fs) for %s → %s "
                                "[%s @ %.3f MHz | gain=%s dB, ext_lna=%+.1f dB, "
                                "bias-t=%s | hw_bw=%s kHz | ppm=%+.1f | "
                                "modulation=%s rbds=%s | %s]",
                                actual,
                                size_bytes / (1024 * 1024),
                                actual / max(effective_rate, 1),
                                receiver_id,
                                output_path,
                                driver,
                                frequency_hz / 1_000_000.0,
                                ("%.1f" % capture_gain_db) if capture_gain_db is not None else "?",
                                capture_external_lna_db,
                                "on" if capture_bias_t else "off",
                                ("%d" % hw_bw) if hw_bw else "?",
                                ppm,
                                modulation,
                                "on" if rbds_enabled else "off",
                                signal_path,
                            )

                            result = {
                                "command_id": command_id,
                                "success": True,
                                "path": output_path,
                                "sidecar_path": sidecar_path,
                                "filename": filename,
                                "num_samples": actual,
                                "requested_samples": num_samples,
                                "sample_rate": effective_rate,
                                "hardware_sample_rate": hw_sample_rate,
                                "early_decim_factor": early_decim,
                                "frequency_hz": frequency_hz,
                                "frequency_correction_ppm": ppm,
                                "applied_frequency_offset_hz": applied_offset_hz,
                                "hardware_bandwidth_hz": hw_bw,
                                "size_bytes": size_bytes,
                                "dtype": "complex64",
                                "gain_db": capture_gain_db,
                                "external_lna_db": capture_external_lna_db,
                                "bias_t_enabled": capture_bias_t,
                                "driver": driver,
                                "modulation_type": modulation,
                                "enable_rbds": rbds_enabled,
                                "signal_path": signal_path,
                                "duration_sec": actual / max(effective_rate, 1),
                                "complete": bool(completed),
                                "spectral": spectral,
                            }
                    except Exception as e:
                        # On any unexpected error, detach the tap so the
                        # publisher does not keep appending into a dropped
                        # entry.
                        with _active_captures_lock:
                            _active_captures.pop(receiver_id, None)
                        logger.error(
                            "Failed to capture IQ for receiver %s: %s",
                            receiver_id, e
                        )
                        result = {
                            "command_id": command_id,
                            "success": False,
                            "error": str(e)
                        }
            elif action == "auto_gain":
                # Runtime gain calibration: sweep the device's supported
                # gain values, measure IQ headroom (RMS + clipping ratio)
                # for each, and pick the highest gain that stays out of
                # clipping while keeping the RMS comfortably below
                # full-scale. The chosen value is applied to the live
                # device immediately; the webapp may also persist it to
                # the RadioReceiver row.
                receiver = radio_manager.get_receiver(receiver_id)
                if not receiver:
                    result = {
                        "command_id": command_id,
                        "success": False,
                        "error": f"Receiver '{receiver_id}' not found"
                    }
                else:
                    try:
                        result = _auto_gain_calibrate(
                            receiver=receiver,
                            receiver_id=receiver_id,
                            command_id=command_id,
                            settle_sec=float(
                                command.get("settle_sec", 0.20) or 0.20
                            ),
                            measure_sec=float(
                                command.get("measure_sec", 0.10) or 0.10
                            ),
                            target_rms_dbfs=float(
                                command.get("target_rms_dbfs", -12.0)
                            ),
                            clipping_threshold=float(
                                command.get("clipping_threshold", 0.01)
                            ),
                        )
                    except Exception as exc:
                        logger.error(
                            "auto_gain failed for receiver %s: %s",
                            receiver_id, exc, exc_info=True,
                        )
                        result = {
                            "command_id": command_id,
                            "success": False,
                            "error": str(exc),
                        }
            else:
                result = {
                    "command_id": command_id,
                    "success": False,
                    "error": f"Unknown action: {action}"
                }
        
        redis_client.setex(
            f"sdr:command_result:{command_id}",
            30,
            json.dumps(result)
        )
        
    except json.JSONDecodeError as e:
        logger.error(f"Invalid command JSON: {e}")
    except Exception as e:
        logger.error(f"Error processing command: {e}")


def main():
    """Main service loop."""
    logger.info("=" * 80)
    logger.info("EAS Station - Standalone SDR Service")
    logger.info("=" * 80)
    logger.info("This service handles ONLY SDR hardware operations:")
    logger.info("  - SoapySDR device management")
    logger.info("  - Dual-thread USB reading for reliability")
    logger.info("  - Publishing IQ samples to Redis")
    logger.info("  - Publishing SDR health metrics")
    logger.info("=" * 80)

    # Register signal handlers
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)

    try:
        # Verify SDR dependencies FIRST before anything else
        logger.info("=" * 80)
        if not verify_soapysdr_installation():
            logger.error("=" * 80)
            logger.error("❌ SDR DEPENDENCIES NOT PROPERLY INSTALLED")
            logger.error("=" * 80)
            logger.error("The SDR service cannot start without SoapySDR Python bindings.")
            logger.error("")
            logger.error("Required dependencies:")
            logger.error("  - SoapySDR Python bindings (python3-soapysdr)")
            logger.error("  - NumPy (python3-numpy)")
            logger.error("  - USB device access (/dev/bus/usb)")
            logger.error("")
            logger.error("Install dependencies: sudo apt install python3-soapysdr python3-numpy")
            logger.error("=" * 80)
            return 1
        logger.info("=" * 80)

        # Initialize Redis
        logger.info("Connecting to Redis...")
        redis_client = get_redis_client()
        
        # Initialize database
        logger.info("Initializing database connection...")
        app = initialize_database()
        
        # Initialize radio receivers
        logger.info("Initializing SDR receivers...")
        radio_manager = initialize_radio_receivers(app)
        
        if not radio_manager:
            logger.warning("No radio receivers initialized - service will wait for configuration")
        
        # Start sample publisher thread
        logger.info("Starting sample publisher thread...")
        _state.publisher_thread = threading.Thread(
            target=publish_samples_and_metrics,
            name="SDR-Publisher",
            daemon=True
        )
        _state.publisher_thread.start()
        
        logger.info("=" * 80)
        logger.info("✅ SDR Service started successfully")
        logger.info("   - Redis connection: ACTIVE")
        logger.info(f"   - Receivers configured: {len(radio_manager._receivers) if radio_manager and hasattr(radio_manager, '_receivers') else 0}")
        logger.info("   - Sample publishing: ACTIVE")
        logger.info("=" * 80)
        
        # Main loop: process commands and maintain health
        while _state.running:
            try:
                # Process any pending commands
                process_commands(redis_client)
                
                # Brief sleep
                time.sleep(0.1)
                
            except KeyboardInterrupt:
                logger.info("Received keyboard interrupt")
                break
            except Exception as e:
                logger.error(f"Main loop error: {e}", exc_info=True)
                time.sleep(1.0)
        
        # Shutdown
        logger.info("Shutting down SDR service...")
        
        # Stop all receivers
        if radio_manager and hasattr(radio_manager, '_receivers'):
            for identifier, receiver in radio_manager._receivers.items():
                try:
                    logger.info(f"Stopping receiver: {identifier}")
                    receiver.stop()
                except Exception as e:
                    logger.warning(f"Error stopping receiver {identifier}: {e}")
        
        # Close Redis
        if _state.redis_client:
            _state.redis_client.close()
        
        logger.info("✅ SDR Service shut down gracefully")
        return 0
        
    except Exception as e:
        logger.error(f"Fatal error in SDR service: {e}", exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
