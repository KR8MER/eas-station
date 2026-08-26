#!/usr/bin/env python3
"""
Tests for the Redis-backed audio distribution pipeline.

Originally written for a "3-tier separated architecture" experiment
(sdr-service / audio-service / eas-service as three independent processes)
that was reversed three days after it landed -- EAS monitoring was merged
back into audio-service (now eas_monitoring_service.py), and the standalone
eas-service was retired outright as a redundant duplicate decoder. What
remains here tests the parts of that experiment still in active use:

- app_core/audio/redis_sdr_adapter.py: IQ sample publishing (sdr-service ->
  eas_monitoring_service.py)
- the IQ/audio Redis message encoding itself
- FIPS code loading used by the EAS monitor

app_core/audio/redis_audio_publisher.py (audio sample publishing out of
eas_monitoring_service.py, feeding eas-service.py) was removed along with
the rest of that dead code path once eas-service.py itself was retired --
nothing published to its Redis channel had any subscriber left.
"""

import sys
import os
import unittest
from unittest.mock import Mock, MagicMock, patch
import json
import base64
import zlib
import numpy as np

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class _FakeDemodulatorStatus:
    """Picklable stand-in for app_core.radio.demod.types.DemodulatorStatus.

    A MagicMock can't cross a real pickle round-trip (which is exactly
    what _get_remote_status() does against the bytes eas-station-demod.
    service publishes), so these tests need a plain, module-level,
    picklable object instead.
    """

    def __init__(self, stereo_pilot_locked: bool = False):
        self.stereo_pilot_locked = stereo_pilot_locked


