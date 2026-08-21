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
# beside the tower-light block, then moved to one station-wide form on the
# Audio Sources page. Both were placement/scope mistakes: the thresholds
# are audio quantities (so GPIO -- only *today's* output -- must not own
# them), and a single shared policy cannot express "alarm on silence for
# this continuous broadcast monitor, never for that state-relay source
# that's supposed to be silent except when relaying an actual alert."
# Detection is per-source now, configured in that source's own Add/Edit
# dialog on the Audio Sources page. These pin the split so it does not
# drift back.

HARDWARE_HTML = ROOT / "templates" / "admin" / "hardware_settings.html"
AUDIO_HTML = ROOT / "templates" / "admin" / "audio_sources.html"
HEALTH_HTML = ROOT / "templates" / "audio" / "health_dashboard.html"

# The Add-Source-modal ids; the Edit modal mirrors these with an "edit"
# prefix (editDeadAirEnabled, etc.) and both are checked below.
_DETECTION_FIELDS = (
    "sourceDeadAirEnabled",
    "sourceDeadAirDuration",
    "sourceDeadAirLevel",
    "sourceDeadAirFlatness",
    "sourceDeadAirOpenCarrier",
)
_EDIT_DETECTION_FIELDS = (
    "editDeadAirEnabled",
    "editDeadAirDuration",
    "editDeadAirLevel",
    "editDeadAirFlatness",
    "editDeadAirOpenCarrier",
)
_OUTPUT_FIELDS = (
    "dead_air_buzzer_gpio_pin",
    "tower_light_silence_color",
    "tower_light_silence_enabled",
)


def test_detection_settings_live_with_the_audio_sources():
    """Detection fields must be on the per-source Add/Edit dialog, not a
    station-wide form -- a single shared policy can't express "alarm for
    this source, never for that one"."""
    audio = AUDIO_HTML.read_text(encoding="utf-8")
    for field in _DETECTION_FIELDS + _EDIT_DETECTION_FIELDS:
        assert field in audio, f"{field} should be on the audio page's source dialog"


def test_detection_fields_are_not_a_station_wide_form():
    """Regression: a single global enabled flag couldn't express per-source
    policy, which is exactly the false-alarm bug this redesign fixed."""
    audio = AUDIO_HTML.read_text(encoding="utf-8")
    assert "deadAirSaveBtn" not in audio, (
        "there is no longer a single form to save -- each source's dialog "
        "saves through the normal create/update source flow"
    )


def test_detection_settings_are_not_on_the_hardware_page():
    """The thresholds must not be editable in two places at once."""
    hardware = HARDWARE_HTML.read_text(encoding="utf-8")
    for field in ("dead_air_enabled", "dead_air_duration_seconds",
                  "dead_air_level_threshold_db",
                  "dead_air_flatness_threshold_pct",
                  "dead_air_detect_open_carrier"):
        assert field not in hardware, f"{field} should have moved off Hardware"


def test_output_wiring_stays_on_the_hardware_page():
    """The buzzer pin and light colour are physical wiring, not policy."""
    hardware = HARDWARE_HTML.read_text(encoding="utf-8")
    for field in _OUTPUT_FIELDS:
        assert field in hardware, f"{field} belongs on Hardware"

    audio = AUDIO_HTML.read_text(encoding="utf-8")
    for field in _OUTPUT_FIELDS:
        assert field not in audio, f"{field} should remain on Hardware only"
    assert "deadAirAckBtn" not in audio, (
        "acknowledging belongs on the health dashboard, not a settings form"
    )


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


# --------------------------------------------------------------------------
# Fixes from code review on PR #2417
# --------------------------------------------------------------------------

ALARM_JS = ROOT / "static" / "js" / "admin" / "dead-air-alarm.js"
SETTINGS_JS = ROOT / "static" / "js" / "admin" / "dead-air-settings.js"


def test_operator_supplied_names_are_never_interpolated_into_html():
    """Source names are free text and reach the browser through Redis.

    ``AudioSource.name`` has no markup validation, so a source named with
    a tag would execute in another operator's session if these renderers
    used innerHTML. Both build text nodes instead.
    """
    for path in (ALARM_JS, SETTINGS_JS):
        src = path.read_text(encoding="utf-8")
        code = "\n".join(
            line for line in src.splitlines()
            if not line.strip().startswith(("//", "*", "/*"))
        )
        assert "innerHTML" not in code, f"{path.name} must not assign innerHTML"
        assert "textContent" in code


