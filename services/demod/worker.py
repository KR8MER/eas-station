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

"""Per-receiver FM/AM demodulation worker.

Moved out of ``app_core/audio/redis_sdr_adapter.py`` (the audio service),
where it ran synchronously inline inside the Redis subscriber thread that
receives IQ samples from ``eas-station-sdr.service``. Profiling that thread
with ``py-spy record --gil`` showed it dominating GIL-held samples: every
incoming IQ chunk triggered several ``scipy.signal.oaconvolve`` FFT
convolutions (stereo pilot detection, L+R/L-R extraction --
``app_core/radio/demod/fm.py``), which starved the audio service's three
real-time Icecast feeder threads sharing the same interpreter (each needs
to wake roughly every 50ms to keep its buffer fed).

This worker runs in ``eas-station-demod.service`` -- its own OS process --
so that DSP work can never again share a GIL with anything real-time. One
``DemodWorker`` instance owns exactly one demodulator (``FMDemodulator`` /
``AMDemodulator``, both stateful/order-dependent, order-dependent across
consecutive IQ chunks and safe for exactly one sequential consumer -- never
call ``.process()`` from more than one thread or on out-of-order chunks).
Mirrors ``app_core/radio/demod/rbds_worker.py``'s queue+single-consumer-
thread shape: a bounded queue decouples the network-receive path (which
must stay fast so it can't itself become a new GIL hog) from the actual
demod call, dropping the newest message on backpressure rather than
blocking the receiver.
"""

import base64
import logging
import pickle
import queue
import threading
import time
import zlib
from typing import Any, Optional

import numpy as np

logger = logging.getLogger(__name__)

#: Mirrors RBDSWorker's queue sizing rationale (rbds_worker.py) -- large
#: enough to absorb scheduler contention on a small SBC without blocking
#: the receive thread, small enough that a stuck demodulator doesn't pile
#: up unbounded memory. IQ chunks arrive roughly every 32ms
#: (SDR_SAMPLE_CHUNK_DURATION_SEC in sdr_hardware_service.py), so 64 slots
#: is ~2s of buffering.
_QUEUE_MAXSIZE = 64


