"""Regression tests for the endless stall/restart cycle (audio never recovering).

Production symptom: the Audio Alerts log filled for hours with the same two
sources repeating ``stall, stall, stall, error, error`` roughly every three
minutes, indefinitely.

Root cause: ``AudioSourceAdapter.restart()`` cleared the restart circuit
breaker (``_consecutive_failed_restarts`` / ``_quarantined_until``) whenever
``start()`` returned True.  But ``start()`` only proves the capture *launched*
— a dead stream URL or a dead SDR relaunches cleanly every time while never
delivering a sample.  So for exactly the failure mode the breaker exists to
catch, it was unreachable: the monitor escalated to ERROR, set a flat 60s
quarantine, restarted after it lapsed, had the quarantine wiped by that
restart, stalled again, and repeated forever.

The fix has three parts, one test group each:
  1. only observed audio (``note_healthy``) clears the breaker;
  2. quarantine backs off exponentially instead of staying at 60s;
  3. alerts for a source stuck failing are deduplicated by severity.
"""
import os
import sys
import threading
import time

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

# Import the real package rather than stubbing the web/DB stack.
# tests/test_stall_detection_fix.py loads this module via a stubbed
# ``app_core`` whose ``__path__`` is empty, which makes ``app_core.audio``
# unimportable for every test file collected after it.  That file happens to
# sort last today so nothing notices; this one does not, so it must not
# repeat the trick.
from app_core.audio.ingest import (  # noqa: E402
    AudioIngestController,
    AudioSourceAdapter,
    AudioSourceConfig,
    AudioSourceStatus,
    AudioSourceType,
)


class FlakyAdapter(AudioSourceAdapter):
    """Launches cleanly every time; delivers audio only while ``alive`` is set.

    This is the shape of the sources that caused the production incident: a
    stream whose ffmpeg spawns fine against a URL that is off the air.
    """

    def __init__(self, name="flaky-source", alive=False):
        super().__init__(AudioSourceConfig(
            source_type=AudioSourceType.STREAM,
            name=name,
            enabled=True,
            buffer_size=256,
        ))
        self.alive = threading.Event()
        if alive:
            self.alive.set()
        self.start_calls = 0

    def _start_capture(self) -> None:
        self.start_calls += 1  # always "succeeds"

    def _stop_capture(self) -> None:
        pass

    def _read_audio_chunk(self):
        time.sleep(0.01)
        if not self.alive.is_set():
            return None
        return np.zeros(256, dtype=np.float32)


def _make_controller(**kwargs):
    controller = AudioIngestController(
        enable_monitor=True,
        monitor_interval=0.1,
        stall_seconds=1.0,
        **kwargs,
    )
    controller._monitor_grace_period = 0.3
    controller._stall_quarantine_threshold = 3
    return controller


# ---------------------------------------------------------------------------
# 1. A launch-only restart must NOT clear the circuit breaker
# ---------------------------------------------------------------------------
def test_successful_launch_does_not_clear_circuit_breaker():
    """restart() succeeding on launch must leave the breaker armed.

    This is the exact defect: ``start()`` returning True was treated as proof
    of recovery, so quarantine could never accumulate for a source that always
    launches and never delivers.
    """
    adapter = FlakyAdapter()
    adapter._consecutive_failed_restarts = 2
    adapter._quarantine_escalations = 1

    assert adapter.restart("test") is True, "launch was expected to succeed"

    assert adapter._consecutive_failed_restarts == 2, (
        "a restart that only launched the capture must not reset the "
        "failed-restart counter"
    )
    assert adapter._quarantine_escalations == 1, (
        "a restart that only launched the capture must not reset the backoff"
    )
    assert adapter._restart_unconfirmed is True, (
        "restart should be marked provisional until audio is observed"
    )
    adapter.stop()


def test_note_healthy_clears_circuit_breaker():
    """Observed audio is the one thing that clears the breaker."""
    adapter = FlakyAdapter()
    adapter._consecutive_failed_restarts = 3
    adapter._quarantine_escalations = 2
    adapter._quarantined_until = time.time() + 600
    adapter._restart_unconfirmed = True

    adapter.note_healthy()

    assert adapter._consecutive_failed_restarts == 0
    assert adapter._quarantine_escalations == 0
    assert adapter.is_quarantined() is False
    assert adapter._restart_unconfirmed is False


