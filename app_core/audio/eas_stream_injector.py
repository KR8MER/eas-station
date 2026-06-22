from __future__ import annotations
"""
EAS Station - Emergency Alert System
Copyright (c) 2025-2026 EAS Station, LLC (KR8MER)

This file is part of EAS Station.

EAS Station is dual-licensed under AGPL-3.0 and a Commercial License.
See LICENSE and LICENSE-COMMERCIAL for details.

Repository: https://github.com/KR8MER/eas-station

EAS Stream Injector

Publishes generated EAS alert audio directly into the active source
BroadcastQueue(s) so that every subscribed IcecastStreamer streams
the full SAME sequence (headers → attention tone → narration → EOM)
to listeners on the Icecast server.

Usage
-----
At app startup (after AudioIngestController is created)::

    from app_core.audio import eas_stream_injector
    eas_stream_injector.set_controller(controller)

When an EAS broadcast is generated::

    from app_core.audio.eas_stream_injector import inject_eas_audio
    inject_eas_audio(wav_bytes)

The injector converts WAV bytes to float32 PCM, resamples to each
source's native rate, and publishes in 50 ms chunks to the source's
BroadcastQueue.  IcecastStreamer reads those chunks and sends them on
to the Icecast server without any additional wiring.
"""

import io
import logging
import threading
import wave
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)

# Thread-safe lock for controller registration.
_lock = threading.Lock()
_controller = None  # AudioIngestController (set at startup)


def set_controller(controller) -> None:
    """Register the global AudioIngestController.

    Called once during app startup after the controller is initialised.
    """
    global _controller
    with _lock:
        _controller = controller
    logger.info("EAS stream injector: controller registered (%s)", type(controller).__name__)


