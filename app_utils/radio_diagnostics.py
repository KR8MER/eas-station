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

from __future__ import annotations

"""Reusable radio-capture diagnostic analyzers.

These functions consume a complex64 IQ array (and a sample rate in Hz)
and return JSON-serialisable dicts describing:

* `analyze_iq_frontend` — front-end / RTL-SDR health: DC offset (LO
  leakage), RMS / peak levels in dBFS, clipping fraction (|x|>=0.95),
  envelope flatness (constant-envelope FM check), discriminator click
  rate (|Δφ|>0.6π), I/Q imbalance, and the IQ passband rolloff points
  (-3 dB, -20 dB) which expose RTL2832 / R820T2 channel-filter rolloff
  that can attenuate the 57 kHz RBDS subcarrier before it ever reaches
  the demodulator.

* `analyze_mpx_subcarriers` — inventory of every MPX subcarrier the FM
  multiplex can carry in North America (19 kHz pilot, 38 kHz stereo
  DSB-SC, 57 kHz RBDS, 67 kHz SCA #1, 76 kHz DARC, 92 kHz SCA #2). Each
  entry reports detected peak frequency, peak level, local noise floor,
  SNR, a presence verdict, and a note describing what the rest of the
  station does with that signal today (only RBDS is decoded; everything
  else is informational only).

* `analyze_capture` — top-level orchestrator combining both, plus a
  one-sentence summary verdict answering "is RBDS being suppressed by
  the RTL-SDR front end?".

The module is self-contained (numpy + scipy only) and has no Flask /
app_core imports so it can be used from:
  - the Flask `/api/radio/diagnostics/analyze/<id>` endpoint,
  - the CLI `scripts/rbds_diagnose.py`, and
  - unit tests.
"""

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import math

try:
    import numpy as np
    from scipy import signal as scipy_signal  # noqa: F401  (sanity import)
    _HAVE_DSP = True
except ImportError:  # pragma: no cover - numpy/scipy are runtime requirements
    np = None  # type: ignore
    scipy_signal = None  # type: ignore
    _HAVE_DSP = False


# ──────────────────────────────────────────────────────────────────────────────
# Subcarrier catalogue
# ──────────────────────────────────────────────────────────────────────────────
# Centre frequency, half-bandwidth used for the peak search, and metadata
# describing what each subcarrier is and what the station does with it today.
# The "in_use" field is the answer to the operator's recurring question
# "what signals are we throwing out?" — anything with in_use=False is
# currently being discarded by the RBDS-only worker.
SUBCARRIER_CATALOG: Tuple[Dict[str, Any], ...] = (
    {
        "id": "pilot_19k",
        "name": "19 kHz stereo pilot",
        "center_hz": 19_000,
        "search_bw_hz": 500,
        "in_use": True,
        "used_for": "Phase reference (locks the 38 kHz stereo and 57 kHz RBDS regenerators)",
        "standard": "FCC §73.322 / NRSC-1",
        "description": "Pure CW tone. Absent → mono station or weak signal.",
    },
    {
        "id": "stereo_38k",
        "name": "38 kHz stereo (L-R DSB-SC)",
        "center_hz": 38_000,
        "search_bw_hz": 1_500,
        "in_use": False,
        "used_for": "Not decoded — station only consumes the L+R mono sum from the audio path.",
        "standard": "FCC §73.322 / NRSC-1",
        "description": "Double-sideband suppressed-carrier difference signal (±15 kHz wide).",
    },
    {
        "id": "rbds_57k",
        "name": "57 kHz RBDS",
        "center_hz": 57_000,
        "search_bw_hz": 2_000,
        "in_use": True,
        "used_for": "Decoded by RBDSWorker → PI/PS/RT/TA/CT in the dashboard.",
        "standard": "NRSC-4-B / RDS",
        "description": "BPSK at 1187.5 bps, ±2.4 kHz around 57 kHz. The only data subcarrier currently decoded.",
    },
    {
        "id": "sca_67k",
        "name": "67 kHz SCA #1",
        "center_hz": 67_000,
        "search_bw_hz": 6_000,
        "in_use": False,
        "used_for": "Discarded. Common analog SCA: reading services for the blind, background music, ethnic audio, low-rate data.",
        "standard": "FCC §73.319 / NRSC-4-B Annex B",
        "description": "Narrowband FM (≈±7.5 kHz). If present and unaccounted for, this is the most likely 'other signal' on the air.",
    },
    {
        "id": "darc_76k",
        "name": "76 kHz DARC",
        "center_hz": 76_000,
        "search_bw_hz": 4_000,
        "in_use": False,
        "used_for": "Discarded. Rare in North America; primarily European/Japanese paging/data.",
        "standard": "ITU-R BS.1194 / EN 300 751",
        "description": "LMSK at 16 kbps. Almost never seen on US FM.",
    },
    {
        "id": "sca_92k",
        "name": "92 kHz SCA #2",
        "center_hz": 92_000,
        "search_bw_hz": 6_000,
        "in_use": False,
        "used_for": "Discarded. Second SCA slot — typically wideband data (paging legacy) or a second audio service.",
        "standard": "FCC §73.319 / NRSC-4-B Annex B",
        "description": "Wideband FM/data. Operates above the 75 kHz peak-deviation envelope used by RBDS.",
    },
)