class DemodWorker:
    """Owns one demodulator instance and its dedicated worker thread.

    Construct one per receiver. ``submit_message(data)`` is the only
    method the (separate, lightweight) Redis-subscriber thread calls --
    everything else runs on this worker's own thread.
    """

    def __init__(self, receiver_id: str, redis_client, receiver_config) -> None:
        self.receiver_id = receiver_id
        self._redis_client = redis_client
        # ReceiverConfig snapshot (modulation_type, stereo_enabled,
        # deemphasis_us, enable_rbds, audio_sample_rate, ...) -- see
        # app_core/radio/manager.ReceiverConfig, built by
        # RadioReceiver.to_receiver_config(). Refreshed by the caller
        # (services/demod/__main__.py's reconcile loop) on config change;
        # this worker just reads whatever was last handed to it.
        self.receiver_config = receiver_config

        self._demodulator: Optional[Any] = None
        self._iq_sample_rate: int = 0
        self._center_frequency: int = 0
        self._last_rbds_reset_frequency: Optional[int] = None

        self._queue: "queue.Queue[dict]" = queue.Queue(maxsize=_QUEUE_MAXSIZE)
        self._chunks_dropped = 0
        self._chunks_processed = 0
        self._last_processed_at: float = 0.0

        self._stop_event = threading.Event()
        self._thread = threading.Thread(
            target=self._worker_loop,
            name=f"demod-{receiver_id}",
            daemon=True,
        )
        self._thread.start()

    # -- public API, called from the subscriber thread -------------------

    def submit_message(self, data: dict) -> None:
        """Hand a parsed ``sdr:samples:<id>`` message to the worker.

        Never blocks -- drops the newest message and counts it if the
        worker is falling behind, same policy as
        ``RBDSWorker.submit_samples``.
        """
        try:
            self._queue.put_nowait(data)
        except queue.Full:
            self._chunks_dropped += 1

    def update_config(self, receiver_config) -> None:
        """Swap in a new ReceiverConfig snapshot (picked up on next chunk).

        Does not force a demodulator rebuild by itself -- the worker loop
        rebuilds when it next notices ``receiver_config`` differs in a way
        that matters (modulation/stereo/RBDS/deemphasis), mirroring how
        the old adapter only recreated on a meaningful sample-rate drift
        rather than on every message.
        """
        self.receiver_config = receiver_config

    def stop(self) -> None:
        self._stop_event.set()
        self._thread.join(timeout=2.0)
        if self._demodulator is not None and hasattr(self._demodulator, "stop"):
            try:
                self._demodulator.stop()
            except Exception as exc:  # pragma: no cover - defensive
                logger.debug("demod worker %s: stop() failed: %s", self.receiver_id, exc)
        self._demodulator = None

    def get_stats(self) -> dict:
        return {
            "chunks_processed": self._chunks_processed,
            "chunks_dropped": self._chunks_dropped,
            "queue_depth": self._queue.qsize(),
            "last_processed_age_s": (
                time.time() - self._last_processed_at if self._last_processed_at else None
            ),
            "demodulator_active": self._demodulator is not None,
        }

    # -- worker thread -----------------------------------------------------

    def _worker_loop(self) -> None:
        logger.info("demod worker started for %s", self.receiver_id)
        while not self._stop_event.is_set():
            try:
                data = self._queue.get(timeout=0.5)
            except queue.Empty:
                continue
            try:
                self._process_message(data)
                self._chunks_processed += 1
                self._last_processed_at = time.time()
            except Exception as exc:
                logger.warning(
                    "demod worker %s: failed to process chunk: %s",
                    self.receiver_id, exc, exc_info=True,
                )
        logger.info(
            "demod worker exited for %s (processed=%d dropped=%d)",
            self.receiver_id, self._chunks_processed, self._chunks_dropped,
        )

    def _process_message(self, data: dict) -> None:
        # -- sample-rate / frequency bookkeeping (moved verbatim from the
        #    old RedisSDRSourceAdapter._redis_subscriber_loop) ------------
        new_sample_rate = data.get("sample_rate", self._iq_sample_rate)
        prev_center_frequency = self._center_frequency
        self._center_frequency = data.get("center_frequency", self._center_frequency)

        if (
            self._center_frequency
            and self._center_frequency != self._last_rbds_reset_frequency
        ):
            if prev_center_frequency and prev_center_frequency != self._center_frequency:
                logger.info(
                    "Frequency change detected for %s: %d Hz -> %d Hz; resetting RBDS state",
                    self.receiver_id, prev_center_frequency, self._center_frequency,
                )
            if self._demodulator is not None and hasattr(self._demodulator, "reset_rbds"):
                try:
                    self._demodulator.reset_rbds()
                except Exception as exc:  # pragma: no cover - defensive
                    logger.debug("reset_rbds failed: %s", exc)
            self._last_rbds_reset_frequency = self._center_frequency

        if self._demodulator is None:
            self._iq_sample_rate = new_sample_rate
            self._create_demodulator()
        elif new_sample_rate != self._iq_sample_rate:
            rate_diff_pct = abs(new_sample_rate - self._iq_sample_rate) / self._iq_sample_rate * 100.0
            if rate_diff_pct > 0.1:
                logger.warning(
                    "IQ sample rate changed for %s: %dHz -> %dHz (%.3f%%); recreating demodulator",
                    self.receiver_id, self._iq_sample_rate, new_sample_rate, rate_diff_pct,
                )
                self._iq_sample_rate = new_sample_rate
                self._create_demodulator()

        encoded_samples = data.get("samples", "")
        if not encoded_samples:
            return

        compressed = base64.b64decode(encoded_samples)
        interleaved_bytes = zlib.decompress(compressed)
        interleaved = np.frombuffer(interleaved_bytes, dtype=np.float32)
        iq_samples = interleaved[0::2] + 1j * interleaved[1::2]

        if self._demodulator is None:
            # IQ-passthrough receivers (modulation_type == 'IQ') have no
            # demodulator by design -- create_demodulator() returns None.
            # Nothing for this service to publish for them.
            return

        audio_samples, status = self._demodulator.demodulate(iq_samples)
        if audio_samples is None or len(audio_samples) == 0:
            return

        self._publish(audio_samples, status)

    def _create_demodulator(self) -> None:
        if self._demodulator is not None and hasattr(self._demodulator, "stop"):
            try:
                self._demodulator.stop()
            except Exception as exc:  # pragma: no cover - defensive
                logger.debug("stop() before recreate failed: %s", exc)
        self._demodulator = None

        cfg = self.receiver_config
        modulation_type = (getattr(cfg, "modulation_type", None) or "FM").upper()

        from app_core.radio.demod.factory import create_demodulator
        from app_core.radio.demod.types import DemodulatorConfig

        demod_config = DemodulatorConfig(
            modulation_type=modulation_type,
            sample_rate=self._iq_sample_rate,
            audio_sample_rate=int(getattr(cfg, "audio_sample_rate", None) or 44100),
            stereo_enabled=bool(getattr(cfg, "stereo_enabled", True)),
            deemphasis_us=float(getattr(cfg, "deemphasis_us", 75.0) or 75.0),
            enable_rbds=bool(getattr(cfg, "enable_rbds", False)),
        )
        self._demodulator = create_demodulator(demod_config)
        logger.info(
            "demod worker %s: created %s demodulator (%dHz IQ -> %dHz audio, stereo=%s, rbds=%s)",
            self.receiver_id, modulation_type, self._iq_sample_rate,
            demod_config.audio_sample_rate, demod_config.stereo_enabled, demod_config.enable_rbds,
        )

    def _publish(self, audio_samples: np.ndarray, status: Any) -> None:
        from app_core.config.redis_config import RedisChannels

        if self._redis_client is None:
            return

        audio_bytes = audio_samples.astype(np.float32).tobytes()
        channel = f"{RedisChannels.DEMOD_AUDIO_PREFIX}{self.receiver_id}"
        try:
            envelope = _pack_audio_envelope(audio_bytes, self._iq_sample_rate, self._center_frequency)
            # base64-encoded, not raw bytes: the shared Redis client (see
            # app_core/redis_client.get_redis_client) is constructed with
            # decode_responses=True everywhere else in this codebase, and
            # redis-py applies that UTF-8 decode to every pub/sub payload
            # it reads off the socket -- including this one -- before our
            # code ever sees it. A raw (non-UTF-8) binary payload crashed
            # the subscriber's read loop outright
            # (UnicodeDecodeError: 'utf-8' codec can't decode byte ...),
            # confirmed live when this was first deployed. base64 keeps
            # the payload valid UTF-8/ASCII without needing a second,
            # separately-configured Redis connection just for this channel.
            self._redis_client.publish(channel, base64.b64encode(envelope).decode('ascii'))
        except Exception as exc:
            logger.debug("demod worker %s: audio publish failed: %s", self.receiver_id, exc)

        if status is not None:
            try:
                status_key = f"{RedisChannels.DEMOD_STATUS_PREFIX}{self.receiver_id}"
                # base64 for the same reason as the audio envelope above --
                # GET/SETEX go through the same decode_responses=True UTF-8
                # decode as pub/sub, and a pickle stream is not valid UTF-8.
                encoded = base64.b64encode(pickle.dumps(status)).decode('ascii')
                self._redis_client.setex(
                    status_key,
                    RedisChannels.DEMOD_STATUS_TTL_SECONDS,
                    encoded,
                )
            except Exception as exc:
                logger.debug("demod worker %s: status publish failed: %s", self.receiver_id, exc)


