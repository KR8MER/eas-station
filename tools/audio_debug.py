#!/usr/bin/env python3
"""
Audio Debug and Calibration Utilities

Command-line tools for testing, calibrating, and troubleshooting
audio sources in the EAS Station audio ingest pipeline.
"""

import argparse
import json
import logging
import signal
import sys
import time
from pathlib import Path

import numpy as np

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    from app_core.audio.ingest import AudioIngestController, AudioSourceConfig, AudioSourceType
    from app_core.audio.sources import create_audio_source
    from app_core.audio.metering import AudioMeter, SilenceDetector, AudioHealthMonitor
    from configure import Config
except ImportError as e:
    print(f"Error importing audio modules: {e}")
    print("Make sure you're running from the project root with dependencies installed.")
    sys.exit(1)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class AudioDebugger:
    """Main audio debugging utility class."""

    def __init__(self):
        self.running = False
        self.controller = AudioIngestController()

    def signal_handler(self, signum, frame):
        """Handle Ctrl+C gracefully."""
        print("\nShutting down audio debug session...")
        self.running = False
        self.controller.cleanup()
        sys.exit(0)

    def test_source(self, config: AudioSourceConfig, duration: int = 10):
        """Test a single audio source."""
        print(f"\n=== Testing Audio Source: {config.name} ===")
        print(f"Type: {config.source_type.value}")
        print(f"Sample Rate: {config.sample_rate}")
        print(f"Channels: {config.channels}")
        print(f"Buffer Size: {config.buffer_size}")
        
        # Create source
        try:
            source = create_audio_source(config)
        except Exception as e:
            print(f"❌ Failed to create source: {e}")
            return False

        # Create health monitor
        health_monitor = AudioHealthMonitor(config.name)
        
        # Add alert callback
        def alert_callback(alert):
            print(f"🚨 [{alert.level.value.upper()}] {alert.source}: {alert.message}")
        
        health_monitor.add_alert_callback(alert_callback)

        # Start source
        print(f"\n🎤 Starting audio capture for {duration} seconds...")
        if not source.start():
            print("❌ Failed to start audio source")
            return False

        self.running = True
        start_time = time.time()
        chunk_count = 0
        
        try:
            while self.running and (time.time() - start_time) < duration:
                # Get audio chunk
                chunk = source.get_audio_chunk(timeout=1.0)
                
                if chunk is not None:
                    chunk_count += 1
                    
                    # Process through health monitor
                    health_status = health_monitor.process_samples(chunk)
                    
                    # Display metrics every 100 chunks
                    if chunk_count % 100 == 0:
                        meter = health_status['meter_levels']
                        health = health_status['health_score']
                        print(f"📊 Chunk {chunk_count}: "
                              f"RMS: {meter['rms_dbfs']:+.1f}dB, "
                              f"Peak: {meter['peak_dbfs']:+.1f}dB, "
                              f"Health: {health:.1f}%")
                else:
                    print("⚠️  No audio data received")
                    
        except KeyboardInterrupt:
            print("\n⏹️  Test interrupted by user")
        
        finally:
            source.stop()
            
        # Show final status
        final_status = health_monitor.get_health_status()
        print(f"\n📈 Final Status:")
        print(f"   Total chunks processed: {chunk_count}")
        print(f"   Final health score: {final_status['health_score']:.1f}%")
        print(f"   Silence detected: {final_status['silence_detected']}")
        if final_status['silence_detected']:
            print(f"   Silence duration: {final_status['silence_duration']:.1f}s")
        print(f"   Level trend: {final_status['level_trend']['direction']} "
              f"({final_status['level_trend']['trend']:+.1f}dB)")
        
        return True

    def test_all_sources(self, duration: int = 10):
        """Test all configured audio sources."""
        print("=== Testing All Configured Audio Sources ===")
        
        configs = self.get_configured_sources()
        
        if not configs:
            print("❌ No audio sources configured in environment variables")
            return False
        
        results = {}
        
        for config in configs:
            print(f"\n{'='*50}")
            success = self.test_source(config, duration)
            results[config.name] = success
            
            if not success:
                print(f"❌ Failed to test {config.name}")
            else:
                print(f"✅ Successfully tested {config.name}")
        
        # Summary
        print(f"\n{'='*50}")
        print("📋 TEST SUMMARY")
        for name, success in results.items():
            status = "✅ PASS" if success else "❌ FAIL"
            print(f"   {name}: {status}")
        
        return all(results.values())

    def get_configured_sources(self) -> list:
        """Get audio source configurations from environment."""
        configs = []
        
        # SDR source
        if getattr(Config, 'AUDIO_SDR_ENABLED', False):
            if getattr(Config, 'AUDIO_SDR_RECEIVER_ID', ''):
                config = AudioSourceConfig(
                    source_type=AudioSourceType.SDR,
                    name="sdr_main",
                    enabled=True,
                    priority=getattr(Config, 'AUDIO_SDR_PRIORITY', 100),
                    sample_rate=getattr(Config, 'AUDIO_INGEST_SAMPLE_RATE', 44100),
                    channels=getattr(Config, 'AUDIO_INGEST_CHANNELS', 1),
                    buffer_size=getattr(Config, 'AUDIO_INGEST_BUFFER_SIZE', 4096),
                    silence_threshold_db=getattr(Config, 'AUDIO_SILENCE_THRESHOLD_DB', -60.0),
                    device_params={'receiver_id': getattr(Config, 'AUDIO_SDR_RECEIVER_ID', '')}
                )
                configs.append(config)
        
        # ALSA source
        if getattr(Config, 'AUDIO_ALSA_ENABLED', False):
            config = AudioSourceConfig(
                source_type=AudioSourceType.ALSA,
                name="alsa_main",
                enabled=True,
                priority=getattr(Config, 'AUDIO_ALSA_PRIORITY', 200),
                sample_rate=getattr(Config, 'AUDIO_INGEST_SAMPLE_RATE', 44100),
                channels=getattr(Config, 'AUDIO_INGEST_CHANNELS', 1),
                buffer_size=getattr(Config, 'AUDIO_INGEST_BUFFER_SIZE', 4096),
                silence_threshold_db=getattr(Config, 'AUDIO_SILENCE_THRESHOLD_DB', -60.0),
                device_params={'device_name': getattr(Config, 'AUDIO_ALSA_DEVICE', 'default')}
            )
            configs.append(config)
        
        # PulseAudio source
        if getattr(Config, 'AUDIO_PULSE_ENABLED', False):
            device_index_str = getattr(Config, 'AUDIO_PULSE_DEVICE_INDEX', '')
            device_index = int(device_index_str) if device_index_str.isdigit() else None
            
            config = AudioSourceConfig(
                source_type=AudioSourceType.PULSE,
                name="pulse_main",
                enabled=True,
                priority=getattr(Config, 'AUDIO_PULSE_PRIORITY', 300),
                sample_rate=getattr(Config, 'AUDIO_INGEST_SAMPLE_RATE', 44100),
                channels=getattr(Config, 'AUDIO_INGEST_CHANNELS', 1),
                buffer_size=getattr(Config, 'AUDIO_INGEST_BUFFER_SIZE', 4096),
                silence_threshold_db=getattr(Config, 'AUDIO_SILENCE_THRESHOLD_DB', -60.0),
                device_params={'device_index': device_index}
            )
            configs.append(config)
        
        # File source
        if getattr(Config, 'AUDIO_FILE_ENABLED', False):
            file_path = getattr(Config, 'AUDIO_FILE_PATH', '')
            if file_path and Path(file_path).exists():
                config = AudioSourceConfig(
                    source_type=AudioSourceType.FILE,
                    name="file_test",
                    enabled=True,
                    priority=getattr(Config, 'AUDIO_FILE_PRIORITY', 999),
                    sample_rate=getattr(Config, 'AUDIO_INGEST_SAMPLE_RATE', 44100),
                    channels=getattr(Config, 'AUDIO_INGEST_CHANNELS', 1),
                    buffer_size=getattr(Config, 'AUDIO_INGEST_BUFFER_SIZE', 4096),
                    silence_threshold_db=getattr(Config, 'AUDIO_SILENCE_THRESHOLD_DB', -60.0),
                    device_params={
                        'file_path': file_path,
                        'loop': getattr(Config, 'AUDIO_FILE_LOOP', False)
                    }
                )
                configs.append(config)
        
        return configs

    def list_devices(self, source_type: str):
        """List available devices for a source type."""
        print(f"=== Available {source_type.upper()} Devices ===")
        
        if source_type.lower() == 'alsa':
            self._list_alsa_devices()
        elif source_type.lower() == 'pulse':
            self._list_pulse_devices()
        elif source_type.lower() == 'sdr':
            self._list_sdr_devices()
        else:
            print(f"❌ Device listing not supported for: {source_type}")

    def _list_alsa_devices(self):
        """List ALSA audio devices."""
        try:
            import alsaaudio
            
            # Capture devices
            print("\n🎤 Capture Devices:")
            for i, name in enumerate(alsaaudio.cards()):
                try:
                    # Try to get device info
                    device = alsaaudio.PCM(alsaaudio.PCM_CAPTURE, device=name)
                    print(f"   {i}: {name}")
                    device.close()
                except:
                    print(f"   {i}: {name} (may not support capture)")
                    
        except ImportError:
            print("❌ ALSA not available - install python3-alsaaudio")

    def _list_pulse_devices(self):
        """List PulseAudio devices."""
        try:
            import pyaudio
            
            p = pyaudio.PyAudio()
            
            print("\n🎤 Input Devices:")
            for i in range(p.get_device_count()):
                info = p.get_device_info_by_index(i)
                if info['maxInputChannels'] > 0:
                    print(f"   {i}: {info['name']} "
                          f"(channels: {info['maxInputChannels']}, "
                          f"rate: {int(info['defaultSampleRate'])})")
            
            p.terminate()
            
        except ImportError:
            print("❌ PyAudio not available - install pyaudio")

    def _list_sdr_devices(self):
        """List SDR devices via radio manager."""
        try:
            from app_core.radio.manager import RadioManager
            
            manager = RadioManager()
            devices = manager.discover_devices()
            
            print("\n📻 SDR Devices:")
            for device in devices:
                print(f"   ID: {device.get('id', 'unknown')}")
                print(f"   Type: {device.get('type', 'unknown')}")
                print(f"   Description: {device.get('description', 'No description')}")
                print(f"   Available: {device.get('available', False)}")
                print()
                
        except ImportError:
            print("❌ Radio manager not available")
        except Exception as e:
            print(f"❌ Error listing SDR devices: {e}")

    def generate_test_tone(self, frequency: float = 440.0, duration: float = 5.0, 
                          output_path: str = "test_tone.wav"):
        """Generate a test tone file."""
        print(f"🎵 Generating test tone: {frequency}Hz for {duration}s")
        
        sample_rate = 44100
        samples = int(sample_rate * duration)
        t = np.linspace(0, duration, samples, False)
        
        # Generate sine wave
        tone = 0.5 * np.sin(2 * np.pi * frequency * t)
        
        # Convert to 16-bit PCM
        tone_int16 = (tone * 32767).astype(np.int16)
        
        # Write to WAV file
        try:
            import wave
            
            with wave.open(output_path, 'wb') as wav_file:
                wav_file.setnchannels(1)  # Mono
                wav_file.setsampwidth(2)  # 16-bit
                wav_file.setframerate(sample_rate)
                wav_file.writeframes(tone_int16.tobytes())
            
            print(f"✅ Test tone saved to: {output_path}")
            
        except ImportError:
            print("❌ wave module not available")
        except Exception as e:
            print(f"❌ Error writing test tone: {e}")


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="EAS Station Audio Debug Utilities",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Test all configured audio sources
  python tools/audio_debug.py test-all --duration 15
  
  # Test only ALSA source
  python tools/audio_debug.py test --type alsa --duration 10
  
  # List available PulseAudio devices
  python tools/audio_debug.py list-devices --type pulse
  
  # Generate a 440Hz test tone
  python tools/audio_debug.py generate-tone --frequency 440 --duration 5
        """
    )
    
    subparsers = parser.add_subparsers(dest='command', help='Available commands')
    
    # Test all sources
    test_all_parser = subparsers.add_parser('test-all', help='Test all configured sources')
    test_all_parser.add_argument('--duration', type=int, default=10,
                                help='Test duration in seconds (default: 10)')
    
    # Test specific source
    test_parser = subparsers.add_parser('test', help='Test a specific source type')
    test_parser.add_argument('--type', choices=['sdr', 'alsa', 'pulse', 'file'],
                            required=True, help='Source type to test')
    test_parser.add_argument('--duration', type=int, default=10,
                            help='Test duration in seconds (default: 10)')
    test_parser.add_argument('--device', help='Device identifier')
    test_parser.add_argument('--file', help='File path (for file source)')
    
    # List devices
    list_parser = subparsers.add_parser('list-devices', help='List available devices')
    list_parser.add_argument('--type', choices=['sdr', 'alsa', 'pulse'],
                            required=True, help='Device type to list')
    
    # Generate test tone
    tone_parser = subparsers.add_parser('generate-tone', help='Generate test tone')
    tone_parser.add_argument('--frequency', type=float, default=440.0,
                            help='Frequency in Hz (default: 440)')
    tone_parser.add_argument('--duration', type=float, default=5.0,
                            help='Duration in seconds (default: 5.0)')
    tone_parser.add_argument('--output', default='test_tone.wav',
                            help='Output file path (default: test_tone.wav)')
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return
    
    debugger = AudioDebugger()
    signal.signal(signal.SIGINT, debugger.signal_handler)
    
    try:
        if args.command == 'test-all':
            success = debugger.test_all_sources(args.duration)
            sys.exit(0 if success else 1)
            
        elif args.command == 'test':
            # Create config for specific source type
            source_type = AudioSourceType(args.type)
            
            device_params = {}
            if args.type == 'sdr' and args.device:
                device_params['receiver_id'] = args.device
            elif args.type == 'alsa' and args.device:
                device_params['device_name'] = args.device
            elif args.type == 'pulse' and args.device:
                device_params['device_index'] = int(args.device) if args.device.isdigit() else args.device
            elif args.type == 'file' and args.file:
                device_params['file_path'] = args.file
            
            config = AudioSourceConfig(
                source_type=source_type,
                name=f"{args.type}_test",
                enabled=True,
                priority=100,
                sample_rate=getattr(Config, 'AUDIO_INGEST_SAMPLE_RATE', 44100),
                channels=getattr(Config, 'AUDIO_INGEST_CHANNELS', 1),
                buffer_size=getattr(Config, 'AUDIO_INGEST_BUFFER_SIZE', 4096),
                device_params=device_params
            )
            
            success = debugger.test_source(config, args.duration)
            sys.exit(0 if success else 1)
            
        elif args.command == 'list-devices':
            debugger.list_devices(args.type)
            
        elif args.command == 'generate-tone':
            debugger.generate_test_tone(args.frequency, args.duration, args.output)
            
    except KeyboardInterrupt:
        print("\n⏹️  Operation cancelled by user")
        sys.exit(130)
    except Exception as e:
        print(f"❌ Error: {e}")
        sys.exit(1)


if __name__ == '__main__':
    main()