# ──────────────────────────────────────────────────────────────────────────────
# Front-end thresholds (kept in one place so the UI and CLI agree)
# ──────────────────────────────────────────────────────────────────────────────
# Clipping fraction at |x|>=0.95 — matches the auto-gain threshold elsewhere
# in the codebase (sdr_hardware_service._measure_iq_levels) so verdicts are
# consistent across the dashboard.
CLIPPING_FRACTION_CRITICAL = 0.01    # 1 %
CLIPPING_FRACTION_WARNING = 0.001    # 0.1 %

# Discriminator click rate (|Δφ| > 0.6π) — driven by FM-demod noise on weak
# signals.  >2 % obliterates the 57 kHz RBDS lobe (see prior bug capture
# analysis: 9.49 % click rate → 0 dB RBDS SNR).
CLICK_RATE_CRITICAL_PCT = 5.0
CLICK_RATE_WARNING_PCT = 1.0

# Envelope P99/P01 — constant-envelope FM expects ~1; >3 means the upstream
# anti-alias or IF filter is shaving the FM shoulders.
ENVELOPE_RATIO_CRITICAL = 6.0
ENVELOPE_RATIO_WARNING = 3.0

# No-carrier / noise-dominated capture.  A genuine FM carrier is
# constant-envelope (P99/P01 → 1) and tracks its modulation smoothly, so the
# discriminator-click rate stays low.  Band-limited complex noise with *no*
# carrier is Rayleigh-distributed (P99/P01 ≈ 20) and its instantaneous phase
# walks randomly, so a large fraction of phase steps exceed 0.6π.  When BOTH
# hold the capture contains no demodulable FM signal — the receiver is locked
# to the noise floor (antenna disconnected, RF gain too low, or tuned
# off-channel), which sounds like white noise on the audio output.  Detected
# as its own finding so the dashboard stops blaming the IF / anti-alias filter
# (the envelope and click findings below) for what is really "no signal".
CLICK_RATE_NO_CARRIER_PCT = 15.0
ENVELOPE_RATIO_NO_CARRIER = 8.0

# Carrier offset from DC (the tuned frequency).  A correctly-tuned FM capture
# centres the station at DC; a non-trivial offset means the tuner landed off
# frequency (bad PPM correction, mistuned channel).  A broadcast FM channel is
# 200 kHz wide, so an offset past ~40 kHz is audibly off and past ~90 kHz
# starts dropping the station out of the captured band entirely.
CARRIER_OFFSET_WARNING_HZ = 40_000.0
CARRIER_OFFSET_CRITICAL_HZ = 90_000.0

# DC offset (LO leakage) — RTL-SDR direct conversion always has some DC,
# but >0.05 of full scale is unusually high and points at a centred carrier
# or a stuck I/Q bias.
DC_OFFSET_WARNING = 0.05
DC_OFFSET_CRITICAL = 0.15

# IQ passband -3 dB point.  RBDS at 57 kHz lives well inside the FM channel;
# if the RTL2832 (or other front-end) is rolling off by 3 dB before 60 kHz
# baseband, the RBDS lobe is being attenuated before software ever sees it.
ROLLOFF_3DB_RBDS_CRITICAL_HZ = 50_000
ROLLOFF_3DB_RBDS_WARNING_HZ = 60_000


# ──────────────────────────────────────────────────────────────────────────────
# Result dataclasses
# ──────────────────────────────────────────────────────────────────────────────
@dataclass
class SubcarrierReport:
    id: str
    name: str
    center_hz: int
    peak_hz: Optional[float]
    peak_db: Optional[float]
    noise_floor_db: Optional[float]
    snr_db: Optional[float]
    verdict: str   # "strong" | "present" | "marginal" | "absent"
    present: bool
    in_use: bool
    used_for: str
    standard: str
    description: str


@dataclass
class FrontEndReport:
    sample_rate: int
    duration_sec: float
    num_samples: int

    # Levels
    dc_offset_i: float
    dc_offset_q: float
    dc_offset_mag: float
    rms_dbfs: float
    peak_dbfs: float

    # Clipping / saturation
    clipping_fraction: float            # |x| >= 0.95 over both rails
    clipping_fraction_i: float
    clipping_fraction_q: float

    # Constant-envelope check
    envelope_p99: float
    envelope_p01: float
    envelope_ratio: float

    # I/Q imbalance (mean(I^2) vs mean(Q^2))
    iq_imbalance_db: float

    # Discriminator clicks (FM-demod path)
    click_rate_pct: float               # |Δφ| > 0.6π
    click_rate_severe_pct: float        # |Δφ| > 0.8π

    # IF passband rolloff (relative to central ±20 kHz reference)
    passband_ref_db: Optional[float]
    passband_3db_hz: Optional[float]
    passband_20db_hz: Optional[float]
    rbds_band_attenuation_db: Optional[float]  # at 57 kHz vs centre
    carrier_offset_hz: Optional[float]         # captured-energy centroid vs DC

    # Verdicts
    verdict: str
    findings: List[Dict[str, str]] = field(default_factory=list)


