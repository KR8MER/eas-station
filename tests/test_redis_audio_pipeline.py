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

    def test_get_remote_status_decodes_json_and_caches(self):
        """_get_remote_status() replaces self._demodulator.get_last_status()
        now that the demodulator lives in eas-station-demod.service --
        verify it fetches+decodes the status key (JSON, not pickle -- see
        app_core/radio/demod/types.py's demodulator_status_to/from_json_dict)
        and reuses it within the cache TTL instead of round-tripping Redis
        on every call."""
        from app_core.radio.demod.types import DemodulatorStatus, demodulator_status_to_json_dict

        adapter = self._make_adapter()

        status_obj = DemodulatorStatus(stereo_pilot_locked=True)
        mock_redis = MagicMock()
        mock_redis.get.return_value = json.dumps(demodulator_status_to_json_dict(status_obj))
        adapter._redis_client = mock_redis

        first = adapter._get_remote_status()
        second = adapter._get_remote_status()

        # Decoding produces a new (but equal-by-value) object -- check
        # content, not identity, against the original.
        self.assertTrue(first.stereo_pilot_locked)
        # The cache returns the literal object from the first decode.
        self.assertIs(second, first)
        # Cached within _STATUS_CACHE_TTL_S -- only one Redis round-trip.
        self.assertEqual(mock_redis.get.call_count, 1)
        mock_redis.get.assert_called_with('demod:status:test-receiver')

    def test_get_remote_status_keeps_last_known_on_ttl_gap(self):
        """A missing key (TTL lapsed between demod publishes) should not
        flap the UI to blank -- keep showing the last-known status, same
        behavior the old in-process path had while a demodulator was
        between decode cycles."""
        from app_core.audio.redis_sdr_adapter import _STATUS_CACHE_TTL_S
        from app_core.radio.demod.types import DemodulatorStatus, demodulator_status_to_json_dict

        adapter = self._make_adapter()

        status_obj = DemodulatorStatus()
        mock_redis = MagicMock()
        mock_redis.get.return_value = json.dumps(demodulator_status_to_json_dict(status_obj))
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
        envelope = base64.b64encode(
            _pack_audio_envelope(audio.tobytes(), 250000, 93900000)
        ).decode('ascii')

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

    def test_subscriber_loop_reshapes_stereo_audio_envelope(self):
        """Regression test: services/demod/worker.py publishes stereo audio
        as np.column_stack((left, right)) -- a (frames, 2) array -- and
        .tobytes() flattens that to interleaved L,R,L,R floats. The receive
        side (_unpack_audio_envelope) can only hand back a flat 1-D array,
        since the wire format carries no shape info.

        Without reshaping using the adapter's own config.channels, that flat
        array reached IcecastOutputStreamer._samples_to_pcm_bytes() as
        ndim==1, which treated every one of the 2x-as-many interleaved
        values as an independent mono sample and upmixed each to fake
        stereo -- doubling the frame count FFmpeg received per real second
        of audio (and scrambling the L/R image in the process). FFmpeg still
        assumed config.sample_rate frames/sec, so the encoded stream ended
        up representing ~2x the declared audio duration per real second --
        audible on the live Icecast relay as playback running at roughly
        half speed (deep, dragging pitch).
        """
        from services.demod.worker import _pack_audio_envelope
        from app_core.audio.ingest import AudioSourceConfig, AudioSourceType

        stereo_config = AudioSourceConfig(
            source_type=AudioSourceType.STREAM,
            name="test-redis-sdr-stereo",
            enabled=True,
            priority=1,
            sample_rate=48000,
            channels=2,
            buffer_size=4096,
            device_params={'receiver_id': 'test-receiver', 'demod_mode': 'WFM'},
        )
        from app_core.audio.redis_sdr_adapter import RedisSDRSourceAdapter
        adapter = RedisSDRSourceAdapter(stereo_config)
        adapter._receiver_id = 'test-receiver'

        left = np.random.randn(200).astype(np.float32)
        right = np.random.randn(200).astype(np.float32)
        stereo_audio = np.column_stack((left, right))  # what fm.py actually returns
        envelope = base64.b64encode(
            _pack_audio_envelope(stereo_audio.astype(np.float32).tobytes(), 256000, 93900000)
        ).decode('ascii')

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

        queued = adapter._audio_chunk_queue.get_nowait()
        # Must come back as (frames, channels), not a flat (frames*channels,)
        # array -- otherwise the frame count downstream doubles.
        self.assertEqual(queued.shape, (200, 2))
        np.testing.assert_array_almost_equal(queued, stereo_audio)


