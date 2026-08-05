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

"""Guards on the VU meter loop: responsive, but never a CPU sink.

The meters were raised from ~15 fps to ~30 fps. That is only safe because the
per-update cost came down at the same time, and because the ballistics stopped
depending on the frame rate. These tests pin both halves of that bargain — a
future edit that reinstates a per-frame smoothing coefficient, an FFT, or a
per-source AudioContext should fail here rather than in a user's CPU graph.
"""

import json
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
VU_METER_JS = PROJECT_ROOT / "static" / "js" / "realtime-vu-meters.js"


def _source() -> str:
    return VU_METER_JS.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Static guarantees — these run everywhere
# ---------------------------------------------------------------------------

def test_uses_time_domain_not_fft():
    """Level metering must read samples, not spectral magnitudes.

    ``getByteFrequencyData()`` runs an FFT per call and returns per-bin
    magnitudes, which are not signal amplitude — so peak/RMS derived from them
    measured the wrong quantity *and* paid for a transform to do it.
    """
    source = _source()
    assert ".getByteTimeDomainData(" in source
    # Match the call, not the prose: the header comment explains why the FFT
    # variant was dropped and names it.
    assert ".getByteFrequencyData(" not in source, (
        "an FFT per frame per source is both costlier and wrong for a level meter"
    )


def test_single_shared_audio_context():
    """One AudioContext for the page, not one per source.

    Every AudioContext carries its own audio render thread, so a context per
    player multiplied that fixed cost by the number of players.
    """
    source = _source()
    assert source.count("new Ctor()") == 1, (
        "the AudioContext must be constructed in exactly one place"
    )
    assert "function getSharedAudioContext" in source
    assert "new AudioContext(" not in source


def test_loop_is_animation_frame_driven():
    """rAF only — it is display-capped and suspends on a hidden tab."""
    source = _source()
    assert "requestAnimationFrame" in source
    assert "setInterval" not in source, (
        "a timer keeps running while the tab is hidden; rAF does not"
    )


def test_ballistics_are_time_based():
    """Smoothing must be derived from elapsed time, not a per-frame constant."""
    source = _source()
    assert "function smoothingFactor" in source
    assert "Math.exp" in source
    assert "MAX_BALLISTIC_DELTA_S" in source, (
        "the elapsed interval must be clamped, or the first frame after a "
        "hidden tab resumes applies a multi-second decay in one step"
    )


def test_detached_meters_are_pruned():
    """Meters for replaced elements must not be analysed forever.

    The source list re-renders on a timer and rebuilds its audio elements.
    Without pruning, each render's meter stayed in the map and was re-analysed
    every frame against an element that no longer existed.
    """
    source = _source()
    assert "function pruneDetachedMeters" in source
    assert "document.contains" in source
    assert "pruneDetachedMeters()" in source


def test_listeners_are_bound_once_per_element():
    """enableRealtimeVUMeters() is called on every render; listeners are not."""
    source = _source()
    assert "vuMeterBound" in source, (
        "without a bind guard, every re-render stacks another listener set"
    )


def test_dom_writes_are_conditional():
    """Style and text writes are the expensive part; skip the no-op ones."""
    source = _source()
    for cache_key in (
        "renderedPeakWidth",
        "renderedRmsWidth",
        "renderedPeakLabel",
        "renderedPlaying",
    ):
        assert cache_key in source, f"missing write-elision cache: {cache_key}"


# ---------------------------------------------------------------------------
# Behavioural checks — executed through node when it is available
# ---------------------------------------------------------------------------

HARNESS = """
globalThis.window = {};
globalThis.document = {};
%(source)s

function decay(fps, tau, seconds) {
    const dt = 1 / fps;
    let value = 0;
    for (let t = 0; t < seconds; t += dt) {
        value += (-120 - value) * smoothingFactor(dt, tau);
    }
    return value;
}

const out = {
    decays: [10, 15, 30, 60, 144].map((fps) => decay(fps, 0.30, 0.5)),
    width_silence: calculateFillWidth(-120),
    width_floor: calculateFillWidth(-60),
    width_full: calculateFillWidth(0),
    width_nan: calculateFillWidth(NaN),
    label_silence: formatDbLabel(-120),
    label_value: formatDbLabel(-12.34),
    alpha_zero_dt: smoothingFactor(0, 0.3),
    alpha_big_dt: smoothingFactor(10, 0.3),
    exports: Object.keys(globalThis.window),
};
console.log(JSON.stringify(out));
"""


def _run_node():
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not available to execute the VU meter module")

    script = HARNESS % {"source": _source()}
    result = subprocess.run(
        [node, "-e", script],
        capture_output=True,
        text=True,
        timeout=30,
        cwd=PROJECT_ROOT,
    )
    assert result.returncode == 0, f"node failed: {result.stderr[:800]}"
    return json.loads(result.stdout.strip().splitlines()[-1])


def test_decay_is_independent_of_frame_rate():
    """The same half-second of silence must decay the same at any rate.

    This is the property that makes raising the refresh rate safe. With the
    previous fixed per-frame coefficient the same interval landed anywhere
    between roughly -80 dB and the -120 dB floor depending on frame rate, so
    changing the rate silently retuned the meter's ballistics.
    """
    decays = _run_node()["decays"]
    spread = max(decays) - min(decays)
    assert spread < 5.0, (
        f"decay varies by {spread:.1f} dB across 10-144 fps; ballistics are "
        f"still frame-rate dependent: {decays}"
    )


def test_fill_width_bounds():
    data = _run_node()
    assert data["width_silence"] == 0
    assert data["width_nan"] == 0
    assert data["width_floor"] == 0
    assert data["width_full"] == pytest.approx(100.0)


def test_label_formatting():
    data = _run_node()
    assert data["label_silence"] == "-- dBFS"
    assert data["label_value"] == "-12.3 dBFS"


def test_smoothing_factor_bounds():
    """A zero interval must not move the meter; a long one must not overshoot."""
    data = _run_node()
    assert data["alpha_zero_dt"] == 0
    assert 0 < data["alpha_big_dt"] <= 1


def test_public_api_is_preserved():
    """audio_monitoring.html calls these by name."""
    exports = set(_run_node()["exports"])
    assert {
        "enableRealtimeVUMeters",
        "disableRealtimeVUMeters",
        "initializeRealtimeVUMeter",
        "cleanupRealtimeVUMeter",
    } <= exports