@dataclass
class CaptureDiagnostic:
    sample_rate: int
    duration_sec: float
    num_samples: int
    frontend: FrontEndReport
    subcarriers: List[SubcarrierReport]
    summary_verdict: str
    summary_messages: List[str]
    rbds_suppression_risk: str          # "none" | "low" | "elevated" | "high"
    rbds_suppression_reasons: List[str]


# ──────────────────────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────────────────────
def analyze_iq_frontend(iq: "np.ndarray", sample_rate: int) -> FrontEndReport:
    """Analyse the IQ stream for front-end health issues.

    Parameters
    ----------
    iq : complex64 ndarray
        Raw IQ samples as written by the SDR service (normalised so that
        0 dBFS == |x| == 1.0).
    sample_rate : int
        Sample rate in Hz.
    """
    if not _HAVE_DSP:
        raise RuntimeError("numpy/scipy are required for radio diagnostics")

    iq = np.asarray(iq, dtype=np.complex64)
    n = int(iq.size)
    if n == 0:
        raise ValueError("IQ array is empty")

    # ── Levels ────────────────────────────────────────────────────────────
    dc_i = float(iq.real.mean())
    dc_q = float(iq.imag.mean())
    dc_mag = float(math.hypot(dc_i, dc_q))

    mag = np.abs(iq)
    rms = float(np.sqrt(np.mean(mag.astype(np.float64) ** 2)))
    peak = float(np.max(mag))
    rms_dbfs = 20.0 * math.log10(rms) if rms > 0 else -120.0
    peak_dbfs = 20.0 * math.log10(peak) if peak > 0 else -120.0

    # ── Saturation / clipping ─────────────────────────────────────────────
    # The "either rail at 0.95" definition matches _measure_iq_levels in
    # sdr_hardware_service.py.  Per-rail counts let the UI tell the user
    # whether the saturation is symmetric (proper AGC overdrive) or one-
    # sided (DC bias / hardware fault).
    abs_i = np.abs(iq.real)
    abs_q = np.abs(iq.imag)
    clip_i = float(np.mean(abs_i >= 0.95))
    clip_q = float(np.mean(abs_q >= 0.95))
    # Per-rail | I OR Q | >= 0.95 (counts any sample with either rail at the
    # rail).  For complex IQ |x| can exceed 1 even when neither rail does;
    # use the OR of the two rails as the operator-facing "saturated samples"
    # count because that's what the 8-bit RTL2832 ADC actually clips.
    clip_any = float(np.mean((abs_i >= 0.95) | (abs_q >= 0.95)))

    # ── Constant-envelope FM check ────────────────────────────────────────
    env_p99 = float(np.percentile(mag, 99))
    env_p01 = float(np.percentile(mag, 1))
    env_ratio = env_p99 / max(env_p01, 1e-12)

    # ── I/Q imbalance ─────────────────────────────────────────────────────
    pi = float(np.mean(iq.real.astype(np.float64) ** 2))
    pq = float(np.mean(iq.imag.astype(np.float64) ** 2))
    if pi > 0 and pq > 0:
        iq_imbalance_db = 10.0 * math.log10(pi / pq)
    else:
        iq_imbalance_db = 0.0

    # ── Discriminator click rate ──────────────────────────────────────────
    # Use the same instantaneous-phase discriminator that the FM demod
    # worker uses (np.angle(z[n]*conj(z[n-1]))).  Clicks dominate the RBDS
    # band noise floor on weak / interfered signals.
    if n >= 2:
        z = iq[1:] * np.conj(iq[:-1])
        dphi = np.angle(z)
        click_rate = float(np.mean(np.abs(dphi) > 0.6 * math.pi)) * 100.0
        click_severe = float(np.mean(np.abs(dphi) > 0.8 * math.pi)) * 100.0
    else:
        click_rate = 0.0
        click_severe = 0.0

    # ── IF passband rolloff ───────────────────────────────────────────────
    # Welch PSD on the centred IQ; reference is the median of the central
    # ±20 kHz (flat FM body).  Walk outward to find where the spectrum has
    # rolled off by 3 dB and 20 dB.  If the -3 dB point sits below 57 kHz
    # the RTL2832 channel filter is attenuating RBDS before demod.
    passband_3db_hz: Optional[float] = None
    passband_20db_hz: Optional[float] = None
    passband_ref_db: Optional[float] = None
    rbds_atten_db: Optional[float] = None
    # Carrier offset: where the captured RF energy sits relative to DC (the
    # tuned frequency).  A correctly-tuned FM signal is centred at DC so the
    # power-weighted centroid of the above-noise-floor energy is ~0.  A tuner
    # that landed off frequency (wrong PPM correction, mistuned channel) shifts
    # the whole lump, so the centroid ≈ the tuning error.  Pure noise has no
    # above-floor energy and leaves this as None.
    carrier_offset_hz: Optional[float] = None

    nperseg = min(4096, max(64, n // 4))
    if nperseg >= 64:
        f, psd = scipy_signal.welch(
            iq, fs=sample_rate, nperseg=nperseg, return_onesided=False
        )
        f = np.fft.fftshift(f)
        psd = np.fft.fftshift(psd)

        # Power-weighted centroid of the energy that sits above the noise
        # floor.  Subtracting a robust floor (the 10th percentile of the PSD)
        # stops symmetric broadband noise from dragging the centroid toward 0
        # and keeps the estimate on the actual carrier lump.
        floor = float(np.percentile(psd, 10))
        excess = np.maximum(psd - floor, 0.0)
        total = float(np.sum(excess))
        if total > 0:
            carrier_offset_hz = float(np.sum(f * excess) / total)

        ref_mask = np.abs(f) <= 20_000
        if np.any(ref_mask) and np.any(psd[ref_mask] > 0):
            ref = float(np.median(psd[ref_mask]))
            ref_db = 10.0 * math.log10(ref + 1e-30)
            passband_ref_db = ref_db
            # Use the positive-frequency arm only — the negative arm is the
            # mirror image, and the channel filter is symmetric by design.
            pos_mask = f >= 0
            f_pos = f[pos_mask]
            psd_pos = psd[pos_mask]
            # Smooth lightly so noise doesn't trigger false rolloff crossings.
            if psd_pos.size > 7:
                kernel = np.ones(7) / 7.0
                psd_pos = np.convolve(psd_pos, kernel, mode="same")
            db_pos = 10.0 * np.log10(np.maximum(psd_pos, 1e-30)) - ref_db
            # First crossing below -3 dB after we leave the in-band reference
            # window.  We require the dip to persist (no false single-bin
            # nulls) by demanding two consecutive bins below the threshold.
            def _first_persistent_crossing(threshold_db: float) -> Optional[float]:
                below = db_pos < threshold_db
                # Persistent = two adjacent True
                for i in range(len(below) - 1):
                    if (
                        f_pos[i] > 20_000
                        and below[i] and below[i + 1]
                    ):
                        return float(f_pos[i])
                return None

            passband_3db_hz = _first_persistent_crossing(-3.0)
            passband_20db_hz = _first_persistent_crossing(-20.0)

            # Attenuation at 57 kHz vs the central reference.
            rbds_mask = (f_pos >= 55_000) & (f_pos <= 59_000)
            if np.any(rbds_mask):
                rbds_atten_db = float(np.max(db_pos[rbds_mask]))

    # ── Build findings + verdict ──────────────────────────────────────────
    findings: List[Dict[str, str]] = []
    severity_rank = {"info": 0, "ok": 0, "warning": 1, "critical": 2}
    worst = "ok"

    def _add(level: str, code: str, message: str) -> None:
        nonlocal worst
        findings.append({"level": level, "code": code, "message": message})
        if severity_rank.get(level, 0) > severity_rank.get(worst, 0):
            worst = level

    # No-carrier check first: a noise-dominated capture trips the envelope and
    # click thresholds below, but their messages ("IF filter too narrow",
    # "clicks dominate the noise floor") send the operator down the wrong path.
    # When the IQ is statistically indistinguishable from band-limited noise we
    # say so plainly and suppress those misleading follow-on findings.
    no_carrier = (
        click_rate >= CLICK_RATE_NO_CARRIER_PCT
        and env_ratio >= ENVELOPE_RATIO_NO_CARRIER
    )
    if no_carrier:
        _add(
            "critical", "no_carrier",
            f"No FM carrier in this capture: envelope P99/P01 = {env_ratio:.1f} "
            "(a constant-envelope FM carrier is ~1) and "
            f"{click_rate:.1f}% of phase steps exceed 0.6π — the IQ is "
            "indistinguishable from band-limited noise, which is what white "
            "noise on the audio sounds like. The receiver is locked to the "
            "noise floor, not a station. Check the antenna connection, raise "
            "the RF gain (Auto-Calibrate Gain), and confirm the tuned "
            "frequency. The subcarrier SNRs below are not meaningful until a "
            "carrier is present."
        )

    if clip_any >= CLIPPING_FRACTION_CRITICAL:
        _add(
            "critical", "saturation",
            f"Front-end saturated: {clip_any * 100:.1f}% of samples at |I or Q| ≥ 0.95. "
            "Lower the RTL-SDR LNA / IF gain (Auto-Calibrate Gain)."
        )
    elif clip_any >= CLIPPING_FRACTION_WARNING:
        _add(
            "warning", "saturation",
            f"Front-end approaching saturation: {clip_any * 100:.2f}% of samples at |I or Q| ≥ 0.95."
        )

    if dc_mag >= DC_OFFSET_CRITICAL:
        _add(
            "critical", "dc_offset",
            f"Large DC offset ({dc_mag:.3f}) — RTL-SDR LO leakage at the tuned carrier. "
            "Re-tune ±100 kHz off-channel or enable DC-block."
        )
    elif dc_mag >= DC_OFFSET_WARNING:
        _add(
            "warning", "dc_offset",
            f"Elevated DC offset ({dc_mag:.3f}) — expected for centred-carrier RTL2832, but worth noting."
        )

    # The click-rate and envelope-ratio findings below assume a carrier is
    # present and diagnose how the front end is treating it.  When there is no
    # carrier (no_carrier above) both thresholds trip on noise alone and their
    # messages are misleading, so we suppress them in favour of the single
    # "no_carrier" finding.
    if not no_carrier and click_rate >= CLICK_RATE_CRITICAL_PCT:
        _add(
            "critical", "discriminator_clicks",
            f"FM discriminator click rate {click_rate:.2f}% — clicks dominate the noise floor "
            "around 57 kHz; RBDS decode is almost certainly impossible. Check antenna / signal strength."
        )
    elif not no_carrier and click_rate >= CLICK_RATE_WARNING_PCT:
        _add(
            "warning", "discriminator_clicks",
            f"FM discriminator click rate {click_rate:.2f}% — elevated; RBDS BLER will be poor."
        )

    if not no_carrier and env_ratio >= ENVELOPE_RATIO_CRITICAL:
        _add(
            "critical", "envelope_ratio",
            f"Envelope P99/P01 = {env_ratio:.1f} — upstream IF / anti-alias filter is too narrow; "
            "FM shoulders being clipped (AM-to-PM distortion)."
        )
    elif not no_carrier and env_ratio >= ENVELOPE_RATIO_WARNING:
        _add(
            "warning", "envelope_ratio",
            f"Envelope P99/P01 = {env_ratio:.1f} — slightly elevated."
        )

    if abs(iq_imbalance_db) >= 3.0:
        _add(
            "warning", "iq_imbalance",
            f"I/Q power imbalance {iq_imbalance_db:+.1f} dB — uncalibrated RTL-SDR or DC bias."
        )

    if passband_3db_hz is not None:
        if passband_3db_hz < ROLLOFF_3DB_RBDS_CRITICAL_HZ:
            _add(
                "critical", "passband_rolloff",
                f"IF passband -3 dB at {passband_3db_hz / 1000:.0f} kHz — RBDS lobe at 57 kHz is being "
                "attenuated by the RTL2832 channel filter before software demod. Widen the requested "
                "device bandwidth or use a higher sample rate."
            )
        elif passband_3db_hz < ROLLOFF_3DB_RBDS_WARNING_HZ:
            _add(
                "warning", "passband_rolloff",
                f"IF passband -3 dB at {passband_3db_hz / 1000:.0f} kHz — RBDS lobe is close to the rolloff."
            )
    if rbds_atten_db is not None and rbds_atten_db < -3.0:
        _add(
            "warning", "rbds_band_attenuation",
            f"57 kHz IQ power is {rbds_atten_db:+.1f} dB below the central FM body — "
            "front-end is attenuating the RBDS subcarrier."
        )

    # Carrier offset — only meaningful when a carrier is actually present
    # (no_carrier captures have no lump to centre on, and the no_carrier
    # finding already tells the operator to confirm the tuned frequency).
    if not no_carrier and carrier_offset_hz is not None:
        off_khz = carrier_offset_hz / 1000.0
        if abs(carrier_offset_hz) >= CARRIER_OFFSET_CRITICAL_HZ:
            _add(
                "critical", "carrier_offset",
                f"Captured energy is centred {off_khz:+.0f} kHz off DC — the tuner is off "
                f"frequency by ~{abs(off_khz):.0f} kHz, pushing the station out of the captured "
                "band. Check the PPM frequency correction and the tuned frequency."
            )
        elif abs(carrier_offset_hz) >= CARRIER_OFFSET_WARNING_HZ:
            _add(
                "warning", "carrier_offset",
                f"Captured energy is centred {off_khz:+.0f} kHz off DC — the tuner appears "
                f"~{abs(off_khz):.0f} kHz off frequency (PPM correction / tuned frequency)."
            )

    if worst == "ok" and not findings:
        _add("ok", "frontend", "Front-end is healthy: no clipping, low click rate, flat passband.")

    return FrontEndReport(
        sample_rate=int(sample_rate),
        duration_sec=float(n) / float(sample_rate),
        num_samples=n,
        dc_offset_i=dc_i,
        dc_offset_q=dc_q,
        dc_offset_mag=dc_mag,
        rms_dbfs=float(rms_dbfs),
        peak_dbfs=float(peak_dbfs),
        clipping_fraction=clip_any,
        clipping_fraction_i=clip_i,
        clipping_fraction_q=clip_q,
        envelope_p99=env_p99,
        envelope_p01=env_p01,
        envelope_ratio=env_ratio,
        iq_imbalance_db=iq_imbalance_db,
        click_rate_pct=click_rate,
        click_rate_severe_pct=click_severe,
        passband_ref_db=passband_ref_db,
        passband_3db_hz=passband_3db_hz,
        passband_20db_hz=passband_20db_hz,
        rbds_band_attenuation_db=rbds_atten_db,
        carrier_offset_hz=carrier_offset_hz,
        verdict=worst,
        findings=findings,
    )


def _fm_demodulate(iq: "np.ndarray") -> "np.ndarray":
    """Instantaneous-phase FM discriminator (same as the live demod path)."""
    z = iq[1:] * np.conj(iq[:-1])
    return np.angle(z).astype(np.float32)


def analyze_mpx_subcarriers(
    mpx: "np.ndarray",
    sample_rate: int,
) -> List[SubcarrierReport]:
    """Inventory the MPX subcarriers present in *mpx*.

    Returns one entry per subcarrier defined in ``SUBCARRIER_CATALOG``.
    Only subcarriers within the Nyquist band of *sample_rate* are
    evaluated; the rest return ``present=False`` with a verdict of
    ``"absent"`` and ``snr_db=None``.
    """
    if not _HAVE_DSP:
        raise RuntimeError("numpy/scipy are required for radio diagnostics")

    mpx = np.asarray(mpx, dtype=np.float32)
    n = int(mpx.size)
    if n < 4096:
        # Not enough samples for a meaningful FFT — report all subcarriers
        # as undetermined.
        return [
            SubcarrierReport(
                id=sc["id"], name=sc["name"], center_hz=sc["center_hz"],
                peak_hz=None, peak_db=None, noise_floor_db=None, snr_db=None,
                verdict="undetermined", present=False,
                in_use=sc["in_use"], used_for=sc["used_for"],
                standard=sc["standard"], description=sc["description"],
            )
            for sc in SUBCARRIER_CATALOG
        ]

    # Welch PSD for a robust noise-floor estimate.  Use a moderately long
    # window (~25 Hz bin width at 256 kHz) so the 19 kHz / 57 kHz pure-tone
    # lobes are well-resolved but the wider DSB-SC stereo image is still
    # captured in a single peak measurement.
    nperseg = min(1 << 14, 1 << int(math.floor(math.log2(n))))
    f, psd = scipy_signal.welch(
        mpx, fs=sample_rate, nperseg=nperseg, return_onesided=True
    )
    psd_db = 10.0 * np.log10(np.maximum(psd, 1e-30))

    # Pick a "quiet" reference band between 28-32 kHz (above the stereo
    # pilot, below the stereo upper sideband) for the noise floor.  This is
    # the same convention used by _compute_capture_spectral_diagnostics in
    # sdr_hardware_service.py.
    noise_mask = (f >= 28_000) & (f <= 32_000)
    fallback_noise_db = (
        float(np.median(psd_db[noise_mask])) if np.any(noise_mask) else -120.0
    )

    reports: List[SubcarrierReport] = []
    nyquist = sample_rate / 2.0

    for sc in SUBCARRIER_CATALOG:
        center = float(sc["center_hz"])
        bw = float(sc["search_bw_hz"])
        # Out of band relative to the current sample rate.
        if center + bw > nyquist:
            reports.append(SubcarrierReport(
                id=sc["id"], name=sc["name"], center_hz=int(center),
                peak_hz=None, peak_db=None, noise_floor_db=None, snr_db=None,
                verdict="out_of_band", present=False,
                in_use=bool(sc["in_use"]), used_for=str(sc["used_for"]),
                standard=str(sc["standard"]), description=str(sc["description"]),
            ))
            continue

        sig_mask = (f >= center - bw) & (f <= center + bw)
        if not np.any(sig_mask):
            reports.append(SubcarrierReport(
                id=sc["id"], name=sc["name"], center_hz=int(center),
                peak_hz=None, peak_db=None, noise_floor_db=None, snr_db=None,
                verdict="undetermined", present=False,
                in_use=bool(sc["in_use"]), used_for=str(sc["used_for"]),
                standard=str(sc["standard"]), description=str(sc["description"]),
            ))
            continue

        peak_idx_local = int(np.argmax(psd_db[sig_mask]))
        peak_db = float(psd_db[sig_mask][peak_idx_local])
        peak_hz = float(f[sig_mask][peak_idx_local])

        # Local noise floor: a band immediately above the subcarrier (or
        # the fallback 28-32 kHz reference if that bumps into another
        # subcarrier).  Walk +bw..+2*bw above centre but stay below Nyquist.
        nf_lo = center + bw + 500
        nf_hi = min(center + 2 * bw + 2_000, nyquist - 500)
        nf_mask = (f >= nf_lo) & (f <= nf_hi)
        if np.any(nf_mask) and nf_hi > nf_lo:
            noise_db = float(np.median(psd_db[nf_mask]))
        else:
            noise_db = fallback_noise_db

        snr_db = peak_db - noise_db

        if snr_db >= 20.0:
            verdict = "strong"
            present = True
        elif snr_db >= 10.0:
            verdict = "present"
            present = True
        elif snr_db >= 5.0:
            verdict = "marginal"
            present = True
        else:
            verdict = "absent"
            present = False

        reports.append(SubcarrierReport(
            id=sc["id"], name=sc["name"], center_hz=int(center),
            peak_hz=peak_hz, peak_db=peak_db,
            noise_floor_db=noise_db, snr_db=snr_db,
            verdict=verdict, present=present,
            in_use=bool(sc["in_use"]), used_for=str(sc["used_for"]),
            standard=str(sc["standard"]), description=str(sc["description"]),
        ))

    return reports


def analyze_capture(
    iq: "np.ndarray",
    sample_rate: int,
    *,
    multiplex: Optional["np.ndarray"] = None,
) -> CaptureDiagnostic:
    """Top-level analyser combining front-end + MPX inventory.

    If *multiplex* is provided (e.g. the ``multiplex`` array saved
    alongside the IQ in the .npz capture archive), it is used directly
    for the subcarrier scan; otherwise the IQ is FM-demodulated here so
    the same code path works for legacy .npy captures that store only IQ.
    """
    if not _HAVE_DSP:
        raise RuntimeError("numpy/scipy are required for radio diagnostics")

    iq = np.asarray(iq, dtype=np.complex64)
    frontend = analyze_iq_frontend(iq, sample_rate)

    if multiplex is None:
        mpx = _fm_demodulate(iq)
    else:
        mpx = np.asarray(multiplex, dtype=np.float32)
    subcarriers = analyze_mpx_subcarriers(mpx, sample_rate)

    # ── Cross-cutting verdict: is RBDS being suppressed by the front-end? ─
    reasons: List[str] = []
    risk = "none"

    rbds = next((s for s in subcarriers if s.id == "rbds_57k"), None)
    pilot = next((s for s in subcarriers if s.id == "pilot_19k"), None)

    # The cleanest "suppression" signal is: pilot strong but RBDS weak/absent.
    # Only compares when both subcarriers were actually measurable (rbds may
    # be ``out_of_band`` for narrow sample rates, in which case snr_db is
    # None and the comparison is meaningless).
    if (
        pilot and rbds and pilot.present
        and pilot.snr_db is not None and rbds.snr_db is not None
    ):
        if not rbds.present and pilot.snr_db >= 15.0:
            risk = "high"
            reasons.append(
                f"19 kHz pilot is strong ({pilot.snr_db:.1f} dB SNR) but 57 kHz RBDS is "
                f"absent ({rbds.snr_db:.1f} dB) — the station is reachable but RBDS isn't getting through."
            )
        elif rbds.verdict == "marginal" and pilot.snr_db >= 20.0:
            risk = "elevated"
            reasons.append(
                f"Pilot is strong ({pilot.snr_db:.1f} dB) but RBDS is marginal ({rbds.snr_db:.1f} dB)."
            )

    # Hardware-side contributors.
    for finding in frontend.findings:
        if finding["level"] == "critical":
            if finding["code"] in ("saturation", "passband_rolloff",
                                   "rbds_band_attenuation",
                                   "discriminator_clicks", "envelope_ratio"):
                if risk in ("none", "low"):
                    risk = "elevated"
                reasons.append(f"Front-end: {finding['message']}")
        elif finding["level"] == "warning" and finding["code"] in (
            "passband_rolloff", "rbds_band_attenuation", "discriminator_clicks",
        ):
            if risk == "none":
                risk = "low"
            reasons.append(f"Front-end: {finding['message']}")

    # No-carrier captures dominate the verdict: every subcarrier SNR is noise
    # vs noise, so lead with the real problem and don't frame it as RBDS being
    # "suppressed" by the front end (it isn't — there's simply no signal).
    no_carrier = any(f["code"] == "no_carrier" for f in frontend.findings)

    # Summary text.
    summary_messages: List[str] = []
    if no_carrier:
        summary_messages.append(
            "No FM carrier present — the capture is band-limited noise "
            "(white noise on the audio). Check the antenna, RF gain, and "
            "tuned frequency; the subcarrier SNRs below are not meaningful "
            "until a carrier is acquired."
        )
        if risk in ("none", "low"):
            risk = "elevated"
        reasons.append(
            "Capture contains no FM carrier (noise floor only) — RBDS cannot "
            "decode until the front end delivers a signal."
        )
    if rbds is not None and rbds.snr_db is not None:
        summary_messages.append(
            f"57 kHz RBDS subcarrier: {rbds.snr_db:.1f} dB SNR ({rbds.verdict})."
        )

    discards = [s.name for s in subcarriers if s.present and not s.in_use]
    if discards:
        summary_messages.append(
            "Signals present but currently discarded by the station: "
            + ", ".join(discards) + "."
        )

    if frontend.verdict == "critical":
        summary_verdict = "critical"
    elif frontend.verdict == "warning" or risk in ("elevated", "high"):
        summary_verdict = "warning"
    else:
        summary_verdict = "ok"
        if not summary_messages:
            summary_messages.append("Capture is healthy.")

    return CaptureDiagnostic(
        sample_rate=int(sample_rate),
        duration_sec=float(iq.size) / float(sample_rate),
        num_samples=int(iq.size),
        frontend=frontend,
        subcarriers=subcarriers,
        summary_verdict=summary_verdict,
        summary_messages=summary_messages,
        rbds_suppression_risk=risk,
        rbds_suppression_reasons=reasons,
    )


def diagnostic_to_dict(diag: CaptureDiagnostic) -> Dict[str, Any]:
    """Convert a :class:`CaptureDiagnostic` into a JSON-serialisable dict.

    Floats are rounded to a sensible number of digits so the payload
    stays compact and stable across runs.
    """
    def _r(x: Any, places: int = 2) -> Any:
        if x is None:
            return None
        try:
            return round(float(x), places)
        except (TypeError, ValueError):
            return x

    fe = diag.frontend
    fe_dict = {
        "sample_rate": fe.sample_rate,
        "duration_sec": _r(fe.duration_sec, 3),
        "num_samples": fe.num_samples,
        "dc_offset_i": _r(fe.dc_offset_i, 5),
        "dc_offset_q": _r(fe.dc_offset_q, 5),
        "dc_offset_mag": _r(fe.dc_offset_mag, 5),
        "rms_dbfs": _r(fe.rms_dbfs, 2),
        "peak_dbfs": _r(fe.peak_dbfs, 2),
        "clipping_fraction": _r(fe.clipping_fraction, 5),
        "clipping_fraction_i": _r(fe.clipping_fraction_i, 5),
        "clipping_fraction_q": _r(fe.clipping_fraction_q, 5),
        "envelope_p99": _r(fe.envelope_p99, 4),
        "envelope_p01": _r(fe.envelope_p01, 4),
        "envelope_ratio": _r(fe.envelope_ratio, 2),
        "iq_imbalance_db": _r(fe.iq_imbalance_db, 2),
        "click_rate_pct": _r(fe.click_rate_pct, 3),
        "click_rate_severe_pct": _r(fe.click_rate_severe_pct, 4),
        "passband_ref_db": _r(fe.passband_ref_db, 2),
        "passband_3db_hz": _r(fe.passband_3db_hz, 0),
        "passband_20db_hz": _r(fe.passband_20db_hz, 0),
        "rbds_band_attenuation_db": _r(fe.rbds_band_attenuation_db, 2),
        "carrier_offset_hz": _r(fe.carrier_offset_hz, 0),
        "verdict": fe.verdict,
        "findings": fe.findings,
    }

    sc_list: List[Dict[str, Any]] = []
    for sc in diag.subcarriers:
        sc_list.append({
            "id": sc.id,
            "name": sc.name,
            "center_hz": sc.center_hz,
            "peak_hz": _r(sc.peak_hz, 1),
            "peak_db": _r(sc.peak_db, 2),
            "noise_floor_db": _r(sc.noise_floor_db, 2),
            "snr_db": _r(sc.snr_db, 2),
            "verdict": sc.verdict,
            "present": sc.present,
            "in_use": sc.in_use,
            "used_for": sc.used_for,
            "standard": sc.standard,
            "description": sc.description,
        })

    return {
        "sample_rate": diag.sample_rate,
        "duration_sec": _r(diag.duration_sec, 3),
        "num_samples": diag.num_samples,
        "frontend": fe_dict,
        "subcarriers": sc_list,
        "summary_verdict": diag.summary_verdict,
        "summary_messages": diag.summary_messages,
        "rbds_suppression_risk": diag.rbds_suppression_risk,
        "rbds_suppression_reasons": diag.rbds_suppression_reasons,
    }


__all__ = [
    "SUBCARRIER_CATALOG",
    "FrontEndReport",
    "SubcarrierReport",
    "CaptureDiagnostic",
    "analyze_iq_frontend",
    "analyze_mpx_subcarriers",
    "analyze_capture",
    "diagnostic_to_dict",
]
