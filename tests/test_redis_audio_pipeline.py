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
- app_core/audio/redis_audio_publisher.py: audio sample publishing out of
  eas_monitoring_service.py
- the IQ/audio Redis message encoding itself
- FIPS code loading used by the EAS monitor
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
        """Test IQ sample decoding from Redis message."""
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


class TestRedisAudioPublisher(unittest.TestCase):
    """Test Redis audio publisher."""

    def test_import(self):
        """Test that RedisAudioPublisher can be imported."""
        try:
            from app_core.audio.redis_audio_publisher import RedisAudioPublisher
            self.assertIsNotNone(RedisAudioPublisher)
        except ImportError as e:
            self.fail(f"Failed to import RedisAudioPublisher: {e}")


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
    suite.addTests(loader.loadTestsFromTestCase(TestRedisAudioPublisher))
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
