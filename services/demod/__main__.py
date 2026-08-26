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

from __future__ import annotations

"""Demod subsystem subprocess entry point.

Owns FM/AM demodulation for every SDR receiver with ``audio_output``
enabled, moved out of the audio service (see ``services/demod/worker.py``
for why -- a py-spy profile of eas-station-audio.service showed this DSP
work dominating GIL-held time in a thread that also had to share a GIL
with three real-time Icecast feeder threads). Subscribes to
``sdr:samples:<receiver_id>`` (published by eas-station-sdr.service),
publishes demodulated audio to ``demod:audio:<receiver_id>`` and decoder
status (stereo lock, RBDS data, ...) to ``demod:status:<receiver_id>``.
eas-station-audio.service's ``RedisSDRSourceAdapter`` is the consumer on
the other end (app_core/audio/redis_sdr_adapter.py).

No HTTP control API beyond ``/health`` -- like the ``gpio`` subsystem,
this is purely Redis-driven; the Flask app exists only so systemd / the
web UI can verify "is the demod subprocess up?" at a known port.

Listens on port 5106 (next free port after the 5101-5105 hardware.target
bundle -- this service is a peer of ``sdr``/``audio`` in the dataflow,
not a hardware.target member, so it isn't in that port range's bundle).
"""

import logging
import threading
import time
from datetime import datetime, timezone
from typing import Dict, Optional

from flask import Flask, jsonify

from app_utils.system.sd_notify import notify as sd_notify, Watchdog
from services.common import (
    configure_logging,
    get_redis,
    init_database,
    init_runtime,
    install_signal_handlers,
    load_environment,
)
from services.demod.worker import DemodWorker

PORT = 5106
SUBSYSTEM = "demod"
HEARTBEAT_INTERVAL_S = 5
#: How often to re-query RadioReceiver for added/removed/reconfigured
#: receivers. Not event-driven (unlike GPIO's command channel) because
#: receiver CRUD is rare admin activity, not a real-time control path --
#: a short poll is simpler than inventing a new notification channel for
#: something that changes on the order of "once in a while".
RECONCILE_INTERVAL_S = 30

_running = True
_workers: Dict[str, DemodWorker] = {}
_subscriber_threads: Dict[str, threading.Thread] = {}
_subscriber_stop_events: Dict[str, threading.Event] = {}
_workers_lock = threading.Lock()


def _on_shutdown_signal(signum: int) -> None:
    global _running
    logging.getLogger(__name__).info(
        f"[{SUBSYSTEM}] received signal {signum}, initiating graceful shutdown..."
    )
    _running = False