def test_settings_js_no_longer_owns_a_save_form():
    """dead-air-settings.js is a status poller now, not a settings form.

    Detection settings save through the per-source Add/Edit dialog (see
    audio_monitoring.js's addAudioSource()/saveEditedSource()), which is
    populated from a fetched source record before it can be submitted, so
    the old "blank input overwrites stored threshold" failure mode this
    test used to guard against cannot occur here anymore.
    """
    src = SETTINGS_JS.read_text(encoding="utf-8")
    assert "dead-air/settings" not in src, (
        "the station-wide settings endpoint was removed; nothing should "
        "still call it"
    )
    assert "pollStatus" in src


def test_status_is_readable_by_the_dashboard_audience():
    """The API must not be stricter than the page that renders it.

    The navigation registry gates Audio Health on the view-role trio. When
    the status endpoint required system.configure instead, a radio watcher
    could open the dashboard while every poll 403'd, so an active alarm
    was invisible to exactly the people meant to watch for it.
    """
    src = (ROOT / "webapp" / "admin" / "audio_ingest"
           / "routes_dead_air.py").read_text(encoding="utf-8")
    status = src.split("def audio_dead_air_status", 1)[0]
    assert "require_any_permission" in status
    for perm in ("alerts.view", "receivers.view", "logs.view"):
        assert perm in status, f"{perm} should be able to read dead-air status"
    # Acknowledging stays privileged, and the response tells the UI so it
    # can hide the control instead of offering a button that only 403s.
    assert "can_acknowledge" in src
    ack_decorators = src.split("def audio_dead_air_acknowledge", 1)[0]
    ack_decorators = ack_decorators.rsplit("@audio_ingest_bp.route", 1)[1]
    assert "require_permission('system.configure')" in ack_decorators


def test_acknowledgement_is_bound_to_an_episode():
    """An unbound ack would sit in Redis and mute the *next* outage.

    The publisher mints an episode id when the alarm goes active and drops
    it on recovery; the ack stores that id, and both the API and the GPIO
    reader compare against it.

    The actual acknowledge logic lives in app_core/audio/dead_air_alarm.py
    (extracted so the GPIO-triggered "Acknowledge Dead Air" input action can
    reuse it instead of duplicating the Redis calls) -- the route just
    delegates to it, which test_route_delegates_to_shared_acknowledge_logic
    below covers.
    """
    core = (ROOT / "app_core" / "audio" / "dead_air_alarm.py").read_text(encoding="utf-8")
    assert "if not state.get(\"active\")" in core, (
        "acknowledging with no active alarm must be refused"
    )
    assert "DEAD_AIR_ACK_KEY, 86400, episode" in core

    service = (ROOT / "eas_monitoring_service.py").read_text(encoding="utf-8")
    assert '"episode": _dead_air_episode' in service
    assert "_dead_air_episode = None" in service

    gpio = (ROOT / "services" / "gpio"
            / "alert_indicators.py").read_text(encoding="utf-8")
    assert "ack == episode" in gpio, (
        "the buzzer must only stay silent for the episode that was acknowledged"
    )


def test_route_delegates_to_shared_acknowledge_logic():
    """The web route must not re-duplicate the Redis-level acknowledge logic
    -- it should call the shared core function so the GPIO input action and
    the web UI can never drift apart."""
    routes = (ROOT / "webapp" / "admin" / "audio_ingest"
              / "routes_dead_air.py").read_text(encoding="utf-8")
    ack = routes.split("def audio_dead_air_acknowledge", 1)[1]
    assert "from app_core.audio.dead_air_alarm import acknowledge_dead_air" in ack
    assert "acknowledge_dead_air(" in ack


# --------------------------------------------------------------------------
# The retired carrier-squelch feature
# --------------------------------------------------------------------------
#
# "Carrier Squelch" gated on the RMS of the *demodulated audio*, not on
# carrier presence, so it muted a feed that was already digitally silent
# (a no-op) and passed full-scale hiss straight through -- the one case its
# own help text promised to mute. Its "raise alarm on carrier loss" option
# wrote a log line and a metadata flag behind one status badge, driving no
# GPIO, tower light or notification, and is superseded by the dead-air
# monitor above, which detects the open-carrier case properly.