class TestSameDecodeStereoRegression(unittest.TestCase):
    """End-to-end regression test for the stereo-reshape fix, proven against
    the real SAME decoder rather than just checking array shape.

    Runs a synthetic RWT header + EOM, encoded as a genuine (frames, 2)
    stereo array (the exact shape services/demod/worker.py's
    np.column_stack((left, right)) produces), through the real
    production pipeline: the same wire pack/unpack the demod service and
    RedisSDRSourceAdapter use, the same _resample_for_eas() downmix +
    resample logic from app_core/audio/ingest.py, and the real
    StreamingSAMEDecoder class eas_monitor_v3 uses -- twice: once with
    the flat array left unreshaped (reproducing the pre-fix bug) and once
    reshaped to (frames, 2) (the fix), to prove cause and effect directly
    rather than just asserting on array shape.
    """

    SAMPLE_RATE = 48000

    def _build_stereo_test_signal(self) -> np.ndarray:
        from datetime import datetime, timezone
        from app_utils.eas_fsk import (
            SAME_BAUD, SAME_MARK_FREQ, SAME_SPACE_FREQ,
            encode_same_bits, generate_fsk_samples,
        )

        amplitude = 0.7 * 32767
        now = datetime.now(timezone.utc)
        timestamp = f"{now.timetuple().tm_yday:03d}{now:%H%M}"
        header_text = f"ZCZC-EAS-RWT-000000+0015-{timestamp}-EASTEST-"

        same_bits = encode_same_bits(header_text, include_preamble=True)
        header_samples = generate_fsk_samples(
            same_bits, sample_rate=self.SAMPLE_RATE, bit_rate=float(SAME_BAUD),
            mark_freq=SAME_MARK_FREQ, space_freq=SAME_SPACE_FREQ, amplitude=amplitude,
        )
        silence = [0] * self.SAMPLE_RATE
        all_samples = []
        for i in range(3):
            all_samples.extend(header_samples)
            if i < 2:
                all_samples.extend(silence)
        all_samples.extend(silence)

        eom_bits = encode_same_bits("NNNN", include_preamble=True, include_cr=False)
        eom_samples = generate_fsk_samples(
            eom_bits, sample_rate=self.SAMPLE_RATE, bit_rate=float(SAME_BAUD),
            mark_freq=SAME_MARK_FREQ, space_freq=SAME_SPACE_FREQ, amplitude=amplitude,
        )
        for i in range(3):
            all_samples.extend(eom_samples)
            if i < 2:
                all_samples.extend(silence)

        mono = np.array(all_samples, dtype=np.float32) / 32767.0
        return np.column_stack((mono, mono)).astype(np.float32), header_text

    def _run_pipeline(self, flat_audio: np.ndarray, apply_fix: bool) -> list:
        from app_core.audio.eas_resampler import make_eas_resampler
        from app_core.audio.streaming_same_decoder import StreamingSAMEDecoder

        detections = []
        decoder = StreamingSAMEDecoder(sample_rate=16000, alert_callback=detections.append)
        resampler = make_eas_resampler(self.SAMPLE_RATE, 16000)

        channels = 2
        chunk_size = 1600 * channels
        for start in range(0, len(flat_audio), chunk_size):
            raw_chunk = flat_audio[start:start + chunk_size]
            if raw_chunk.size == 0:
                continue

            if apply_fix and raw_chunk.size % channels == 0:
                chunk = raw_chunk.reshape(-1, channels)
            else:
                chunk = raw_chunk  # pre-fix: flat interleaved L,R,L,R as-is

            if chunk.ndim == 2:
                mono = chunk.mean(axis=1)
            elif chunk.ndim > 2:
                mono = chunk.flatten()
            else:
                mono = chunk  # bug path

            resampled = resampler.process(mono.astype(np.float32))
            if resampled is not None and len(resampled) > 0:
                decoder.process_samples(resampled)

        return detections

    def test_stereo_reshape_is_required_for_same_decode(self):
        from services.demod.worker import _pack_audio_envelope
        from app_core.audio.redis_sdr_adapter import _unpack_audio_envelope

        stereo_tone, header_text = self._build_stereo_test_signal()
        envelope = _pack_audio_envelope(stereo_tone.tobytes(), 256000, 93900000)
        _iq_rate, _freq, flat_audio = _unpack_audio_envelope(envelope)
        self.assertEqual(flat_audio.ndim, 1)  # always flat off the wire

        before = self._run_pipeline(flat_audio, apply_fix=False)
        after = self._run_pipeline(flat_audio, apply_fix=True)

        self.assertEqual(
            len(before), 0,
            "Expected the pre-fix (unreshaped) path to fail to decode -- "
            "if this now passes, the bug's premise has changed and this "
            "test needs re-evaluating, not just the assertion loosened.",
        )
        self.assertGreater(
            len(after), 0,
            "Reshaping the flat stereo array to (frames, channels) before "
            "feeding it to _resample_for_eas() must be enough for the SAME "
            "decoder to detect a real header -- this is what actually "
            "restores SAME/RMT reception on stereo SDR receivers.",
        )
        self.assertIn(header_text, after[0].message)


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