# ---------------------------------------------------------------------------
# 2. Quarantine backs off exponentially
# ---------------------------------------------------------------------------
def test_quarantine_backoff_doubles_and_caps():
    adapter = FlakyAdapter()
    adapter._quarantine_seconds = 60.0
    adapter._max_quarantine_seconds = 900.0

    observed = []
    for _ in range(6):
        observed.append(round(adapter.enter_quarantine()))
        adapter._quarantined_until = 0.0  # let the next call proceed

    assert observed == [60, 120, 240, 480, 900, 900], (
        f"expected doubling capped at 900s, got {observed}"
    )


def test_quarantine_backoff_resets_after_recovery():
    adapter = FlakyAdapter()
    adapter.enter_quarantine()
    adapter.enter_quarantine()
    assert adapter._quarantine_escalations == 2

    adapter.note_healthy()

    assert adapter.quarantine_backoff_seconds() == adapter._quarantine_seconds, (
        "a recovered source must start over at the base cooldown"
    )


# ---------------------------------------------------------------------------
# 3. Alert dedup for a source stuck failing
# ---------------------------------------------------------------------------
def test_repeat_alerts_are_deduplicated_by_severity():
    controller = _make_controller()
    now = time.time()

    # First stall is reported.
    assert controller._should_alert_state("src", "stall", now) is True
    # A repeat of the same state inside the window is not.
    assert controller._should_alert_state("src", "stall", now + 1) is False
    # Escalation to ERROR breaks the dedup — severity increased.
    assert controller._should_alert_state("src", "error", now + 2) is True
    # Cycling back down to a stall does NOT re-alert: this alternation is
    # exactly what flooded the log.
    assert controller._should_alert_state("src", "stall", now + 3) is False
    assert controller._should_alert_state("src", "error", now + 4) is False
    # After the re-notify window a stuck source is surfaced again.
    later = now + controller._alert_renotify_seconds + 5
    assert controller._should_alert_state("src", "error", later) is True


def test_alert_dedup_resets_once_source_is_healthy():
    controller = _make_controller()
    now = time.time()
    assert controller._should_alert_state("src", "error", now) is True
    assert controller._should_alert_state("src", "error", now + 1) is False

    controller._alerted_states.pop("src", None)  # what the healthy branch does

    assert controller._should_alert_state("src", "error", now + 2) is True, (
        "a source that recovered and broke again must alert afresh"
    )


# ---------------------------------------------------------------------------
# 4. End-to-end: the cycle terminates instead of running forever
# ---------------------------------------------------------------------------
@pytest.mark.slow
def test_dead_source_stops_cycling_and_backs_off():
    """The production symptom, end to end.

    Before the fix this emitted ~21 alerts and 14 start() calls in 30s and
    would have kept going indefinitely at that rate.
    """
    adapter = FlakyAdapter(name="dead-stream")
    adapter._quarantine_seconds = 2.0
    controller = _make_controller()

    alerts = []
    lock = threading.Lock()

    def _record(source_name, event_type, message):
        with lock:
            alerts.append(event_type)

    controller.set_source_alert_callback(_record)
    controller.add_source(adapter)
    adapter.start()
    try:
        time.sleep(25)
        with lock:
            fired = list(alerts)
        escalations = adapter._quarantine_escalations
    finally:
        controller.stop_all()

    assert escalations >= 2, (
        f"expected quarantine to escalate under a sustained outage, got {escalations}"
    )
    assert len(fired) <= 4, (
        f"a permanently dead source should not flood the alert log; got {len(fired)}: {fired}"
    )
    assert "stall" in fired and "error" in fired, (
        f"the outage must still be reported at all; got {fired}"
    )


@pytest.mark.slow
def test_source_recovers_and_realerts_on_next_failure():
    """Backoff must not block a genuine recovery."""
    adapter = FlakyAdapter(name="recovering-stream")
    adapter._quarantine_seconds = 1.0
    controller = _make_controller()
    controller.add_source(adapter)
    adapter.start()
    try:
        # Let it fail and escalate.
        deadline = time.time() + 20
        while adapter._quarantine_escalations == 0 and time.time() < deadline:
            time.sleep(0.2)
        assert adapter._quarantine_escalations > 0, "expected an escalation"

        # Upstream comes back.
        adapter.alive.set()
        adapter._quarantined_until = 0.0
        if adapter.status != AudioSourceStatus.RUNNING:
            adapter.restart("upstream restored")

        deadline = time.time() + 20
        while adapter._quarantine_escalations != 0 and time.time() < deadline:
            time.sleep(0.2)

        assert adapter._quarantine_escalations == 0, (
            "observed audio must clear the backoff"
        )
        assert adapter._restart_unconfirmed is False
        assert not adapter.is_quarantined()
    finally:
        controller.stop_all()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