def test_carrier_squelch_is_gone_from_the_runtime():
    """No squelch gate may sit in the audio path again.

    A gate keyed on audio level cannot distinguish an off-air carrier from
    programme material -- that is exactly the mistake this codebase already
    made once, and the reason dead-air detection needs spectral flatness.
    """
    sources = (ROOT / "app_core" / "audio" / "sources.py").read_text(encoding="utf-8")
    for token in ("_apply_squelch", "_update_squelch_metadata",
                  "_emit_carrier_event", "squelch"):
        assert token not in sources, f"{token} should be retired from the audio path"


def test_carrier_squelch_is_gone_from_the_model_and_api():
    for rel in (
        ("app_core", "_models_radio.py"),
        ("app_core", "radio", "manager.py"),
        ("app_core", "radio", "schema.py"),
        ("app_core", "radio", "service_config.py"),
        ("app_core", "audio", "source_config.py"),
        ("webapp", "radio_settings", "payload.py"),
        ("webapp", "radio_settings", "serialization.py"),
    ):
        text = ROOT.joinpath(*rel).read_text(encoding="utf-8")
        assert "squelch" not in text.lower(), f"{'/'.join(rel)} still references squelch"


def test_carrier_squelch_is_gone_from_the_receiver_form():
    """The Edit Receiver panel must not offer a control that does nothing."""
    radio_html = (ROOT / "templates" / "admin" / "radio.html").read_text(encoding="utf-8")
    for token in ("Carrier Squelch", "receiverSquelch", "toggleSquelchInputs",
                  "squelch_", "carrier_present", "carrier_alarm"):
        assert token not in radio_html, f"{token} should be gone from the receiver form"


# --------------------------------------------------------------------------
# Per-source criteria (the redesign this file's docstring change is about)
# --------------------------------------------------------------------------
#
# A single station-wide dead-air policy shipped, then had to be redesigned
# per source: an operator with even one source that's supposed to be
# silent except when relaying an actual alert (a state relay, an
# alert-only feed) could not enable dead-air alarming for every other
# source without a permanent false alarm on that one. Confirmed live on
# this station: a source named "ERN-LUC" sat in a false dead-air alarm for
# 39 minutes straight under the old station-wide policy.

class _FakeSourceConfig:
    """Minimal stand-in for AudioSourceConfig's dead_air_* attributes."""

    def __init__(self, **overrides):
        self.dead_air_enabled = overrides.get("dead_air_enabled", False)
        self.dead_air_level_threshold_db = overrides.get(
            "dead_air_level_threshold_db", -65.0
        )
        self.dead_air_detect_open_carrier = overrides.get(
            "dead_air_detect_open_carrier", True
        )
        self.dead_air_flatness_threshold_pct = overrides.get(
            "dead_air_flatness_threshold_pct", 25
        )
        self.dead_air_duration_seconds = overrides.get(
            "dead_air_duration_seconds", 20.0
        )


def test_criteria_from_source_config_disabled_by_default():
    """A source that never opted in must build disabled criteria.

    This is the state-relay / alert-only case: a brand new source, or one
    whose config predates this feature, must never alarm on silence.
    """
    from app_core.audio.silence import criteria_from_source_config

    criteria = criteria_from_source_config(_FakeSourceConfig())
    assert criteria.enabled is False


def test_criteria_from_source_config_is_independent_per_source():
    """Two sources with different policies must not bleed into each other.

    This is the actual bug: a single shared SilenceCriteria object applied
    to every source meant one enabled flag and one threshold set for the
    whole station.
    """
    from app_core.audio.silence import criteria_from_source_config

    relay = criteria_from_source_config(
        _FakeSourceConfig(dead_air_enabled=False)
    )
    broadcast = criteria_from_source_config(
        _FakeSourceConfig(
            dead_air_enabled=True,
            dead_air_level_threshold_db=-70.0,
            dead_air_duration_seconds=45.0,
        )
    )

    assert relay.enabled is False
    assert broadcast.enabled is True
    assert broadcast.level_threshold_db == -70.0
    assert broadcast.duration_seconds == 45.0
    # The flatness threshold is stored as whole percent on the config but
    # consumed as a 0-1 ratio by the monitor.
    assert broadcast.flatness_threshold == pytest.approx(0.25)