def _pack_audio_envelope(audio_bytes: bytes, iq_sample_rate: int, center_frequency: int) -> bytes:
    """Build the wire format for a ``demod:audio:<id>`` pub/sub message.

    Same-process-trusted, low-latency: fixed 4-byte big-endian
    IQ-sample-rate and center-frequency headers (the two fields the audio
    service's metrics still need, per its ``_update_metrics()``) followed
    by raw float32 PCM audio bytes -- already at the receiver's configured
    audio_sample_rate by construction (the demodulator was built with
    that as its target rate), so it doesn't need to ride along too. No
    JSON/base64/zlib -- those exist on the SDR->demod hop because that's
    raw IQ crossing a hop that benefits from compression; demodulated
    audio is already far smaller and this now sits on the hot path a
    real-time feeder thread reads from, so keep it to one unpack call.
    Both header fields are clamped to fit an unsigned 4-byte field
    (~4.29 GHz / 4.29 GHz ceiling), well above any realistic broadcast/ham
    SDR IQ rate or tuning frequency.
    """
    rate = max(0, min(int(iq_sample_rate), 0xFFFFFFFF))
    freq = max(0, min(int(center_frequency), 0xFFFFFFFF))
    return (
        rate.to_bytes(4, "big", signed=False)
        + freq.to_bytes(4, "big", signed=False)
        + audio_bytes
    )


def unpack_audio_envelope(payload: bytes) -> "tuple[int, int, np.ndarray]":
    """Inverse of :func:`_pack_audio_envelope`. Used by the audio service.

    Returns ``(iq_sample_rate, center_frequency, audio_samples)``.
    """
    iq_sample_rate = int.from_bytes(payload[:4], "big", signed=False)
    center_frequency = int.from_bytes(payload[4:8], "big", signed=False)
    audio = np.frombuffer(payload[8:], dtype=np.float32)
    return iq_sample_rate, center_frequency, audio