def inject_eas_audio(wav_bytes: Optional[bytes]) -> bool:
    """Inject EAS alert audio into every active source BroadcastQueue.

    Converts *wav_bytes* (a complete WAV file) to float32 PCM, resamples
    to each source's native sample rate, then publishes 50 ms chunks to
    ``adapter._source_broadcast`` so the IcecastStreamer streams them.

    Parameters
    ----------
    wav_bytes:
        Raw WAV audio produced by EASBroadcaster (SAME headers + attention
        tone + narration + EOM). May be *None*; returns *False* in that case.

    Returns
    -------
    bool
        *True* if at least one source queue received audio.
    """
    if not wav_bytes:
        return False

    with _lock:
        controller = _controller

    if controller is None:
        logger.debug("EAS stream injector: no controller registered — skipping injection")
        return False

    # Decode WAV once; resample per-source as needed.
    try:
        src_samples, src_rate = _decode_wav(wav_bytes)
    except Exception as exc:
        logger.error("EAS stream injector: failed to decode WAV: %s", exc)
        return False

    if src_samples is None or len(src_samples) == 0:
        logger.warning("EAS stream injector: decoded WAV is empty")
        return False

    # Gather all source adapters from the controller.
    try:
        with controller._lock:
            adapters = dict(controller._sources)
    except Exception as exc:
        logger.error("EAS stream injector: could not read sources from controller: %s", exc)
        return False

    if not adapters:
        logger.warning(
            "EAS stream injector: no sources registered in controller — skipping injection"
        )
        return False

    injected_any = False
    for source_name, adapter in adapters.items():
        try:
            broadcast_queue = adapter._source_broadcast
        except AttributeError:
            logger.debug("EAS stream injector: adapter %s has no _source_broadcast", source_name)
            continue

        config = getattr(adapter, 'config', None)
        target_rate: int = getattr(config, 'sample_rate', 44100) if config else 44100
        target_rate = target_rate or 44100

        # Resample from WAV rate to the source's native broadcast rate.
        if src_rate != target_rate:
            try:
                resampled = _resample(src_samples, src_rate, target_rate)
            except Exception as exc:
                logger.warning(
                    "EAS stream injector: resampling failed for source %s (%d→%d Hz): %s",
                    source_name, src_rate, target_rate, exc,
                )
                continue
        else:
            resampled = src_samples

        # Increment the injection sequence counter BEFORE setting the gate so
        # IcecastStreamer sees the new value on its very next loop iteration and
        # can clear its local pre-buffer, eliminating the ~7.5 s buffering delay.
        inject_seq = getattr(adapter, '_eas_inject_seq', None)
        if inject_seq is not None:
            adapter._eas_inject_seq += 1

        # Gate live source audio so it does not interleave with EAS chunks.
        # The capture loop checks this flag and skips publishing to
        # _source_broadcast while it is set, ensuring listeners hear a clean
        # uninterrupted EAS alert sequence rather than a mix of EAS and live
        # program audio.
        gate = getattr(adapter, '_eas_injection_active', None)
        if gate is not None:
            gate.set()

        # Flush stale live-audio chunks from every subscriber's queue so that
        # EAS chunks are not delayed behind pre-buffered live audio.
        try:
            import queue as _queue_mod
            with broadcast_queue._lock:
                sub_queues = list(broadcast_queue._subscribers.values())
            for sq in sub_queues:
                while True:
                    try:
                        sq.get_nowait()
                    except _queue_mod.Empty:
                        break
        except Exception:
            pass

        try:
            # Publish in 50 ms chunks — same granularity used by the capture loop.
            chunk_size = max(1, int(target_rate * 0.05))
            published = 0
            for offset in range(0, len(resampled), chunk_size):
                chunk = resampled[offset: offset + chunk_size]
                if len(chunk) > 0:
                    broadcast_queue.publish(chunk)
                    published += 1
        finally:
            # Always release the gate, even if publishing raised an exception.
            if gate is not None:
                gate.clear()

        duration_s = len(resampled) / target_rate
        logger.info(
            "EAS stream injector: pushed %.1f s of EAS audio (%d chunks, %d Hz) "
            "to source '%s' broadcast queue",
            duration_s, published, target_rate, source_name,
        )
        injected_any = True

    return injected_any


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _decode_wav(wav_bytes: bytes):
    """Decode a WAV file into a float32 numpy array.

    Returns
    -------
    tuple[np.ndarray, int]
        ``(samples_float32, sample_rate)`` where *samples* is a 1-D array
        normalised to [-1.0, 1.0].
    """
    with wave.open(io.BytesIO(wav_bytes)) as wf:
        n_channels = wf.getnchannels()
        sample_width = wf.getsampwidth()
        sample_rate = wf.getframerate()
        n_frames = wf.getnframes()
        raw = wf.readframes(n_frames)

    if sample_width == 2:
        pcm = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    elif sample_width == 4:
        pcm = np.frombuffer(raw, dtype=np.int32).astype(np.float32) / 2147483648.0
    elif sample_width == 1:
        # WAV 8-bit is unsigned; centre around zero
        pcm = (np.frombuffer(raw, dtype=np.uint8).astype(np.float32) - 128.0) / 128.0
    else:
        raise ValueError(f"Unsupported WAV sample width: {sample_width}")

    # Convert multi-channel to mono by averaging channels.
    if n_channels > 1:
        pcm = pcm.reshape(-1, n_channels).mean(axis=1)

    return pcm, sample_rate


def _resample(samples: np.ndarray, src_rate: int, dst_rate: int) -> np.ndarray:
    """Linear resample *samples* from *src_rate* to *dst_rate*.

    Uses numpy-only linear interpolation — no scipy required.
    """
    if src_rate == dst_rate:
        return samples
    src_len = len(samples)
    dst_len = max(1, int(src_len * dst_rate / src_rate))
    src_indices = np.linspace(0, src_len - 1, dst_len)
    return np.interp(src_indices, np.arange(src_len), samples).astype(np.float32)


__all__ = ["set_controller", "inject_eas_audio"]
