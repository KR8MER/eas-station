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

Regression tests for the live spectrum frequency axis.

Reported live on the SDR Diagnostics page: an FM broadcast station tuned
at 93.9 MHz filled a Live Waterfall / Spectrum Scope axis labelled
93.388-94.412 MHz -- a 1.024 MHz span. A US FM channel is 200 kHz wide,
so the picture was physically impossible.

Root cause: the FFT behind both views runs on samples pulled from the
ring buffer, which sit *after* the early-decimation stage (see
app_core/radio/decimation.py). On a receiver configured for 1.024 MHz
the decimator runs at factor 4, so those samples are clocked at 256 kHz
and the bins cover 256 kHz of RF. But the SDR service never published
freq_min/freq_max, so the web route fell back to
``receiver.frequency_hz +/- receiver.sample_rate / 2`` -- the *configured
hardware* rate -- and drew the axis 4x too wide. A ~200 kHz signal
occupying ~78% of a 256 kHz span was therefore labelled as occupying
~20% of a megahertz.
"""

from __future__ import annotations

import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app_core.radio.decimation import (
    EARLY_DECIM_TARGET_RATE,
    early_decimation_factor,
    effective_sample_rate,
)
from webapp.radio_settings.routes_signal import _spectrum_axis


class _FakeReceiver:
    """Minimal stand-in for a RadioReceiver row."""

    def __init__(self, sample_rate, frequency_hz=93_900_000, driver="airspy"):
        self.sample_rate = sample_rate
        self.frequency_hz = frequency_hz
        self.driver = driver


# --------------------------------------------------------------------------
# Decimation math
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    "configured, expected_factor, expected_effective",
    [
        (250_000, 1, 250_000),          # at target: untouched
        (500_000, 1, 500_000),          # exactly 2x target: still untouched
        (1_024_000, 4, 256_000),        # the reported receiver
        (2_400_000, 9, 266_666),        # RTL-SDR max
        (2_500_000, 10, 250_000),       # Airspy
        (10_000_000, 40, 250_000),      # Airspy high rate
    ],
)
def test_effective_rate_matches_driver_math(
    configured, expected_factor, expected_effective
):
    assert early_decimation_factor(configured) == expected_factor
    assert effective_sample_rate(configured) == expected_effective


def test_decimation_helpers_tolerate_missing_rate():
    for bad in (None, 0, "", "not-a-number"):
        assert early_decimation_factor(bad) == 1
        assert effective_sample_rate(bad) == 0


def test_driver_uses_the_shared_helper():
    """The driver must not carry its own copy of the decimation math."""
    from app_core.radio import drivers

    source = pathlib.Path(drivers.__file__).with_suffix(".py").read_text()
    assert "early_decimation_factor(self.config.sample_rate)" in source
    assert "effective_sample_rate(self.config.sample_rate)" in source
    assert drivers.EARLY_DECIM_TARGET_RATE == EARLY_DECIM_TARGET_RATE


# --------------------------------------------------------------------------
# The axis itself -- the actual reported bug
# --------------------------------------------------------------------------

def test_axis_uses_published_span_not_configured_rate():
    """The reported case: 1.024 MHz configured, 256 kHz actually covered."""
    receiver = _FakeReceiver(sample_rate=1_024_000)
    payload = {
        "sample_rate": 256_000,          # what the service publishes
        "hardware_sample_rate": 1_024_000,
        "early_decim_factor": 4,
        "center_frequency": 93_900_000,
        "freq_min": 93_900_000 - 128_000,
        "freq_max": 93_900_000 + 128_000,
    }

    axis = _spectrum_axis(payload, receiver)

    span = axis["freq_max"] - axis["freq_min"]
    assert span == 256_000
    # The bug drew this span; assert we never regress to it.
    assert span != 1_024_000
    assert axis["freq_min"] == 93_772_000
    assert axis["freq_max"] == 94_028_000
    assert axis["hardware_sample_rate"] == 1_024_000
    assert axis["early_decim_factor"] == 4


def test_axis_recomputes_span_when_service_omits_it():
    """An older sdr-service publishes no freq_min/freq_max/decim factor.

    The route must still land on the effective span rather than falling
    back to the configured hardware rate, which is what produced the
    original 4x-too-wide axis.
    """
    receiver = _FakeReceiver(sample_rate=1_024_000)

    axis = _spectrum_axis({"center_frequency": 93_900_000}, receiver)

    assert axis["sample_rate"] == 256_000
    assert axis["early_decim_factor"] == 4
    assert axis["freq_max"] - axis["freq_min"] == 256_000


def test_fm_broadcast_occupies_a_plausible_fraction_of_the_span():
    """A 200 kHz FM channel must not fit inside a fraction of the axis.

    This is the operator-facing sanity check from the bug report: on the
    broken axis a full-bandwidth FM signal appeared to be ~1 MHz wide.
    """
    receiver = _FakeReceiver(sample_rate=1_024_000)
    axis = _spectrum_axis({"center_frequency": 93_900_000}, receiver)

    fm_channel_hz = 200_000
    span = axis["freq_max"] - axis["freq_min"]
    occupancy = fm_channel_hz / span

    # ~78% of the 256 kHz window. On the broken 1.024 MHz axis this was
    # ~20%, meaning the visible signal had to be read as 1 MHz wide.
    assert 0.7 <= occupancy <= 0.85


def test_axis_handles_untouched_low_rate_receiver():
    """Below the decimation threshold, configured rate == span."""
    receiver = _FakeReceiver(sample_rate=250_000)

    axis = _spectrum_axis({"center_frequency": 162_400_000}, receiver)

    assert axis["sample_rate"] == 250_000
    assert axis["early_decim_factor"] == 1
    assert axis["freq_max"] - axis["freq_min"] == 250_000


def test_axis_survives_missing_centre_frequency():
    receiver = _FakeReceiver(sample_rate=1_024_000, frequency_hz=None)

    axis = _spectrum_axis({}, receiver)

    assert axis["freq_min"] is None
    assert axis["freq_max"] is None
    assert axis["sample_rate"] == 256_000


def test_axis_survives_empty_payload_and_unconfigured_receiver():
    receiver = _FakeReceiver(sample_rate=None, frequency_hz=None)

    axis = _spectrum_axis(None, receiver)

    assert axis["sample_rate"] == 0
    assert axis["freq_min"] is None
    assert axis["freq_max"] is None


# --------------------------------------------------------------------------
# What the SDR service publishes
# --------------------------------------------------------------------------

def test_service_publishes_the_effective_span():
    import sdr_hardware_service as svc

    payload = svc.build_spectrum_payload(
        identifier="wxj93",
        spectrum=[0.5] * 8,
        effective_rate=256_000,
        center_frequency=93_900_000,
        hardware_sample_rate=1_024_000,
        early_decim_factor=4,
        timestamp=1234.0,
    )

    assert payload["freq_min"] == 93_772_000
    assert payload["freq_max"] == 94_028_000
    assert payload["freq_max"] - payload["freq_min"] == 256_000
    assert payload["sample_rate"] == 256_000
    assert payload["hardware_sample_rate"] == 1_024_000
    assert payload["early_decim_factor"] == 4
    assert payload["status"] == "available"


def test_service_payload_survives_missing_centre_frequency():
    import sdr_hardware_service as svc

    payload = svc.build_spectrum_payload(
        identifier="wxj93",
        spectrum=[],
        effective_rate=256_000,
        center_frequency=None,
    )

    assert payload["freq_min"] is None
    assert payload["freq_max"] is None
    assert payload["early_decim_factor"] == 1


def test_published_payload_round_trips_through_the_route_helper():
    """End to end: what the service publishes is what the axis renders."""
    import sdr_hardware_service as svc

    payload = svc.build_spectrum_payload(
        identifier="wxj93",
        spectrum=[0.5] * 8,
        effective_rate=256_000,
        center_frequency=93_900_000,
        hardware_sample_rate=1_024_000,
        early_decim_factor=4,
    )
    axis = _spectrum_axis(payload, _FakeReceiver(sample_rate=1_024_000))

    assert axis["freq_min"] == payload["freq_min"]
    assert axis["freq_max"] == payload["freq_max"]
    assert axis["freq_max"] - axis["freq_min"] == 256_000


# --------------------------------------------------------------------------
# Capture duration -> sample count
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    "module_name",
    [
        "webapp.radio_settings.routes_diagnostics_waterfall",
        "webapp.radio_settings.routes_diagnostics_capture",
        "webapp.radio_settings.routes_diagnostics_analyze",
    ],
)
def test_capture_endpoints_convert_duration_at_effective_rate(module_name):
    """Captures tap the ring buffer, so duration converts at the effective rate.

    Converting at the configured rate asked for decim-factor times too
    many samples -- an Airspy at 2.5 MHz turned a 5 s request into a 50 s
    capture, which always exceeded the wait budget.
    """
    import importlib

    module = importlib.import_module(module_name)
    source = pathlib.Path(module.__file__).read_text()
    assert "effective_sample_rate(receiver_record.sample_rate)" in source
    assert "effective_rate = receiver_record.sample_rate or 250_000" not in source


# --------------------------------------------------------------------------
# Live waterfall / scope zoom invariants
# --------------------------------------------------------------------------
#
# The zoom feature rests on a few non-obvious properties of the template's
# JavaScript that are easy to undo by accident. These assert the contract
# in the spirit of tests/test_map_theme.py, which likewise guards template
# behaviour that has no Python surface.

DIAGNOSTICS_HTML = ROOT / "templates" / "admin" / "radio_diagnostics.html"


def _diagnostics_source() -> str:
    return DIAGNOSTICS_HTML.read_text()


def test_waterfall_history_stores_raw_values_not_pixels():
    """The scrollback buffer must hold per-bin power, not finished RGBA.

    Zoom re-renders the whole history at the current crop. If the buffer
    goes back to storing rasterised pixels, zoomed history degrades to
    upscaled blocks -- it cannot recover detail that was already flattened
    to screen resolution when the row was stored.
    """
    src = _diagnostics_source()
    assert "state.buffer = new Uint8Array(nFreq * LIVE_WF_HEIGHT);" in src
    assert "new Uint8ClampedArray(nFreq * LIVE_WF_HEIGHT * 4)" not in src


def test_zoom_is_bounded_by_real_fft_resolution():
    """The UI must not offer zoom past the resolution the FFT actually has."""
    src = _diagnostics_source()
    assert "const ZOOM_MAX =" in src
    assert "const ZOOM_MIN_BINS =" in src
    # zoomRange must clamp the window inside [0, nFreq].
    assert "Math.min(nFreq - count, start)" in src


def test_axis_and_status_follow_the_visible_window():
    """Labels must describe the crop, not the full span.

    A zoom that leaves the axis reading the full span would recreate the
    exact class of bug this page already shipped once: a frequency label
    that does not match the picture under it.
    """
    src = _diagnostics_source()
    assert "function visibleFreqRange(state, payload)" in src
    # Both views render their axis through the shared, zoom-aware helper.
    assert src.count("renderSpectrumAxis(state, payload,") >= 2
    # The span readout takes the zoom state so it can report the crop.
    assert "function spectrumSpanLabel(payload, state, nFreq)" in src


def test_scope_peak_hold_is_indexed_by_absolute_bin():
    """Panning must not discard peaks accumulated off-screen."""
    src = _diagnostics_source()
    assert "state.scopePeak = new Float32Array(spectrum);" in src
    assert "for (let i = binStart; i < binEnd; i++)" in src


def test_zoom_gestures_leave_vertical_page_scroll_alone():
    """On a phone, claiming both axes would trap the page scroll."""
    src = _diagnostics_source()
    assert "canvas.style.touchAction = 'pan-y';" in src