def _build_app() -> Flask:
    app = Flask(__name__)

    @app.route("/health", methods=["GET"])
    def health():
        with _workers_lock:
            receivers = {
                rid: worker.get_stats() for rid, worker in _workers.items()
            }
        return jsonify({
            "status": "ok",
            "service": f"eas-station-{SUBSYSTEM}",
            "port": PORT,
            "receivers": receivers,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

    return app


def _run_api_server(app: Flask) -> None:
    log = logging.getLogger(__name__)
    try:
        app.run(host="0.0.0.0", port=PORT, debug=False, use_reloader=False)
    except Exception as e:
        log.error(f"[{SUBSYSTEM}] API server crashed: {e}", exc_info=True)


def _discover_receiver_configs(flask_app) -> Dict[str, object]:
    """Query enabled, audio-output SDR receivers and their demod config.

    Returns ``{receiver_id: ReceiverConfig}``. Mirrors what
    ``eas-station-sdr.service`` itself reads to know what to tune hardware
    to -- ``RadioReceiver`` is the single source of truth for both.
    """
    log = logging.getLogger(__name__)
    try:
        from app_core.models import RadioReceiver

        with flask_app.app_context():
            rows = RadioReceiver.query.filter_by(enabled=True, audio_output=True).all()
            return {row.identifier: row.to_receiver_config() for row in rows}
    except Exception as exc:
        log.warning(f"[{SUBSYSTEM}] receiver discovery failed: {exc}")
        return {}


def _run_subscriber_loop(receiver_id: str, stop_event: threading.Event) -> None:
    """Lightweight per-receiver Redis subscriber: parse JSON, hand off, repeat.

    Deliberately does nothing else -- no demod call here. That's the
    entire point of this service: keep the network-receive path thin so
    it can never itself become a GIL hog, exactly the split
    ``RBDSWorker``/``rbds_worker.submit_samples`` already uses. The
    ``DemodWorker`` (a separate thread, one per receiver) does the actual
    demodulation.
    """
    log = logging.getLogger(__name__)
    import json as _json

    from app_core.config.redis_config import RedisChannels

    channel = f"{RedisChannels.SDR_SAMPLES_PREFIX}{receiver_id}"
    backoff = 1.0
    while not stop_event.is_set() and _running:
        pubsub = None
        try:
            client = get_redis()
            pubsub = client.pubsub(ignore_subscribe_messages=True)
            pubsub.subscribe(channel)
            log.info(f"[{SUBSYSTEM}] subscribed to '{channel}'")
            backoff = 1.0
            while not stop_event.is_set() and _running:
                message = pubsub.get_message(timeout=1.0)
                if message is None or message.get("type") != "message":
                    continue
                try:
                    data = _json.loads(message["data"])
                except (ValueError, TypeError) as exc:
                    log.debug(f"[{SUBSYSTEM}] ignoring malformed message on {channel}: {exc}")
                    continue
                with _workers_lock:
                    worker = _workers.get(receiver_id)
                if worker is not None:
                    worker.submit_message(data)
        except Exception as exc:
            if not stop_event.is_set() and _running:
                log.warning(
                    f"[{SUBSYSTEM}] subscriber for {receiver_id} disconnected ({exc}); "
                    f"retrying in {backoff:.0f}s"
                )
                time.sleep(backoff)
                backoff = min(backoff * 2, 30.0)
        finally:
            if pubsub is not None:
                try:
                    pubsub.close()
                except Exception:
                    pass
    log.info(f"[{SUBSYSTEM}] subscriber loop exited for {receiver_id}")


def _reconcile_receivers(flask_app, redis_client) -> None:
    """Start workers for new/enabled receivers, stop them for removed/disabled ones.

    Updates existing workers' config in place on a demod-relevant change
    (modulation, stereo, RBDS, de-emphasis, audio rate) so a settings
    change takes effect on the worker's next chunk without a full
    service restart.
    """
    log = logging.getLogger(__name__)
    current = _discover_receiver_configs(flask_app)

    with _workers_lock:
        # Stop workers for receivers that disappeared or were disabled.
        for receiver_id in list(_workers.keys()):
            if receiver_id not in current:
                log.info(f"[{SUBSYSTEM}] stopping worker for removed/disabled receiver {receiver_id}")
                _subscriber_stop_events[receiver_id].set()
                _subscriber_threads[receiver_id].join(timeout=2.0)
                _workers[receiver_id].stop()
                del _workers[receiver_id]
                del _subscriber_threads[receiver_id]
                del _subscriber_stop_events[receiver_id]

        # Start workers for newly-discovered receivers; refresh config for
        # existing ones (cheap -- update_config() just swaps a reference).
        for receiver_id, receiver_config in current.items():
            if receiver_id in _workers:
                _workers[receiver_id].update_config(receiver_config)
                continue
            log.info(f"[{SUBSYSTEM}] starting worker for receiver {receiver_id}")
            _workers[receiver_id] = DemodWorker(receiver_id, redis_client, receiver_config)
            stop_event = threading.Event()
            _subscriber_stop_events[receiver_id] = stop_event
            thread = threading.Thread(
                target=_run_subscriber_loop,
                args=(receiver_id, stop_event),
                name=f"demod-subscriber-{receiver_id}",
                daemon=True,
            )
            _subscriber_threads[receiver_id] = thread
            thread.start()


def _publish_metrics(redis_client) -> None:
    import json as _json

    from app_core.config.redis_config import RedisChannels

    if not redis_client:
        return
    with _workers_lock:
        receivers = {rid: worker.get_stats() for rid, worker in _workers.items()}
    payload = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "receiver_count": len(receivers),
        "receivers": receivers,
    }
    try:
        redis_client.setex(RedisChannels.DEMOD_METRICS_KEY, 60, _json.dumps(payload))
    except Exception as exc:
        logging.getLogger(__name__).debug(f"[{SUBSYSTEM}] metrics publish failed: {exc}")


def main() -> None:
    configure_logging()
    logger = logging.getLogger(__name__)
    load_environment(logger)

    logger.info("=" * 60)
    logger.info(f"🎚️  EAS Station - Demod Subsystem (port {PORT})")
    logger.info("=" * 60)

    init_runtime(SUBSYSTEM)
    install_signal_handlers(_on_shutdown_signal)

    redis_client = None
    try:
        logger.info("Connecting to Redis...")
        redis_client = get_redis()
        logger.info("✅ Connected to Redis")

        logger.info("Initializing database connection...")
        flask_app, _db = init_database()
        logger.info("✅ Database connected")

        api_app = _build_app()
        logger.info(f"Starting demod health server on port {PORT}...")
        api_thread = threading.Thread(
            target=_run_api_server, args=(api_app,), daemon=True, name="demod-api"
        )
        api_thread.start()
        logger.info("✅ Demod health server started")

        _reconcile_receivers(flask_app, redis_client)
        logger.info(f"✅ Started {len(_workers)} demod worker(s)")

        # Type=notify: tell systemd we're up, then keep kicking the
        # watchdog from the main loop so a deadlocked reconcile/publish
        # path gets this unit killed and restarted rather than hanging
        # forever (see systemd/eas-station-demod.service's WatchdogSec).
        sd_notify("READY=1")
        watchdog = Watchdog()

        last_heartbeat = 0.0
        last_reconcile = time.monotonic()

        while _running:
            now_mono = time.monotonic()
            if now_mono - last_reconcile >= RECONCILE_INTERVAL_S:
                try:
                    _reconcile_receivers(flask_app, redis_client)
                except Exception as exc:
                    logger.error(f"[{SUBSYSTEM}] reconcile failed: {exc}", exc_info=True)
                last_reconcile = now_mono

            now = time.time()
            if now - last_heartbeat >= HEARTBEAT_INTERVAL_S:
                _publish_metrics(redis_client)
                last_heartbeat = now

            watchdog.kick()
            time.sleep(1)

    except KeyboardInterrupt:
        logger.info(f"[{SUBSYSTEM}] received interrupt signal")
    except Exception as e:
        logger.error(f"[{SUBSYSTEM}] fatal error: {e}", exc_info=True)
        import sys
        sys.exit(1)
    finally:
        logger.info(f"[{SUBSYSTEM}] shutting down...")
        with _workers_lock:
            for receiver_id, stop_event in _subscriber_stop_events.items():
                stop_event.set()
            for receiver_id, thread in _subscriber_threads.items():
                thread.join(timeout=2.0)
            for worker in _workers.values():
                worker.stop()
        if redis_client is not None:
            try:
                redis_client.close()
            except Exception:
                pass
        logger.info(f"[{SUBSYSTEM}] ✅ stopped cleanly")


if __name__ == "__main__":
    main()