class TestRedisSdrAdapter(unittest.TestCase):
    """Test Redis SDR source adapter."""

    def setUp(self):
        """Set up test fixtures."""
        from app_core.audio.ingest import AudioSourceConfig, AudioSourceType

        self.config = AudioSourceConfig(
            source_type=AudioSourceType.STREAM,
            name="test-redis-sdr",
            enabled=True,
            priority=1,
            sample_rate=44100,
            channels=1,
            buffer_size=4096,
            device_params={
                'receiver_id': 'test-receiver',
                'demod_mode': 'FM'
            }
        )

    def test_import(self):
        """Test that RedisSDRSourceAdapter can be imported."""
        try:
            from app_core.audio.redis_sdr_adapter import RedisSDRSourceAdapter
            self.assertIsNotNone(RedisSDRSourceAdapter)
        except ImportError as e:
            self.fail(f"Failed to import RedisSDRSourceAdapter: {e}")

    def test_initialization(self):
        """Test adapter initialization."""
        from app_core.audio.redis_sdr_adapter import RedisSDRSourceAdapter

        # Mock Redis to avoid connection
        with patch('app_core.audio.redis_sdr_adapter.get_redis_client'):
            adapter = RedisSDRSourceAdapter(self.config)
            self.assertEqual(adapter.config.name, "test-redis-sdr")
            self.assertEqual(adapter._receiver_id, "test-receiver")

    def test_iq_sample_decoding(self):
        """Test IQ sample decoding from Redis message.

        This encode/decode pair now runs in services/demod (sdr-service ->
        demod-service hop) rather than in this adapter -- kept here because
        it documents the wire format eas-station-sdr.service actually
        publishes, which services/demod/worker.py's DemodWorker consumes.
        """
        # Create sample IQ data
        iq_samples = np.random.randn(1000) + 1j * np.random.randn(1000)
        iq_samples = iq_samples.astype(np.complex64)

        # Encode as Redis would send it
        interleaved = np.empty(len(iq_samples) * 2, dtype=np.float32)
        interleaved[0::2] = iq_samples.real
        interleaved[1::2] = iq_samples.imag
        compressed = zlib.compress(interleaved.tobytes(), level=1)
        encoded = base64.b64encode(compressed).decode('ascii')

        # Verify we can decode it back
        compressed_back = base64.b64decode(encoded)
        interleaved_bytes = zlib.decompress(compressed_back)
        interleaved_back = np.frombuffer(interleaved_bytes, dtype=np.float32)
        iq_back = interleaved_back[0::2] + 1j * interleaved_back[1::2]

        # Verify data integrity
        np.testing.assert_array_almost_equal(iq_samples, iq_back)

    def _make_adapter(self):
        """Construct a RedisSDRSourceAdapter without going through
        _start_capture() (which would try a real Redis connection) --
        these tests exercise post-startup behavior directly instead."""
        from app_core.audio.redis_sdr_adapter import RedisSDRSourceAdapter

        adapter = RedisSDRSourceAdapter(self.config)
        adapter._receiver_id = 'test-receiver'
        return adapter

    def test_get_remote_status_unpickles_and_caches(self):
        """_get_remote_status() replaces self._demodulator.get_last_status()
        now that the demodulator lives in eas-station-demod.service --
        verify it fetches+unpickles the status key and reuses it within the
        cache TTL instead of round-tripping Redis on every call."""
        import pickle

        adapter = self._make_adapter()

        status_obj = _FakeDemodulatorStatus(stereo_pilot_locked=True)
        mock_redis = MagicMock()
        mock_redis.get.return_value = pickle.dumps(status_obj)
        adapter._redis_client = mock_redis

        first = adapter._get_remote_status()
        second = adapter._get_remote_status()

        # Unpickling produces a new (but equal-by-value) object -- check
        # content, not identity, against the original.
        self.assertTrue(first.stereo_pilot_locked)
        # The cache returns the literal object from the first unpickle.
        self.assertIs(second, first)
        # Cached within _STATUS_CACHE_TTL_S -- only one Redis round-trip.
        self.assertEqual(mock_redis.get.call_count, 1)
        mock_redis.get.assert_called_with('demod:status:test-receiver')

    def test_get_remote_status_keeps_last_known_on_ttl_gap(self):
        """A missing key (TTL lapsed between demod publishes) should not
        flap the UI to blank -- keep showing the last-known status, same
        behavior the old in-process path had while a demodulator was
        between decode cycles."""
        import pickle
        from app_core.audio.redis_sdr_adapter import _STATUS_CACHE_TTL_S

        adapter = self._make_adapter()

        status_obj = _FakeDemodulatorStatus()
        mock_redis = MagicMock()
        mock_redis.get.return_value = pickle.dumps(status_obj)
        adapter._redis_client = mock_redis

        first = adapter._get_remote_status()
        self.assertIsNotNone(first)

        # Force the cache to be stale, then simulate the key expiring.
        adapter._status_cache_at -= (_STATUS_CACHE_TTL_S + 1.0)
        mock_redis.get.return_value = None

        second = adapter._get_remote_status()
        self.assertIs(second, first)  # last-known, not None

    def test_subscriber_loop_unpacks_binary_audio_envelope(self):
        """The subscriber thread no longer parses JSON or calls a
        demodulator -- it unpacks the binary envelope published by
        services/demod/worker.py and enqueues the audio directly."""
        from services.demod.worker import _pack_audio_envelope

        adapter = self._make_adapter()

        audio = np.random.randn(200).astype(np.float32)
        envelope = _pack_audio_envelope(audio.tobytes(), 250000, 93900000)

        # First get_message() call returns the one envelope; the second
        # sets _stop_event so _redis_subscriber_loop() exits cleanly
        # instead of blocking on a real Redis connection.
        call_count = {'n': 0}

        def _get_message(*_args, **_kwargs):
            call_count['n'] += 1
            if call_count['n'] == 1:
                return {'type': 'message', 'data': envelope}
            adapter._stop_event.set()
            return None

        mock_pubsub = MagicMock()
        mock_pubsub.get_message.side_effect = _get_message
        adapter._pubsub = mock_pubsub
        adapter._stop_event.clear()

        adapter._redis_subscriber_loop()

        self.assertEqual(adapter._iq_sample_rate, 250000)
        self.assertEqual(adapter._center_frequency, 93900000)
        queued = adapter._audio_chunk_queue.get_nowait()
        np.testing.assert_array_almost_equal(queued, audio)


