#!/usr/bin/env python3
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

"""Tests for services/demod -- FM/AM demodulation split out of the audio
service into its own process.

A py-spy --gil profile of the live eas-station-audio.service showed the
Redis-subscriber thread that received IQ samples and called
FMDemodulator.process() inline dominating GIL-held time (scipy.signal
oaconvolve FFT convolutions for stereo pilot/RDS extraction), starving the
three real-time Icecast feeder threads sharing the same process. This
moves that work to services/demod/, mirroring the queue+dedicated-thread
decoupling app_core/radio/demod/rbds_worker.py already uses. These tests
cover the new worker in isolation -- no live Redis, no live SDR hardware.
"""

import base64
import os
import sys
import unittest
import zlib
from unittest.mock import MagicMock

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _encode_iq_message(iq_samples: np.ndarray, sample_rate: int, center_frequency: int) -> dict:
    """Build a dict shaped like a decoded sdr:samples:<id> pub/sub message."""
    interleaved = np.empty(len(iq_samples) * 2, dtype=np.float32)
    interleaved[0::2] = iq_samples.real
    interleaved[1::2] = iq_samples.imag
    compressed = zlib.compress(interleaved.tobytes(), level=1)
    encoded = base64.b64encode(compressed).decode("ascii")
    return {
        "receiver_id": "test-rx",
        "sample_rate": sample_rate,
        "center_frequency": center_frequency,
        "samples": encoded,
    }


class _FakeReceiverConfig:
    """Minimal stand-in for app_core.radio.manager.ReceiverConfig."""

    def __init__(self, **kwargs):
        self.modulation_type = kwargs.get("modulation_type", "FM")
        self.stereo_enabled = kwargs.get("stereo_enabled", True)
        self.deemphasis_us = kwargs.get("deemphasis_us", 75.0)
        self.enable_rbds = kwargs.get("enable_rbds", False)
        self.audio_sample_rate = kwargs.get("audio_sample_rate", 48000)


class TestAudioEnvelope(unittest.TestCase):
    """Wire-format round-trip for the demod->audio-service audio channel."""

    def test_round_trip(self):
        from services.demod.worker import _pack_audio_envelope, unpack_audio_envelope

        audio = np.random.randn(1000).astype(np.float32)
        packed = _pack_audio_envelope(audio.tobytes(), 250000, 93900000)

        iq_rate, freq, decoded = unpack_audio_envelope(packed)

        self.assertEqual(iq_rate, 250000)
        self.assertEqual(freq, 93900000)
        np.testing.assert_array_almost_equal(audio, decoded)

    def test_round_trip_via_local_adapter_unpacker(self):
        """The audio-service side deliberately duplicates the unpack function
        (app_core must not import from services.*) -- verify both copies
        agree on the wire format."""
        from app_core.audio.redis_sdr_adapter import _unpack_audio_envelope
        from services.demod.worker import _pack_audio_envelope

        audio = np.random.randn(500).astype(np.float32)
        packed = _pack_audio_envelope(audio.tobytes(), 2500000, 162550000)

        iq_rate, freq, decoded = _unpack_audio_envelope(packed)

        self.assertEqual(iq_rate, 2500000)
        self.assertEqual(freq, 162550000)
        np.testing.assert_array_almost_equal(audio, decoded)

    def test_frequency_clamped_to_uint32(self):
        from services.demod.worker import _pack_audio_envelope, unpack_audio_envelope

        packed = _pack_audio_envelope(b"", 100, -5)
        _rate, freq, _audio = unpack_audio_envelope(packed)
        self.assertEqual(freq, 0)


class TestDemodWorker(unittest.TestCase):
    """DemodWorker: queue-fed, single-consumer-thread demod + republish."""

    def setUp(self):
        self.redis_client = MagicMock()
        self.receiver_config = _FakeReceiverConfig(
            modulation_type="FM", stereo_enabled=False, enable_rbds=False,
        )

    def tearDown(self):
        for worker in getattr(self, "_workers", []):
            worker.stop()

    def _make_worker(self, receiver_id="test-rx"):
        from services.demod.worker import DemodWorker

        worker = DemodWorker(receiver_id, self.redis_client, self.receiver_config)
        self._workers = getattr(self, "_workers", [])
        self._workers.append(worker)
        return worker

    def test_submit_and_publish_round_trip(self):
        """Feeding one IQ chunk through the worker should demodulate it and
        publish exactly one audio message + one status key, without
        touching the caller's (subscriber) thread."""
        worker = self._make_worker()

        # A real (weak) FM-ish signal: constant-frequency complex exponential
        # is enough to exercise the demod path without asserting on the
        # audio content itself -- that's FMDemodulator's own test coverage
        # (tests/test_fm_stereo_decoder.py), not this worker's job.
        sample_rate = 250000
        num_samples = int(sample_rate * 0.02)  # 20ms chunk
        t = np.arange(num_samples) / sample_rate
        iq = np.exp(2j * np.pi * 1000 * t).astype(np.complex64)
        message = _encode_iq_message(iq, sample_rate, 93900000)

        worker.submit_message(message)

        # Wait for the worker thread to drain the queue (bounded poll,
        # no fixed sleep -- worker loop pulls with a 0.5s queue timeout).
        import time
        deadline = time.monotonic() + 3.0
        while worker.get_stats()["chunks_processed"] == 0 and time.monotonic() < deadline:
            time.sleep(0.01)

        stats = worker.get_stats()
        self.assertEqual(stats["chunks_processed"], 1)
        self.assertEqual(stats["chunks_dropped"], 0)
        self.assertTrue(stats["demodulator_active"])

        # publish() was called at least once for audio (channel) and,
        # since FMDemodulator always returns a status object, once for
        # the status key too.
        self.assertTrue(self.redis_client.publish.called)
        publish_channel = self.redis_client.publish.call_args[0][0]
        self.assertEqual(publish_channel, "demod:audio:test-rx")

        self.assertTrue(self.redis_client.setex.called)
        status_key = self.redis_client.setex.call_args[0][0]
        self.assertEqual(status_key, "demod:status:test-rx")

    def test_drops_on_backpressure_without_blocking(self):
        """submit_message() must never block the caller -- verify it
        returns immediately and increments a drop counter once the bounded
        queue is full (mirrors RBDSWorker.submit_samples's contract)."""
        from services.demod import worker as worker_module

        worker = self._make_worker()
        # Stop the worker thread so nothing drains the queue -- isolates
        # backpressure behavior from processing speed.
        worker._stop_event.set()
        worker._thread.join(timeout=2.0)

        message = _encode_iq_message(
            np.zeros(10, dtype=np.complex64), 250000, 93900000
        )
        for _ in range(worker_module._QUEUE_MAXSIZE + 10):
            worker.submit_message(message)

        self.assertEqual(worker.get_stats()["chunks_dropped"], 10)

    def test_stop_is_idempotent_and_releases_demodulator(self):
        worker = self._make_worker()
        worker.stop()
        self.assertIsNone(worker._demodulator)
        # Calling stop() again must not raise.
        worker.stop()

    def test_update_config_swaps_reference_without_rebuild(self):
        worker = self._make_worker()
        new_config = _FakeReceiverConfig(modulation_type="FM", enable_rbds=True)
        worker.update_config(new_config)
        self.assertIs(worker.receiver_config, new_config)


if __name__ == "__main__":
    unittest.main()
