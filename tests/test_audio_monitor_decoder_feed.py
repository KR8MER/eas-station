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

"""The /audio-monitor decoder feed: accurate labelling and visible failures.

The EAS decoder stream is served by ``eas_monitoring_service.py`` on its own
port and reverse-proxied by nginx, so it cannot be exercised through the Flask
test client — and the route is defined inside ``main()``, several hundred lines
deep, which puts it out of reach of an import as well. These tests therefore
pin the two things that are checkable without that service running: the
client-side failure handling in the template, and the server-side pre-flight
that decides a status code before streaming begins.
"""

import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
MONITOR_TEMPLATE = PROJECT_ROOT / "templates" / "audio_monitoring.html"
AUDIO_SERVICE = PROJECT_ROOT / "eas_monitoring_service.py"


def _template() -> str:
    return MONITOR_TEMPLATE.read_text(encoding="utf-8")


def _toggle_function(source: str) -> str:
    """Extract the body of ``toggleEASDecoderAudio``."""
    match = re.search(
        r"function toggleEASDecoderAudio\(button\)\s*\{.*?\n\}\n",
        source,
        flags=re.DOTALL,
    )
    assert match, "toggleEASDecoderAudio() not found in audio_monitoring.html"
    return match.group(0)


# ---------------------------------------------------------------------------
# Stream format labelling
# ---------------------------------------------------------------------------

def test_player_does_not_claim_mp3_encoding():
    """The per-source player streams WAV, so it must not advertise MP3.

    ``/api/audio/stream/<source>`` responds with ``mimetype='audio/wav'`` and
    writes a RIFF header — uncompressed PCM at the source's native rate. The UI
    nevertheless claimed "MP3 Streaming @ 128 kbps" and "Audio compressed to
    MP3 format (10x more efficient than WAV)", which is the opposite of what
    the endpoint does on both counts.
    """
    source = _template()
    for claim in (
        "10x more efficient than WAV",
        "Audio compressed to MP3 format",
        "MP3 Streaming @ 128 kbps",
    ):
        assert claim not in source, f"stale/incorrect stream claim still present: {claim!r}"


def test_audio_stream_endpoint_still_serves_wav():
    """Guard the claim above against the backend changing under it."""
    service = AUDIO_SERVICE.read_text(encoding="utf-8")
    assert "mimetype='audio/wav'" in service


# ---------------------------------------------------------------------------
# Listen button failure handling
# ---------------------------------------------------------------------------

def test_playback_failures_are_still_watched_after_start():
    """A stream that dies mid-listen must surface, not fail silently.

    ``onPlaying`` removed both the 'playing' and 'error' listeners, so once
    playback began nothing was watching. If the audio service restarted or the
    source stopped, the player went quiet while the button still read "Stop"
    and no message appeared anywhere — the feed simply seemed to stop working.
    """
    toggle = _toggle_function(_template())

    assert "_easDropHandler" in toggle, (
        "no post-start drop handler: a mid-stream failure would go unreported"
    )
    assert re.search(r"addEventListener\(\s*['\"]ended['\"]", toggle), (
        "'ended' must be watched — a live stream has no natural end, so it "
        "means the server closed the connection"
    )


def test_stalled_does_not_tear_down_the_player():
    """'stalled' fires on routine jitter and must not kill a healthy stream."""
    toggle = _toggle_function(_template())
    assert not re.search(r"addEventListener\(\s*['\"]stalled['\"]", toggle), (
        "reacting to 'stalled' would tear down streams that are merely "
        "buffering; only 'error' and 'ended' are terminal"
    )


def test_startup_watchdog_exists():
    """A connection that never yields a frame must not hang on 'Loading...'."""
    toggle = _toggle_function(_template())
    assert "startupTimer" in toggle
    # Every path that concludes the start attempt has to cancel the watchdog,
    # or a late timer fires over an already-playing stream.
    assert toggle.count("clearTimeout(startupTimer)") >= 3, (
        "clearTimeout(startupTimer) must run on the success path and on both "
        "failure paths (error event and play() rejection)"
    )


def test_stop_detaches_drop_handler_before_teardown():
    """Stopping deliberately must not raise a 'stream ended' alert.

    ``removeAttribute('src')`` followed by ``load()`` fires 'error'/'ended' on
    the way out, which would trip the drop handler for a stop the user asked
    for.
    """
    toggle = _toggle_function(_template())
    teardown = toggle[toggle.index("HIDE PLAYER"):]
    assert "removeEventListener('error', audio._easDropHandler)" in teardown
    # Match the calls, not the prose: the comment above the detach block also
    # names removeAttribute('src').
    detach = teardown.index("removeEventListener('error', audio._easDropHandler)")
    reset = teardown.index("audio.removeAttribute('src')")
    assert detach < reset, "the drop handler must be detached before teardown"


# ---------------------------------------------------------------------------
# Server-side pre-flight
# ---------------------------------------------------------------------------

def test_missing_ffmpeg_is_reported_before_streaming_starts():
    """A missing encoder must yield 503, not an empty 200.

    The generator cannot signal failure: by the time it runs, Response() has
    already sent the headers. Previously a missing ffmpeg just ended the
    generator, so the browser received "200 OK" with an empty body, reported a
    generic media error, and the UI blamed the audio source. The check has to
    happen in the request phase, while a status code can still be chosen —
    hence the ordering assertion below.
    """
    service = AUDIO_SERVICE.read_text(encoding="utf-8")

    route = service.index("def stream_eas_decoder(")
    generator = service.index("def generate_eas_decoder_mp3(", route)
    handler_body = service[route:generator]

    assert "which('ffmpeg')" in handler_body, (
        "ffmpeg availability must be checked in the request phase, before the "
        "streaming Response is constructed"
    )
    assert "503" in handler_body