class TestAudioService(unittest.TestCase):
    """Test audio service modifications."""

    def test_syntax(self):
        """Test that audio_service.py has valid syntax."""
        import py_compile
        import tempfile

        audio_service_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'audio_service.py'
        )

        try:
            # Compile to check syntax
            with tempfile.NamedTemporaryFile(suffix='.pyc', delete=True) as tmp:
                py_compile.compile(audio_service_path, tmp.name, doraise=True)
        except py_compile.PyCompileError as e:
            self.fail(f"Syntax error in audio_service.py: {e}")


class TestDataFlow(unittest.TestCase):
    """Test end-to-end data flow between services."""

    def test_iq_to_audio_pipeline(self):
        """Test IQ → Audio conversion pipeline."""
        # This would require full integration test with Redis
        # For now, just verify the encoding/decoding works

        # Create mock IQ samples (1 second at 2.5 MHz)
        sample_rate = 2500000
        duration = 0.1  # 100ms
        num_samples = int(sample_rate * duration)

        # Generate test signal (1 MHz sine wave)
        t = np.arange(num_samples) / sample_rate
        freq = 1000000  # 1 MHz
        iq_samples = np.exp(2j * np.pi * freq * t).astype(np.complex64)

        # Encode for Redis
        interleaved = np.empty(len(iq_samples) * 2, dtype=np.float32)
        interleaved[0::2] = iq_samples.real
        interleaved[1::2] = iq_samples.imag
        compressed = zlib.compress(interleaved.tobytes(), level=1)
        encoded = base64.b64encode(compressed).decode('ascii')

        # Create Redis message
        message = {
            'receiver_id': 'test-rx',
            'timestamp': 1234567890.0,
            'sample_count': len(iq_samples),
            'sample_rate': sample_rate,
            'center_frequency': 162550000,
            'encoding': 'zlib+base64',
            'samples': encoded
        }

        # Verify message can be JSON encoded
        json_str = json.dumps(message)
        self.assertIsInstance(json_str, str)

        # Verify message can be decoded
        decoded_message = json.loads(json_str)
        self.assertEqual(decoded_message['receiver_id'], 'test-rx')
        self.assertEqual(decoded_message['sample_count'], len(iq_samples))


class TestFIPSCodeLoading(unittest.TestCase):
    """Test FIPS code loading fix."""

    def test_fips_code_fix(self):
        """Verify FIPS code loading uses correct key."""
        from app_core.audio.startup_integration import load_fips_codes_from_config

        # Mock get_location_settings
        with patch('app_core.audio.startup_integration.get_location_settings') as mock_settings:
            # Test with list
            mock_settings.return_value = {'fips_codes': ['039137', '039001']}
            codes = load_fips_codes_from_config()
            self.assertEqual(codes, ['039137', '039001'])

            # Test with comma-separated string
            mock_settings.return_value = {'fips_codes': '039137,039001'}
            codes = load_fips_codes_from_config()
            self.assertEqual(codes, ['039137', '039001'])

            # Test with empty
            mock_settings.return_value = {'fips_codes': []}
            codes = load_fips_codes_from_config()
            self.assertEqual(codes, [])


def run_tests():
    """Run all tests and return results."""
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    # Add all test classes
    suite.addTests(loader.loadTestsFromTestCase(TestRedisSdrAdapter))
    suite.addTests(loader.loadTestsFromTestCase(TestAudioService))
    suite.addTests(loader.loadTestsFromTestCase(TestDataFlow))
    suite.addTests(loader.loadTestsFromTestCase(TestFIPSCodeLoading))

    # Run tests
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    return result


if __name__ == '__main__':
    result = run_tests()
    sys.exit(0 if result.wasSuccessful() else 1)
