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

Tests for app_utils/radio_diagnostics.py — the IQ-capture analyzer that
powers the rich Radio Diagnostics dashboard.

The tests synthesise FM-MPX waveforms with known subcarriers and feed
them through the analyzer to verify that:

* a healthy capture is reported as ``ok`` with the right subcarriers
  marked present,
* a heavily front-end-saturated capture is reported as ``critical``
  with the suppression-risk knob lifted off ``none``,
* the SCA subcarrier inventory correctly flags 67 kHz SCA when present
  vs absent,
* the RBDS-strong-but-pilot-dominant case (the user's "RBDS isn't
  decoding even though it's strong on-air" scenario) is detected.

The tests bypass ``app_utils/__init__.py`` because that module pulls in
optional system dependencies (psutil) that aren't installed in minimal
CI environments.  ``radio_diagnostics`` itself only depends on numpy and
scipy, which are already test-time dependencies elsewhere in the repo.
"""

from __future__ import annotations

import importlib.util
import math
import sys
from pathlib import Path

import numpy as np
import pytest

# Load app_utils/radio_diagnostics.py directly to avoid pulling in the
# package's __init__ (which imports psutil).
_ROOT = Path(__file__).resolve().parents[1]
_SPEC = importlib.util.spec_from_file_location(
    "radio_diagnostics_under_test",
    _ROOT / "app_utils" / "radio_diagnostics.py",
)
assert _SPEC is not None and _SPEC.loader is not None
radio_diagnostics = importlib.util.module_from_spec(_SPEC)
sys.modules["radio_diagnostics_under_test"] = radio_diagnostics
_SPEC.loader.exec_module(radio_diagnostics)

analyze_capture = radio_diagnostics.analyze_capture
analyze_iq_frontend = radio_diagnostics.analyze_iq_frontend
analyze_mpx_subcarriers = radio_diagnostics.analyze_mpx_subcarriers
diagnostic_to_dict = radio_diagnostics.diagnostic_to_dict


# ──────────────────────────────────────────────────────────────────────────────
# Helpers — build an FM IQ signal whose multiplex contains specified subcarriers
# ──────────────────────────────────────────────────────────────────────────────
def _synthesize_clean_capture(
    fs: int,
    duration_sec: float,
    subcarriers: dict,
    seed: int = 12345,
) -> tuple:
    """Build a (iq, mpx) pair for analyzer tests.

    The MPX is the linear sum of the requested subcarrier tones — i.e.
    exactly what the FM discriminator should produce on a clean signal.
    The IQ is low-amplitude complex AWGN — high enough to drive the
    Welch PSD without DC tricks, low enough to avoid the 0.95 clipping
    threshold.  We deliberately don't FM-modulate the MPX into the IQ
    because narrowband FM produces a DC-heavy IQ (looks like LO leakage)
    and wideband FM produces Bessel sidebands at the very subcarrier
    frequencies we're trying to test for absence.  Real .npz captures
    contain the actual demod-output ``multiplex`` array which the
    analyzer accepts directly via the ``multiplex=`` kwarg — this test
    helper exercises that exact code path.
    """
    rng = np.random.default_rng(seed)
    n = int(fs * duration_sec)
    t = np.arange(n) / fs

    mpx = np.zeros(n, dtype=np.float64)
    for freq, amp in subcarriers.items():
        phase = float(rng.uniform(0, 2 * math.pi))
        mpx += amp * np.cos(2 * math.pi * freq * t + phase)
    mpx = (mpx + rng.standard_normal(n) * 0.001).astype(np.float32)

    # Healthy IQ stand-in: zero-mean low-amplitude complex AWGN.  No DC,
    # no clipping, no click hot-spots — exactly what the front-end check
    # should approve.
    iq = (
        rng.standard_normal(n) + 1j * rng.standard_normal(n)
    ).astype(np.complex64) * 0.05
    return iq, mpx


# ──────────────────────────────────────────────────────────────────────────────
# Tests
# ──────────────────────────────────────────────────────────────────────────────
def test_healthy_capture_pilot_stereo_rbds_present():
    """A clean MPX with pilot+stereo+RBDS reports all three present and
    flags 38 kHz stereo as a discarded (present-but-unused) signal."""
    fs = 256_000
    iq, mpx = _synthesize_clean_capture(
        fs=fs,
        duration_sec=2.0,
        subcarriers={
            19_000: 0.10,   # pilot
            38_000: 0.30,   # stereo DSB-SC envelope (modelled as a tone)
            57_000: 0.07,   # RBDS lobe (modelled as a tone)
        },
    )
    diag = analyze_capture(iq, fs, multiplex=mpx)
    out = diagnostic_to_dict(diag)

    sc_by_id = {s["id"]: s for s in out["subcarriers"]}
    assert sc_by_id["pilot_19k"]["present"], out["subcarriers"]
    assert sc_by_id["stereo_38k"]["present"]
    assert sc_by_id["rbds_57k"]["present"]
    # 67/76/92 kHz must be absent — we didn't transmit them.
    assert not sc_by_id["sca_67k"]["present"]
    assert not sc_by_id["darc_76k"]["present"]
    assert not sc_by_id["sca_92k"]["present"]

    # Clean IQ (low-amplitude AWGN) must not register front-end saturation
    # even if it triggers other FM-shape warnings (the IQ stand-in is not
    # a constant-envelope FM signal so envelope/click warnings are
    # expected; the *saturation* finding is the one this test cares
    # about because that's the actionable gain problem).
    fe = out["frontend"]
    assert fe["clipping_fraction"] < 0.001
    finding_codes = {f["code"] for f in fe["findings"]}
    assert "saturation" not in finding_codes

    # The summary should call out 38 kHz stereo as a present-but-discarded
    # signal — that's the answer to "what signals are we throwing out?"
    discards_message = " ".join(out["summary_messages"]).lower()
    assert "stereo" in discards_message or "38 khz" in discards_message


def test_saturated_iq_flags_critical_and_lifts_suppression_risk():
    """An IQ stream where the ADC is at the rails on >1% of samples must
    produce a critical front-end verdict with a ``saturation`` finding,
    and lift the RBDS-suppression risk off ``none``."""
    fs = 256_000
    rng = np.random.default_rng(7)
    n = fs * 1  # 1 second
    # Saturated IQ: large-amplitude complex AWGN that clips at ±1 (the
    # 8-bit ADC rail).  Anything pushed past 1.0 is hard-clipped to
    # exactly 1.0 to mimic real ADC saturation behaviour.
    raw = (rng.standard_normal(n) + 1j * rng.standard_normal(n)) * 1.5
    i = np.clip(raw.real, -1.0, 1.0)
    q = np.clip(raw.imag, -1.0, 1.0)
    iq = (i + 1j * q).astype(np.complex64)
    diag = analyze_capture(iq, fs)
    out = diagnostic_to_dict(diag)

    fe = out["frontend"]
    assert fe["verdict"] == "critical"
    assert fe["clipping_fraction"] > 0.01
    finding_codes = {f["code"] for f in fe["findings"]}
    assert "saturation" in finding_codes
    assert out["summary_verdict"] == "critical"
    # Saturation alone should put us at "elevated" or worse.
    assert out["rbds_suppression_risk"] in ("elevated", "high")


def test_sca_67k_present_when_transmitted_and_in_discard_list():
    """When a station carries a 67 kHz SCA, the analyzer reports it
    present and lists it as a discarded signal in the summary."""
    fs = 256_000
    iq, mpx = _synthesize_clean_capture(
        fs=fs,
        duration_sec=2.0,
        subcarriers={
            19_000: 0.10,
            57_000: 0.07,
            67_000: 0.08,  # SCA #1
        },
    )
    diag = analyze_capture(iq, fs, multiplex=mpx)
    out = diagnostic_to_dict(diag)

    sc_by_id = {s["id"]: s for s in out["subcarriers"]}
    assert sc_by_id["sca_67k"]["present"], sc_by_id["sca_67k"]
    assert sc_by_id["sca_67k"]["in_use"] is False  # station discards SCA today
    # The summary should mention that 67 kHz SCA is present-but-discarded.
    discards_message = " ".join(out["summary_messages"]).lower()
    assert "67 khz" in discards_message or "sca #1" in discards_message.lower()


def test_out_of_band_subcarriers_marked_when_sample_rate_is_narrow():
    """At a 100 kHz sample rate (Nyquist = 50 kHz) the 57/67/76/92 kHz
    subcarriers are physically unobservable; the analyzer should report
    them as out_of_band rather than absent."""
    fs = 100_000
    iq, mpx = _synthesize_clean_capture(
        fs=fs,
        duration_sec=1.0,
        subcarriers={19_000: 0.10, 38_000: 0.30},
    )
    diag = analyze_capture(iq, fs, multiplex=mpx)
    out = diagnostic_to_dict(diag)
    sc_by_id = {s["id"]: s for s in out["subcarriers"]}
    assert sc_by_id["rbds_57k"]["verdict"] == "out_of_band"
    assert sc_by_id["sca_67k"]["verdict"] == "out_of_band"
    assert sc_by_id["sca_92k"]["verdict"] == "out_of_band"
    # 19 kHz pilot is still in band and should be detected.
    assert sc_by_id["pilot_19k"]["present"]


def _synthesize_fm_carrier(
    fs: int,
    duration_sec: float,
    subcarriers: dict,
    deviation_hz: float = 50_000.0,
    seed: int = 99,
) -> np.ndarray:
    """Build a constant-envelope FM IQ stream from an MPX of tones.

    Unlike ``_synthesize_clean_capture`` (which uses an AWGN IQ stand-in),
    this genuinely FM-modulates the multiplex so the IQ has the
    constant-envelope property the front-end check relies on — exactly what a
    healthy capture of a real station looks like.
    """
    rng = np.random.default_rng(seed)
    n = int(fs * duration_sec)
    t = np.arange(n) / fs
    mpx = np.zeros(n, dtype=np.float64)
    for freq, amp in subcarriers.items():
        mpx += amp * np.cos(2 * math.pi * freq * t + rng.uniform(0, 2 * math.pi))
    mpx /= max(np.max(np.abs(mpx)), 1e-9)
    phase = 2 * math.pi * np.cumsum(mpx) * deviation_hz / fs
    return np.exp(1j * phase).astype(np.complex64)


def test_noise_capture_flags_no_carrier_not_if_filter():
    """A capture that is pure band-limited noise (antenna disconnected /
    gain too low / tuned off-channel) must be reported as ``no_carrier`` —
    NOT as an IF/anti-alias filter problem or a discriminator-click problem.

    This is the operator-facing regression behind the screenshot: a strong
    RSSI + "Locked" receiver whose audio is white noise.  Rayleigh-distributed
    noise has an envelope P99/P01 ≈ 20 and a ~30% click rate, which previously
    produced a confidently-wrong "IF filter too narrow" critical.
    """
    fs = 256_000
    rng = np.random.default_rng(2026)
    n = fs * 1
    # Band-limit complex AWGN to the post-decimation passband so it matches a
    # real noise-floor capture (flat to ~108 kHz, then rolls off).
    noise = (rng.standard_normal(n) + 1j * rng.standard_normal(n)).astype(np.complex64)
    from scipy import signal as _sig  # local import; scipy is a test dep
    h = _sig.firwin(257, 108_000.0, window="blackman", fs=fs)
    iq = _sig.lfilter(h, 1.0, noise).astype(np.complex64)

    diag = analyze_capture(iq, fs)
    out = diagnostic_to_dict(diag)
    fe = out["frontend"]
    codes = {f["code"] for f in fe["findings"]}

    # The whole point: it's a no-carrier capture, and we must NOT mislead the
    # operator toward the IF filter or the discriminator.
    assert "no_carrier" in codes, fe["findings"]
    assert "envelope_ratio" not in codes, fe["findings"]
    assert "discriminator_clicks" not in codes, fe["findings"]
    assert fe["verdict"] == "critical"

    # Summary leads with the real cause and mentions the actionable checks.
    summary = " ".join(out["summary_messages"]).lower()
    assert "no fm carrier" in summary or "no carrier" in summary
    assert "antenna" in summary or "gain" in summary


def test_clean_fm_carrier_is_not_flagged_no_carrier():
    """A genuine constant-envelope FM signal must never be mistaken for the
    noise floor, even though a clipped FM signal can legitimately raise the
    envelope ratio."""
    fs = 256_000
    iq = _synthesize_fm_carrier(
        fs=fs,
        duration_sec=1.0,
        subcarriers={19_000: 0.6, 38_000: 0.3, 57_000: 0.1},
    )
    fe = analyze_iq_frontend(iq, fs)
    codes = {f["code"] for f in fe.findings}
    assert "no_carrier" not in codes, fe.findings
    # Constant-envelope FM: P99/P01 stays near 1 and clicks stay low.
    assert fe.envelope_ratio < radio_diagnostics.ENVELOPE_RATIO_NO_CARRIER, fe.envelope_ratio
    assert fe.click_rate_pct < radio_diagnostics.CLICK_RATE_NO_CARRIER_PCT, fe.click_rate_pct


def test_diagnostic_to_dict_is_json_serialisable():
    """The dict returned by ``diagnostic_to_dict`` must round-trip
    through ``json.dumps`` so the Flask endpoint can return it directly."""
    import json
    fs = 256_000
    iq, mpx = _synthesize_clean_capture(
        fs=fs, duration_sec=0.5,
        subcarriers={19_000: 0.1, 57_000: 0.06},
    )
    out = diagnostic_to_dict(analyze_capture(iq, fs, multiplex=mpx))
    payload = json.dumps(out)  # must not raise
    assert "subcarriers" in payload
    assert "frontend" in payload
    assert "summary_verdict" in payload


def test_empty_iq_raises_value_error():
    with pytest.raises(ValueError):
        analyze_iq_frontend(np.zeros(0, dtype=np.complex64), 256_000)


# ──────────────────────────────────────────────────────────────────────────────
# End-to-end against a real bug capture committed to the repo
# ──────────────────────────────────────────────────────────────────────────────
_BUG_CAPTURE = _ROOT / "bugs" / "iq_sdr_256000Hz_1778772958_211c2893.npz"


@pytest.mark.skipif(not _BUG_CAPTURE.is_file(), reason="bug capture not present")
def test_real_bug_capture_diagnoses_rtl_sdr_saturation_and_rbds_present():
    """Smoke test against the operator-reported capture in bugs/.

    This capture is from a real station that transmits RBDS at high
    power.  The IQ shows extreme front-end saturation (~69% of samples
    at |I or Q| >= 0.95) AND the 57 kHz RBDS lobe is clearly present
    (~14 dB SNR).  The analyzer must:

      1. Flag the capture as ``critical`` (saturation).
      2. Lift ``rbds_suppression_risk`` off ``none``.
      3. Report the 57 kHz RBDS subcarrier as ``present`` — i.e. confirm
         to the operator that yes, RBDS IS in the file, the rtl-sdr is
         just mangling it.
    """
    data = np.load(_BUG_CAPTURE)
    iq = data["iq"]
    mpx = data["multiplex"] if "multiplex" in data.files else None
    diag = analyze_capture(iq, 256_000, multiplex=mpx)
    out = diagnostic_to_dict(diag)

    fe = out["frontend"]
    assert fe["clipping_fraction"] > 0.10, fe
    assert fe["verdict"] == "critical"
    assert "saturation" in {f["code"] for f in fe["findings"]}

    sc_by_id = {s["id"]: s for s in out["subcarriers"]}
    rbds = sc_by_id["rbds_57k"]
    assert rbds["present"], rbds
    # Pilot must be very strong on this capture — the station is clearly
    # broadcasting, so a low pilot SNR would indicate the analyzer is
    # broken, not the station.
    assert sc_by_id["pilot_19k"]["present"]
    assert sc_by_id["pilot_19k"]["snr_db"] >= 20.0

    # Suppression knob must be elevated or high — that's the whole point
    # of this dashboard: surface the front-end as the cause.
    assert out["rbds_suppression_risk"] in ("elevated", "high")
