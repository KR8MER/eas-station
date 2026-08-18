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

Tests for dead-air (silence) monitoring.

The load-bearing case is the one a level threshold cannot see. When an FM
station leaves the air, the receiver does not go quiet -- it outputs
unsquelched noise at full scale, tens of dB above any sane silence
threshold. Every level-only detector in this codebase reports "audio
present" for that, which is precisely the failure an EAS monitoring
station most needs to know about.
"""

from __future__ import annotations

import pathlib
import sys
import time

import numpy as np
import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app_core.audio.silence import (  # noqa: E402
    DEFAULT_FLATNESS_THRESHOLD,
    SilenceCriteria,
    SilenceMonitor,
    classify,
    get_default_criteria,
    set_default_criteria,
    spectral_flatness,
)

SR = 22050
_DUR = 0.5


def _t(seconds: float = _DUR):
    return np.arange(int(SR * seconds)) / SR


def _hiss(amplitude: float, seed: int = 0):
    """Unsquelched receiver noise -- what a dead FM carrier sounds like."""
    rng = np.random.default_rng(seed)
    return (rng.standard_normal(_t().size) * amplitude).astype(np.float32)


def _speech(amplitude: float):
    """Harmonic stack with formant-like rolloff; stands in for programme."""
    t = _t()
    x = sum((1.0 / k) * np.sin(2 * np.pi * 120 * k * t) for k in range(1, 25))
    return (x / np.abs(x).max() * amplitude).astype(np.float32)


def _rms_db(x) -> float:
    rms = float(np.sqrt(np.mean(np.asarray(x, dtype=np.float64) ** 2)))
    return 20 * np.log10(max(rms, 1e-12))


# --------------------------------------------------------------------------
# Spectral flatness
# --------------------------------------------------------------------------

def test_flatness_separates_noise_from_programme_by_orders_of_magnitude():
    """The whole design rests on this gap being wide, not marginal."""
    noise = spectral_flatness(_hiss(0.3))
    speech = spectral_flatness(_speech(0.3))

    assert noise is not None and speech is not None
    assert noise > 0.3, f"receiver hiss should read flat, got {noise}"
    assert speech < 0.05, f"programme audio should read structured, got {speech}"
    # At least an order of magnitude of headroom either side of the default.
    assert speech < DEFAULT_FLATNESS_THRESHOLD < noise


def test_flatness_is_level_invariant():
    """Flatness must not track loudness, or the axis is just a level test."""
    quiet = spectral_flatness(_hiss(0.01))
    loud = spectral_flatness(_hiss(0.5))
    assert quiet is not None and loud is not None
    assert abs(quiet - loud) < 0.1


def test_flatness_returns_none_for_a_too_short_chunk():
    assert spectral_flatness(np.zeros(16, dtype=np.float32)) is None


# --------------------------------------------------------------------------
# Classification -- the off-air case a level threshold misses
# --------------------------------------------------------------------------

def test_open_carrier_is_silence_even_at_full_scale():
    """The reported gap: a dead FM station is loud, not quiet.

    A level-only detector calls this "audio present" at any threshold that
    does not also mute real programme material.
    """
    loud_hiss = _hiss(0.5)
    level = _rms_db(loud_hiss)
    assert level > -10, "precondition: this signal is loud"

    verdict = classify(loud_hiss, level, SilenceCriteria())

    assert verdict.is_silent
    assert verdict.reason == "open_carrier"
    # The level axis alone would not have caught it.
    assert level > SilenceCriteria().level_threshold_db


def test_digital_silence_is_caught_by_the_level_axis():
    samples = np.zeros(int(SR * _DUR), dtype=np.float32)
    verdict = classify(samples, _rms_db(samples), SilenceCriteria())
    assert verdict.is_silent
    assert verdict.reason == "level"


def test_programme_audio_is_not_silence():
    speech = _speech(0.1)
    verdict = classify(speech, _rms_db(speech), SilenceCriteria())
    assert not verdict.is_silent
    assert verdict.reason == "audio"


def test_a_quiet_passage_is_not_silence():
    """A soft passage must not alarm.

    This is why the level floor sits at -65 dBFS rather than -55: real
    programme material can sit near -56 dBFS, and alarming on that is a
    false positive that would train operators to ignore the buzzer.
    """
    quiet = _speech(0.003)
    level = _rms_db(quiet)
    assert -60 < level < -50, f"precondition: quiet but real, got {level}"

    verdict = classify(quiet, level, SilenceCriteria())
    assert not verdict.is_silent


def test_open_carrier_detection_can_be_switched_off():
    loud_hiss = _hiss(0.5)
    criteria = SilenceCriteria(detect_open_carrier=False)
    verdict = classify(loud_hiss, _rms_db(loud_hiss), criteria)
    assert not verdict.is_silent


def test_disabled_criteria_never_reports_silence():
    samples = np.zeros(int(SR * _DUR), dtype=np.float32)
    verdict = classify(samples, -240.0, SilenceCriteria(enabled=False))
    assert not verdict.is_silent
    assert verdict.reason == "disabled"


# --------------------------------------------------------------------------
# Debounce
# --------------------------------------------------------------------------

def test_short_silence_does_not_alarm():
    """A pause between programme elements must not sound the buzzer."""
    monitor = SilenceMonitor("test", SilenceCriteria(duration_seconds=1.0))
    deadline = time.time() + 0.4
    while time.time() < deadline:
        chunk = _hiss(0.3)
        monitor.process(chunk, _rms_db(chunk))
        time.sleep(0.05)
    assert not monitor.is_silent()


def test_sustained_silence_alarms_then_clears_on_recovery():
    events = []
    monitor = SilenceMonitor(
        "test",
        SilenceCriteria(duration_seconds=0.5),
        on_change=lambda name, silent, verdict: events.append((silent, verdict.reason)),
    )

    deadline = time.time() + 1.2
    while time.time() < deadline and not monitor.is_silent():
        chunk = _hiss(0.3)
        monitor.process(chunk, _rms_db(chunk))
        time.sleep(0.05)
    assert monitor.is_silent(), "sustained open carrier must alarm"

    speech = _speech(0.1)
    monitor.process(speech, _rms_db(speech))
    assert not monitor.is_silent(), "must clear when programme audio returns"

    assert events[0] == (True, "open_carrier")
    assert events[-1][0] is False


def test_a_restart_into_a_dead_source_still_debounces():
    """Regression: the first chunk used to alarm instantly.

    ``SilenceDetector`` treats "never saw a signal" as immediate silence,
    which bypasses the hold-off entirely. On a service restart -- where a
    source simply has not produced its first audio yet -- that sounded the
    rack buzzer straight away.
    """
    monitor = SilenceMonitor("test", SilenceCriteria(duration_seconds=5.0))
    chunk = _hiss(0.3)
    monitor.process(chunk, _rms_db(chunk))
    assert not monitor.is_silent()


def test_snapshot_is_json_safe_and_describes_the_fault():
    monitor = SilenceMonitor("wxj93", SilenceCriteria(duration_seconds=0.2))
    chunk = _hiss(0.4)
    monitor.process(chunk, _rms_db(chunk))
    snap = monitor.snapshot()

    assert set(snap) >= {"enabled", "silent", "reason", "detail", "level_db"}
    assert snap["reason"] == "open_carrier"
    assert "open carrier" in snap["detail"]
    import json
    json.dumps(snap)   # must not raise


def test_criteria_are_clamped_to_sane_ranges():
    wild = SilenceCriteria(
        level_threshold_db=999.0,
        flatness_threshold=42.0,
        duration_seconds=-5.0,
    ).sanitized()
    assert wild.level_threshold_db <= 0.0
    assert 0.0 <= wild.flatness_threshold <= 1.0
    assert wild.duration_seconds >= 1.0


def test_station_wide_default_criteria_round_trip():
    """Sources are built from eight call sites; they share one policy."""
    original = get_default_criteria()
    try:
        set_default_criteria(SilenceCriteria(enabled=True, duration_seconds=42.0))
        monitor = SilenceMonitor("inherits-default")
        assert monitor.criteria.enabled
        assert monitor.criteria.duration_seconds == 42.0
    finally:
        set_default_criteria(original)


# --------------------------------------------------------------------------
# Tower light
# --------------------------------------------------------------------------

def _tower_cfg(**kw):
    from app_utils.gpio.tower_light import TowerLightConfig
    return TowerLightConfig(**kw)


def _resolve(**kw):
    from services.gpio.alert_indicators import resolve_tower_state
    base = dict(
        config=_tower_cfg(), broadcast_state={}, incoming_active=False, redis_ok=True
    )
    base.update(kw)
    return resolve_tower_state(**base)


def test_dead_air_outranks_every_alert_indication():
    """A silent monitored source means monitoring has stopped.

    That must not be visually buried by an alert indication -- the alert
    pipeline can look perfectly healthy while the source feeding it is dead.
    """
    assert _resolve(silence_active=True).name == "silence"
    assert _resolve(silence_active=True, active_alert_count=3).name == "silence"
    assert _resolve(
        silence_active=True,
        broadcast_state={"active": True, "event_code": "TOR"},
    ).name == "silence"


def test_redis_loss_still_outranks_dead_air():
    """A dead Redis makes the dead-air reading itself untrustworthy."""
    assert _resolve(silence_active=True, redis_ok=False).name == "fault"


def test_quiet_hours_do_not_hide_dead_air():
    """An overnight schedule must never mask a monitoring outage."""
    from datetime import datetime
    cfg = _tower_cfg(quiet_enabled=True, quiet_start="00:00", quiet_end="23:59")
    state = _resolve(
        config=cfg, silence_active=True, now=datetime(2026, 8, 18, 3, 0)
    )
    assert state.name == "silence"


def test_dead_air_indication_can_be_switched_off():
    cfg = _tower_cfg(silence_enabled=False)
    assert _resolve(config=cfg, silence_active=True).name == "standby"


def test_no_dead_air_leaves_the_ladder_unchanged():
    assert _resolve().name == "standby"
    assert _resolve(active_alert_count=1).name == "active"


# --------------------------------------------------------------------------
# Rack alarm buzzer
# --------------------------------------------------------------------------

class _FakeGPIO:
    def __init__(self):
        self.log = []

    def activate(self, pin, **kwargs):
        self.log.append(("on", pin))

    def deactivate(self, pin, force=False):
        self.log.append(("off", pin))


def test_buzzer_is_level_triggered_and_acknowledgeable():
    """Standard alarm-panel behaviour.

    The buzzer holds while the condition holds (not a pulse), an
    acknowledgement silences it without repeating, and a later outage
    sounds again rather than staying muted.
    """
    from services.gpio.alert_indicators import _drive_silence_buzzer

    gpio = _FakeGPIO()
    state = {"pin": 17, "sounding": False}

    _drive_silence_buzzer(gpio, False, False, state)   # quiet
    _drive_silence_buzzer(gpio, True, False, state)    # dead air -> sound
    _drive_silence_buzzer(gpio, True, False, state)    # held, no repeat
    _drive_silence_buzzer(gpio, True, True, state)     # acknowledged
    _drive_silence_buzzer(gpio, True, True, state)     # stays quiet
    _drive_silence_buzzer(gpio, False, False, state)   # audio back
    _drive_silence_buzzer(gpio, True, False, state)    # next outage

    assert gpio.log == [("on", 17), ("off", 17), ("on", 17)]


def test_buzzer_is_never_keyed_without_a_configured_pin():
    from services.gpio.alert_indicators import _drive_silence_buzzer

    gpio = _FakeGPIO()
    _drive_silence_buzzer(gpio, True, False, {"pin": None})
    assert gpio.log == []


def test_missing_dead_air_key_reads_as_not_alarming(monkeypatch):
    """Absence must not strand the buzzer on.

    The key carries a short TTL, so a missing key means the feature is off
    or the publisher is gone. Neither should hold a rack buzzer down; the
    audio service has its own liveness monitoring.
    """
    from services.gpio import alert_indicators

    class _NoRedis:
        def get(self, *_a, **_kw):
            return None

    # Patch the module object directly rather than by dotted string: the
    # string form resolves differently depending on whether another test
    # has already imported app_core.redis_client, so it passed in
    # isolation and failed in the full suite.
    import app_core.redis_client as redis_client_module

    monkeypatch.setattr(
        redis_client_module, "get_redis_client", lambda *a, **k: _NoRedis()
    )
    state = alert_indicators.read_dead_air_state()
    assert state["active"] is False


# --------------------------------------------------------------------------
# Where the controls live
# --------------------------------------------------------------------------
#
# Dead-air settings were first shipped entirely on the Hardware page,
# beside the tower-light block. That was placement by implementation
# adjacency rather than by task: the thresholds are audio quantities, and
# GPIO is only *today's* output -- an email or SMS notifier added later
# must be able to share the same detection policy without reading it out
# of the GPIO page. These pin the split so it does not drift back.

HARDWARE_HTML = ROOT / "templates" / "admin" / "hardware_settings.html"
AUDIO_HTML = ROOT / "templates" / "admin" / "audio_sources.html"
HEALTH_HTML = ROOT / "templates" / "audio" / "health_dashboard.html"

_DETECTION_FIELDS = (
    "deadAirEnabled",
    "deadAirDuration",
    "deadAirLevel",
    "deadAirFlatness",
    "deadAirOpenCarrier",
)
_OUTPUT_FIELDS = (
    "dead_air_buzzer_gpio_pin",
    "tower_light_silence_color",
    "tower_light_silence_enabled",
)


def test_detection_settings_live_with_the_audio_sources():
    audio = AUDIO_HTML.read_text(encoding="utf-8")
    for field in _DETECTION_FIELDS:
        assert field in audio, f"{field} should be on the audio page"


def test_detection_settings_are_not_on_the_hardware_page():
    """The thresholds must not be editable in two places at once."""
    hardware = HARDWARE_HTML.read_text(encoding="utf-8")
    for field in ("dead_air_enabled", "dead_air_duration_seconds",
                  "dead_air_level_threshold_db",
                  "dead_air_flatness_threshold_pct"):
        assert field not in hardware, f"{field} should have moved off Hardware"


def test_output_wiring_stays_on_the_hardware_page():
    """The buzzer pin and light colour are physical wiring, not policy."""
    hardware = HARDWARE_HTML.read_text(encoding="utf-8")
    for field in _OUTPUT_FIELDS:
        assert field in hardware, f"{field} belongs on Hardware"

    audio = AUDIO_HTML.read_text(encoding="utf-8")
    assert "dead_air_buzzer_gpio_pin" not in audio


def test_acknowledge_lives_on_the_health_dashboard():
    """Acknowledging is an operational act, not configuration.

    It belongs where an operator is already looking when the buzzer is
    sounding, not buried in a settings form.
    """
    health = HEALTH_HTML.read_text(encoding="utf-8")
    assert "deadAirAckBtn" in health
    assert "dead-air-alarm.js" in health

    hardware = HARDWARE_HTML.read_text(encoding="utf-8")
    assert "deadAirAckBtn" not in hardware


def test_the_three_pages_cross_link():
    """Splitting a feature across pages only works if they point at each other."""
    audio = AUDIO_HTML.read_text(encoding="utf-8")
    assert "/admin/hardware" in audio
    assert "/audio/health/dashboard" in audio

    hardware = HARDWARE_HTML.read_text(encoding="utf-8")
    assert "/admin/audio-sources" in hardware

    health = HEALTH_HTML.read_text(encoding="utf-8")
    assert "/admin/audio-sources" in health


def test_both_settings_pages_are_reachable_from_the_navigation():
    """Regression: neither page was ever a NavItem.

    'Station Hardware' is a NavGroup *label*, not a link -- so the
    Hardware Settings page could only be reached by typing the URL or via
    the Admin panel, and /admin/audio-sources was not in the registry at
    all. Both now have entries.
    """
    from webapp.navigation.registry import NAVIGATION

    hrefs, endpoints = set(), set()
    for section in NAVIGATION:
        for group in section.groups:
            for item in group.items:
                if getattr(item, "href", None):
                    hrefs.add(item.href)
                if getattr(item, "endpoint", None):
                    endpoints.add(item.endpoint)

    assert "/admin/audio-sources" in hrefs
    assert "hardware.hardware_settings_page" in endpoints