def test_criteria_from_source_config_accepts_a_dict_shim():
    """The Redis command handlers apply a config change to a running
    source via a dict, not a real AudioSourceConfig -- getattr's default
    must not choke on that."""
    from app_core.audio.silence import criteria_from_source_config

    class _Shim:
        dead_air_enabled = True

    criteria = criteria_from_source_config(_Shim())
    assert criteria.enabled is True
    assert criteria.level_threshold_db == -65.0  # falls back to the default


# --------------------------------------------------------------------------
# The live false-alarm scenario, as a regression test
# --------------------------------------------------------------------------

def _fake_metadata(*, dead_air_enabled, silent, reason="level", detail="", duration=0.0):
    return {
        "metadata": {
            "dead_air": {
                "enabled": dead_air_enabled,
                "silent": silent,
                "reason": reason,
                "detail": detail,
                "silence_duration_seconds": duration,
            }
        }
    }


def test_disabled_source_never_appears_in_the_published_alarm(monkeypatch):
    """Replays the exact live scenario that motivated the redesign.

    A source with dead-air alarming disabled -- e.g. a state relay that is
    silent 99% of the time by design -- must never show up as "silent" in
    the aggregate published to the GPIO service, no matter how far below
    any threshold its audio level actually sits.
    """
    import eas_monitoring_service as ems

    published = {}

    class _FakeRedis:
        def setex(self, key, ttl, value):
            published["key"] = key
            published["value"] = value

        def delete(self, *_a, **_kw):
            pass

    monkeypatch.setattr(ems, "get_redis_client", lambda: _FakeRedis())
    monkeypatch.setattr(ems, "_dead_air_episode", None)

    sources = {
        # A state-relay source: alarming intentionally disabled, sitting
        # far below any silence threshold (this is the ERN-LUC scenario).
        "ERN-LUC": _fake_metadata(
            dead_air_enabled=False, silent=True, detail="no audio (-78.7 dBFS)",
            duration=2331.6,
        ),
        # A continuous broadcast monitor: alarming enabled and currently
        # fine, so it must not appear either.
        "WXJ93": _fake_metadata(dead_air_enabled=True, silent=False),
    }

    ems._publish_dead_air_state(sources)

    import json
    payload = json.loads(published["value"])
    assert payload["sources"] == {}
    assert payload["active"] is False
    # The station does have at least one source with alarming enabled, so
    # the aggregate must still report the feature as "on" for the UI.
    assert payload["enabled"] is True


def test_enabled_silent_source_does_appear_in_the_published_alarm(monkeypatch):
    """The other half of the same guarantee: a source that opted in and is
    actually silent must still alarm -- the fix must not have gone too far
    and silenced every source."""
    import eas_monitoring_service as ems

    published = {}

    class _FakeRedis:
        def setex(self, key, ttl, value):
            published["value"] = value

        def delete(self, *_a, **_kw):
            pass

    monkeypatch.setattr(ems, "get_redis_client", lambda: _FakeRedis())
    monkeypatch.setattr(ems, "_dead_air_episode", None)

    sources = {
        "WXJ93": _fake_metadata(
            dead_air_enabled=True, silent=True, detail="off-air hiss",
            duration=42.0,
        ),
    }

    ems._publish_dead_air_state(sources)

    import json
    payload = json.loads(published["value"])
    assert payload["active"] is True
    assert "WXJ93" in payload["sources"]


def test_legacy_silence_thresholds_no_longer_derive_from_squelch():
    """The instantaneous silence metric keeps working on its own defaults.

    Its thresholds used to be read off the squelch columns, which was a
    coincidence of naming rather than a real relationship.
    """
    from app_core.audio.ingest import AudioSourceConfig

    assert AudioSourceConfig.silence_threshold_db == -60.0
    assert AudioSourceConfig.silence_duration_seconds == 5.0

    for rel in (("webapp", "admin", "audio_ingest", "radio_sources.py"),
                ("eas_monitoring_service.py",)):
        text = ROOT.joinpath(*rel).read_text(encoding="utf-8")
        assert "AudioSourceConfig.silence_threshold_db" in text
        assert "receiver.squelch" not in text
