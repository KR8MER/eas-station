"""
Audio Source Adapters

Concrete implementations of AudioSourceAdapter for different input types.
"""

from __future__ import annotations

import logging
import struct
import threading
import time
from pathlib import Path
from typing import Any, Dict, Optional

import numpy as np

from .ingest import AudioSourceAdapter, AudioSourceConfig, AudioSourceStatus

logger = logging.getLogger(__name__)

try:
    import alsaaudio
    ALSA_AVAILABLE = True
except ImportError:
    ALSA_AVAILABLE = False
    logger.warning("ALSA not available - ALSA source adapter will be disabled")

try:
    import pyaudio
    PULSE_AVAILABLE = True
except ImportError:
    PULSE_AVAILABLE = False
    logger.warning("PyAudio not available - PulseAudio source adapter will be disabled")

try:
    from app_core.radio.manager import RadioManager
    RADIO_AVAILABLE = True
except ImportError:
    RADIO_AVAILABLE = False
    logger.warning("Radio manager not available - SDR source adapter will be disabled")

try:
    import requests
    import urllib.parse
    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False
    logger.warning("Requests not available - Stream source adapter will be disabled")


class SDRSourceAdapter(AudioSourceAdapter):
    """Audio source adapter for SDR receivers via the radio manager."""

    def __init__(self, config: AudioSourceConfig):
        super().__init__(config)
        self._radio_manager: Optional[RadioManager] = None
        self._receiver_id: Optional[str] = None
        self._capture_handle: Optional[Any] = None
        self._demodulator = None  # Audio demodulator (if enabled)
        self._rbds_data = None  # Latest RBDS data
        self._receiver_config = None  # Receiver configuration

    def _start_capture(self) -> None:
        """Start SDR audio capture via radio manager."""
        if not RADIO_AVAILABLE:
            raise RuntimeError("Radio manager not available")

        receiver_id = self.config.device_params.get('receiver_id')
        if not receiver_id:
            raise ValueError("receiver_id required in device_params")

        self._radio_manager = RadioManager()
        self._receiver_id = receiver_id

        # Get receiver configuration to check demodulation settings
        from app_core.models import RadioReceiver
        from app_core.radio.demodulation import create_demodulator, DemodulatorConfig

        db_receiver = RadioReceiver.query.filter_by(identifier=receiver_id).first()
        if db_receiver:
            self._receiver_config = db_receiver.to_receiver_config()

            # Create demodulator if audio output is enabled and modulation is not IQ
            if self._receiver_config.audio_output and self._receiver_config.modulation_type != 'IQ':
                demod_config = DemodulatorConfig(
                    modulation_type=self._receiver_config.modulation_type,
                    sample_rate=self._receiver_config.sample_rate,
                    audio_sample_rate=self.config.sample_rate,
                    stereo_enabled=self._receiver_config.stereo_enabled,
                    deemphasis_us=self._receiver_config.deemphasis_us,
                    enable_rbds=self._receiver_config.enable_rbds
                )
                self._demodulator = create_demodulator(demod_config)
                logger.info(f"Created {self._receiver_config.modulation_type} demodulator for receiver: {receiver_id}")

        # Start IQ capture from the specified receiver
        # Note: This requires the radio manager to support IQ streaming,
        # which would need to be implemented in the receiver drivers
        self._capture_handle = self._radio_manager.start_audio_capture(
            receiver_id=self._receiver_id,
            sample_rate=self.config.sample_rate,
            channels=self.config.channels,
            format='iq' if self._demodulator else 'pcm'
        )

        self.status = AudioSourceStatus.RUNNING
        logger.info(f"Started SDR audio capture from receiver: {receiver_id}")

    def _stop_capture(self) -> None:
        """Stop SDR audio capture."""
        if self._capture_handle and self._radio_manager:
            self._radio_manager.stop_audio_capture(self._capture_handle)
            self._capture_handle = None
        self._radio_manager = None
        self._receiver_id = None

    def _read_audio_chunk(self) -> Optional[np.ndarray]:
        """Read audio chunk from SDR via radio manager."""
        if not self._capture_handle or not self._radio_manager:
            return None

        try:
            # Get data from radio manager (IQ or PCM depending on mode)
            audio_data = self._radio_manager.get_audio_data(
                self._capture_handle,
                chunk_size=self.config.buffer_size
            )

            if audio_data is not None:
                # If we have a demodulator, the data is IQ samples
                if self._demodulator:
                    # Convert to complex IQ samples
                    if isinstance(audio_data, bytes):
                        # Assume interleaved I/Q as float32 or int16
                        try:
                            iq_array = np.frombuffer(audio_data, dtype=np.float32)
                        except:
                            raw = np.frombuffer(audio_data, dtype=np.int16)
                            iq_array = raw.astype(np.float32) / 32768.0

                        # Convert interleaved I/Q to complex
                        iq_complex = iq_array[0::2] + 1j * iq_array[1::2]
                    else:
                        iq_complex = np.array(audio_data, dtype=np.complex64)

                    # Demodulate to audio
                    audio_array, rbds_data = self._demodulator.demodulate(iq_complex)

                    # Update RBDS data and metadata if available
                    if rbds_data:
                        self._rbds_data = rbds_data
                        if self.metrics.metadata is None:
                            self.metrics.metadata = {}
                        self.metrics.metadata['rbds_ps_name'] = rbds_data.ps_name
                        self.metrics.metadata['rbds_radio_text'] = rbds_data.radio_text
                        self.metrics.metadata['rbds_pty'] = rbds_data.pty

                    return audio_array

                else:
                    # No demodulation, just convert PCM to float32
                    if isinstance(audio_data, bytes):
                        # Assume 16-bit PCM
                        audio_array = np.frombuffer(audio_data, dtype=np.int16)
                        # Convert to float32 normalized to [-1, 1]
                        audio_array = audio_array.astype(np.float32) / 32768.0
                    else:
                        audio_array = np.array(audio_data, dtype=np.float32)

                    return audio_array

        except Exception as e:
            logger.error(f"Error reading SDR audio: {e}")

        return None


class ALSASourceAdapter(AudioSourceAdapter):
    """Audio source adapter for ALSA devices."""

    def __init__(self, config: AudioSourceConfig):
        super().__init__(config)
        self._alsa_device: Optional[alsaaudio.PCM] = None
        self._device_name = self.config.device_params.get('device_name', 'default')

    def _start_capture(self) -> None:
        """Start ALSA audio capture."""
        if not ALSA_AVAILABLE:
            raise RuntimeError("ALSA not available")

        try:
            # Create ALSA PCM capture device
            self._alsa_device = alsaaudio.PCM(
                alsaaudio.PCM_CAPTURE,
                alsaaudio.PCM_NORMAL,
                device=self._device_name
            )

            # Configure format
            self._alsa_device.setformat(alsaaudio.PCM_FORMAT_S16_LE)
            self._alsa_device.setrate(self.config.sample_rate)
            self._alsa_device.setchannels(self.config.channels)
            self._alsa_device.setperiodsize(self.config.buffer_size // 4)

            self.status = AudioSourceStatus.RUNNING
            logger.info(f"Started ALSA audio capture from device: {self._device_name}")

        except Exception as e:
            raise RuntimeError(f"Failed to start ALSA capture: {e}")

    def _stop_capture(self) -> None:
        """Stop ALSA audio capture."""
        if self._alsa_device:
            self._alsa_device.close()
            self._alsa_device = None

    def _read_audio_chunk(self) -> Optional[np.ndarray]:
        """Read audio chunk from ALSA device."""
        # If device is not connected, attempt reconnection
        if not self._alsa_device:
            if self._reconnect_attempts < self._max_reconnect_attempts:
                self._reconnect_attempts += 1
                logger.info(f"ALSA device disconnected, attempting to reconnect (attempt {self._reconnect_attempts}/{self._max_reconnect_attempts})")
                time.sleep(0.5)  # Reduced from 2s to 0.5s for faster recovery
                try:
                    self._start_capture()
                    self._reconnect_attempts = 0  # Reset on successful reconnect
                    return None
                except Exception as e:
                    logger.error(f"ALSA reconnection failed: {e}")
                    self.status = AudioSourceStatus.DISCONNECTED
                    return None
            else:
                # Max reconnection attempts reached
                self.status = AudioSourceStatus.ERROR
                self.error_message = f"Max reconnection attempts ({self._max_reconnect_attempts}) reached"
                return None

        try:
            # Read data from ALSA
            length, data = self._alsa_device.read()

            if length > 0 and data:
                # Reset reconnect attempts on successful read
                self._reconnect_attempts = 0
                # Convert bytes to numpy array
                audio_array = np.frombuffer(data, dtype=np.int16)
                # Convert to float32 normalized to [-1, 1]
                audio_array = audio_array.astype(np.float32) / 32768.0
                return audio_array

        except Exception as e:
            logger.error(f"Error reading ALSA audio: {e}")
            # Close the device to trigger reconnection
            if self._alsa_device:
                try:
                    self._alsa_device.close()
                except Exception:
                    pass
                self._alsa_device = None
            # Attempt reconnection on next call
            if self._reconnect_attempts < self._max_reconnect_attempts:
                self.status = AudioSourceStatus.DISCONNECTED

        return None


class PulseSourceAdapter(AudioSourceAdapter):
    """Audio source adapter for PulseAudio via PyAudio."""

    def __init__(self, config: AudioSourceConfig):
        super().__init__(config)
        self._pyaudio: Optional[pyaudio.PyAudio] = None
        self._stream: Optional[pyaudio.Stream] = None
        self._device_index = self.config.device_params.get('device_index', None)

    def _start_capture(self) -> None:
        """Start PulseAudio audio capture."""
        if not PULSE_AVAILABLE:
            raise RuntimeError("PyAudio not available")

        try:
            self._pyaudio = pyaudio.PyAudio()

            # Get device info if index specified
            if self._device_index is not None:
                device_info = self._pyaudio.get_device_info_by_index(self._device_index)
                logger.info(f"Using PulseAudio device: {device_info['name']}")

            # Create audio stream
            self._stream = self._pyaudio.open(
                format=pyaudio.paInt16,
                channels=self.config.channels,
                rate=self.config.sample_rate,
                input=True,
                input_device_index=self._device_index,
                frames_per_buffer=self.config.buffer_size
            )

            self.status = AudioSourceStatus.RUNNING
            logger.info("Started PulseAudio audio capture")

        except Exception as e:
            raise RuntimeError(f"Failed to start PulseAudio capture: {e}")

    def _stop_capture(self) -> None:
        """Stop PulseAudio audio capture."""
        if self._stream:
            self._stream.stop_stream()
            self._stream.close()
            self._stream = None
        
        if self._pyaudio:
            self._pyaudio.terminate()
            self._pyaudio = None

    def _read_audio_chunk(self) -> Optional[np.ndarray]:
        """Read audio chunk from PulseAudio stream."""
        # If stream is not connected, attempt reconnection
        if not self._stream or not self._pyaudio:
            if self._reconnect_attempts < self._max_reconnect_attempts:
                self._reconnect_attempts += 1
                logger.info(f"PulseAudio stream disconnected, attempting to reconnect (attempt {self._reconnect_attempts}/{self._max_reconnect_attempts})")
                time.sleep(0.5)  # Reduced from 2s to 0.5s for faster recovery
                try:
                    # Clean up old resources first
                    if self._stream:
                        try:
                            self._stream.stop_stream()
                            self._stream.close()
                        except Exception:
                            pass
                        self._stream = None
                    if self._pyaudio:
                        try:
                            self._pyaudio.terminate()
                        except Exception:
                            pass
                        self._pyaudio = None

                    # Attempt to restart
                    self._start_capture()
                    self._reconnect_attempts = 0  # Reset on successful reconnect
                    return None
                except Exception as e:
                    logger.error(f"PulseAudio reconnection failed: {e}")
                    self.status = AudioSourceStatus.DISCONNECTED
                    return None
            else:
                # Max reconnection attempts reached
                self.status = AudioSourceStatus.ERROR
                self.error_message = f"Max reconnection attempts ({self._max_reconnect_attempts}) reached"
                return None

        try:
            # Read data from stream
            data = self._stream.read(self.config.buffer_size, exception_on_overflow=False)

            if data:
                # Reset reconnect attempts on successful read
                self._reconnect_attempts = 0
                # Convert bytes to numpy array
                audio_array = np.frombuffer(data, dtype=np.int16)
                # Convert to float32 normalized to [-1, 1]
                audio_array = audio_array.astype(np.float32) / 32768.0
                return audio_array

        except Exception as e:
            logger.error(f"Error reading PulseAudio audio: {e}")
            # Close the stream to trigger reconnection
            if self._stream:
                try:
                    self._stream.stop_stream()
                    self._stream.close()
                except Exception:
                    pass
                self._stream = None
            if self._pyaudio:
                try:
                    self._pyaudio.terminate()
                except Exception:
                    pass
                self._pyaudio = None
            # Attempt reconnection on next call
            if self._reconnect_attempts < self._max_reconnect_attempts:
                self.status = AudioSourceStatus.DISCONNECTED

        return None


class FileSourceAdapter(AudioSourceAdapter):
    """Audio source adapter for audio files (useful for testing)."""

    def __init__(self, config: AudioSourceConfig):
        super().__init__(config)
        self._file_path = Path(self.config.device_params.get('file_path', ''))
        self._audio_data: Optional[np.ndarray] = None
        self._current_position = 0
        self._loop = self.config.device_params.get('loop', False)

    def _start_capture(self) -> None:
        """Start file audio capture."""
        if not self._file_path.exists():
            raise FileNotFoundError(f"Audio file not found: {self._file_path}")

        try:
            # Load audio file
            if self._file_path.suffix.lower() in ['.wav', '.wave']:
                self._audio_data = self._load_wav_file()
            elif self._file_path.suffix.lower() in ['.mp3']:
                self._audio_data = self._load_mp3_file()
            else:
                raise ValueError(f"Unsupported audio format: {self._file_path.suffix}")

            self._current_position = 0
            self.status = AudioSourceStatus.RUNNING
            logger.info(f"Started file audio capture: {self._file_path}")

        except Exception as e:
            raise RuntimeError(f"Failed to start file capture: {e}")

    def _stop_capture(self) -> None:
        """Stop file audio capture."""
        self._audio_data = None
        self._current_position = 0

    def _read_audio_chunk(self) -> Optional[np.ndarray]:
        """Read audio chunk from file."""
        if self._audio_data is None:
            return None

        try:
            # Calculate chunk end position
            end_pos = self._current_position + self.config.buffer_size
            
            if end_pos >= len(self._audio_data):
                if self._loop:
                    # Loop back to beginning
                    end_pos = end_pos % len(self._audio_data)
                    chunk = np.concatenate([
                        self._audio_data[self._current_position:],
                        self._audio_data[:end_pos]
                    ])
                    self._current_position = end_pos
                else:
                    # Return remaining data and mark as finished
                    chunk = self._audio_data[self._current_position:]
                    self._current_position = len(self._audio_data)
                    # Pad with zeros if needed
                    if len(chunk) < self.config.buffer_size:
                        padding = np.zeros(self.config.buffer_size - len(chunk), dtype=np.float32)
                        chunk = np.concatenate([chunk, padding])
            else:
                chunk = self._audio_data[self._current_position:end_pos]
                self._current_position = end_pos

            # Ensure mono if needed
            if len(chunk.shape) > 1 and chunk.shape[1] > 1:
                chunk = np.mean(chunk, axis=1)

            return chunk.astype(np.float32)

        except Exception as e:
            logger.error(f"Error reading file audio: {e}")
            return None

    def _load_wav_file(self) -> np.ndarray:
        """Load WAV file using wave module."""
        import wave
        
        with wave.open(str(self._file_path), 'rb') as wav_file:
            # Get audio properties
            sample_rate = wav_file.getframerate()
            channels = wav_file.getnchannels()
            sample_width = wav_file.getsampwidth()
            
            # Read all data
            frames = wav_file.readframes(-1)
            
            # Convert to numpy array
            if sample_width == 2:
                dtype = np.int16
            elif sample_width == 4:
                dtype = np.int32
            else:
                raise ValueError(f"Unsupported sample width: {sample_width}")
            
            audio_array = np.frombuffer(frames, dtype=dtype)
            
            # Convert to float32 and normalize
            max_val = float(np.iinfo(dtype).max)
            audio_array = audio_array.astype(np.float32) / max_val
            
            # Reshape if stereo
            if channels > 1:
                audio_array = audio_array.reshape(-1, channels)
            
            return audio_array

    def _load_mp3_file(self) -> np.ndarray:
        """Load MP3 file using pydub (if available)."""
        try:
            from pydub import AudioSegment
            
            audio = AudioSegment.from_mp3(str(self._file_path))
            
            # Convert to numpy array
            samples = np.array(audio.get_array_of_samples())
            
            if audio.channels == 2:
                samples = samples.reshape((-1, 2))
            
            # Convert to float32 and normalize
            max_val = float(2 ** (audio.sample_width * 8 - 1))
            samples = samples.astype(np.float32) / max_val
            
            return samples
            
        except ImportError:
            raise RuntimeError("pydub not available for MP3 playback - install with: pip install pydub")


class StreamSourceAdapter(AudioSourceAdapter):
    """Audio source adapter for HTTP/M3U audio streams."""

    def __init__(self, config: AudioSourceConfig):
        super().__init__(config)
        self._stream_url = self.config.device_params.get('stream_url', '')
        self._session: Optional[requests.Session] = None
        self._stream_response = None
        self._buffer = bytearray()
        self._stream_format = self.config.device_params.get('format', 'mp3')  # mp3, aac, raw
        self._decoder = None
        self._reconnect_attempts = 0
        self._max_reconnect_attempts = 5
        self._stream_metadata = {}  # Store stream metadata (URL, codec, bitrate, etc.)
        self._frame_analyzer = None  # Frame-level codec/bitrate analyzer
        self._analyzer_initialized = False  # Track if we've analyzed frames yet

    def _parse_m3u(self, url: str) -> str:
        """Parse M3U playlist and return the first stream URL."""
        try:
            response = requests.get(url, timeout=10)
            response.raise_for_status()

            content = response.text
            # Parse M3U content - look for http/https URLs
            for line in content.split('\n'):
                line = line.strip()
                if line and not line.startswith('#') and (line.startswith('http://') or line.startswith('https://')):
                    logger.info(f"Found stream URL in M3U: {line}")
                    return line

            raise ValueError("No valid stream URL found in M3U playlist")
        except Exception as e:
            raise RuntimeError(f"Failed to parse M3U playlist: {e}")

    def _start_capture(self) -> None:
        """Start HTTP stream audio capture."""
        if not REQUESTS_AVAILABLE:
            raise RuntimeError("Requests library not available")

        try:
            stream_url = self._stream_url

            # Validate URL scheme and netloc
            from urllib.parse import urlparse
            parsed = urlparse(stream_url)
            if parsed.scheme not in ('http', 'https'):
                raise ValueError(f"Invalid URL scheme '{parsed.scheme}'. Only http and https are allowed.")
            if not parsed.netloc:
                raise ValueError(f"Invalid URL: missing hostname")

            # Check if this is an M3U playlist
            if stream_url.lower().endswith('.m3u') or stream_url.lower().endswith('.m3u8'):
                stream_url = self._parse_m3u(stream_url)
                # Validate the resolved stream URL from M3U
                parsed = urlparse(stream_url)
                if parsed.scheme not in ('http', 'https'):
                    raise ValueError(f"Invalid M3U stream URL scheme '{parsed.scheme}'. Only http and https are allowed.")
                if not parsed.netloc:
                    raise ValueError(f"Invalid M3U stream URL: missing hostname")

            # Create session and start streaming
            self._session = requests.Session()
            self._session.headers.update({
                'User-Agent': 'EAS-Station/1.0',
                'Icy-MetaData': '1'  # Request Shoutcast/Icecast metadata
            })

            logger.info(f"Connecting to stream: {stream_url}")
            self._stream_response = self._session.get(stream_url, stream=True, timeout=30)
            self._stream_response.raise_for_status()

            # Extract comprehensive stream metadata from headers
            headers = self._stream_response.headers
            content_type = headers.get('Content-Type', 'unknown')

            # Auto-detect format from content-type if not specified
            detected_codec = self._stream_format
            if 'audio/mpeg' in content_type or 'audio/mp3' in content_type:
                detected_codec = 'mp3'
                self._stream_format = 'mp3'
            elif 'audio/aac' in content_type:
                detected_codec = 'aac'
                self._stream_format = 'aac'
            elif 'audio/ogg' in content_type:
                detected_codec = 'ogg'
                self._stream_format = 'ogg'

            # Extract bitrate from headers if available
            icy_br = headers.get('icy-br', headers.get('Icy-Br', headers.get('ice-audio-info', '')))
            bitrate = None
            if icy_br:
                try:
                    # Handle formats like "128" or "bitrate=128"
                    if 'bitrate=' in icy_br:
                        bitrate = int(icy_br.split('bitrate=')[1].split(';')[0])
                    else:
                        bitrate = int(icy_br)
                except (ValueError, IndexError):
                    pass

            # Build metadata dictionary
            self._stream_metadata = {
                'stream_url': stream_url,
                'resolved_url': stream_url,
                'codec': detected_codec,
                'content_type': content_type,
                'bitrate_kbps': bitrate,
                'icy_name': headers.get('icy-name', headers.get('Icy-Name')),
                'icy_genre': headers.get('icy-genre', headers.get('Icy-Genre')),
                'icy_description': headers.get('icy-description', headers.get('Icy-Description')),
                'server': headers.get('Server'),
                'connection_timestamp': time.time(),
            }

            # Update metrics with stream metadata
            self.metrics.metadata = self._stream_metadata.copy()

            # Log comprehensive stream metadata
            logger.info(f"Stream connected: {stream_url}")
            logger.info(f"  Codec: {detected_codec} | Content-Type: {content_type}")
            if bitrate:
                logger.info(f"  Bitrate: {bitrate} kbps")
            if self._stream_metadata.get('icy_name'):
                logger.info(f"  Station: {self._stream_metadata['icy_name']}")
            if self._stream_metadata.get('icy_genre'):
                logger.info(f"  Genre: {self._stream_metadata['icy_genre']}")

            self.status = AudioSourceStatus.RUNNING
            self._reconnect_attempts = 0
            logger.info(f"Started stream audio capture: {stream_url} (format: {self._stream_format})")

        except Exception as e:
            raise RuntimeError(f"Failed to start stream capture: {e}")

    def _stop_capture(self) -> None:
        """Stop HTTP stream audio capture."""
        if self._stream_response:
            try:
                self._stream_response.close()
            except Exception:
                pass
            self._stream_response = None

        if self._session:
            try:
                self._session.close()
            except Exception:
                pass
            self._session = None

        self._buffer.clear()
        self._decoder = None

    def _read_audio_chunk(self) -> Optional[np.ndarray]:
        """Read audio chunk from HTTP stream with improved error handling."""
        # If stream is disconnected, attempt reconnection
        if not self._stream_response:
            if self._reconnect_attempts < self._max_reconnect_attempts:
                self._reconnect_attempts += 1
                logger.info(f"Stream disconnected, attempting to reconnect (attempt {self._reconnect_attempts}/{self._max_reconnect_attempts})")
                time.sleep(0.5)  # Reduced from 2s to 0.5s for faster recovery
                try:
                    self._start_capture()
                    # Return None this iteration, will read data on next call
                    return None
                except Exception as e:
                    logger.error(f"Reconnection failed: {e}")
                    self.status = AudioSourceStatus.DISCONNECTED
                    return None
            else:
                # Max reconnection attempts reached
                self.status = AudioSourceStatus.ERROR
                self.error_message = f"Max reconnection attempts ({self._max_reconnect_attempts}) reached"
                return None

        try:
            # Read data from stream (smaller chunks for more continuous flow)
            chunk_size = self.config.buffer_size * 4  # Balanced size for low latency and efficiency

            try:
                data = self._stream_response.raw.read(chunk_size)
            except Exception as e:
                logger.error(f"Error reading from stream: {e}")
                # Attempt reconnection with shorter delay
                if self._reconnect_attempts < self._max_reconnect_attempts:
                    self._reconnect_attempts += 1
                    logger.info(f"Attempting to reconnect to stream (attempt {self._reconnect_attempts}/{self._max_reconnect_attempts})")
                    time.sleep(0.5)  # Reduced from 2s to 0.5s
                    try:
                        self._stop_capture()
                        self._start_capture()
                        return None
                    except Exception as reconnect_err:
                        logger.error(f"Reconnection attempt failed: {reconnect_err}")
                        self.status = AudioSourceStatus.DISCONNECTED
                        return None
                else:
                    self.status = AudioSourceStatus.ERROR
                    self.error_message = f"Read error after {self._max_reconnect_attempts} reconnect attempts: {str(e)}"
                    return None

            if not data:
                logger.warning("Stream ended or no data received")
                self.status = AudioSourceStatus.DISCONNECTED
                return None

            # Append to buffer
            self._buffer.extend(data)

            # Decode audio based on format
            if self._stream_format == 'mp3':
                return self._decode_mp3_chunk()
            elif self._stream_format == 'aac':
                return self._decode_aac_chunk()
            elif self._stream_format == 'ogg':
                return self._decode_ogg_chunk()
            elif self._stream_format == 'raw':
                return self._decode_raw_chunk()
            else:
                logger.error(f"Unsupported stream format: {self._stream_format}")
                return None

        except Exception as e:
            logger.error(f"Error reading stream audio: {e}")
            return None

    def _find_mp3_frame_sync(self, data: bytearray, start_pos: int = 0) -> int:
        """
        Find the next MP3 frame sync position in the buffer.
        MP3 frame sync: 11 bits set to 1 (0xFF 0xE0 or higher for second byte).
        Returns position of sync, or -1 if not found.
        """
        for i in range(start_pos, len(data) - 1):
            # Check for frame sync pattern: 0xFF followed by 0xE0-0xFF
            if data[i] == 0xFF and (data[i + 1] & 0xE0) == 0xE0:
                return i
        return -1

    def _decode_mp3_chunk(self) -> Optional[np.ndarray]:
        """Decode MP3 audio from buffer using pydub with improved error recovery."""
        try:
            from pydub import AudioSegment
            import io

            # Need minimum data to attempt decode (reduced to 1024 for faster, more continuous streaming)
            min_buffer_size = 1024
            if len(self._buffer) < min_buffer_size:
                return None

            # Analyze frame headers to detect actual bitrate/codec (only once)
            if not self._analyzer_initialized and len(self._buffer) >= 4096:
                self._analyze_stream_frames()
                self._analyzer_initialized = True

            # Limit buffer growth to prevent memory issues
            max_buffer_size = 131072  # 128KB max buffer
            if len(self._buffer) > max_buffer_size:
                # Find next frame sync and truncate buffer before it
                sync_pos = self._find_mp3_frame_sync(self._buffer, len(self._buffer) - max_buffer_size + 1024)
                if sync_pos > 0:
                    logger.warning(f"Buffer overflow ({len(self._buffer)} bytes), truncating to sync at {sync_pos}")
                    self._buffer = self._buffer[sync_pos:]
                else:
                    # No sync found, drop first half of buffer
                    drop_amount = len(self._buffer) // 2
                    logger.warning(f"Buffer overflow with no sync found, dropping {drop_amount} bytes")
                    self._buffer = self._buffer[drop_amount:]

            # Try to decode what we have
            decode_attempts = 0
            max_decode_attempts = 3

            while decode_attempts < max_decode_attempts and len(self._buffer) >= min_buffer_size:
                try:
                    # Take a chunk from buffer (try up to 32KB for better decoding)
                    chunk_size = min(32768, len(self._buffer))
                    chunk_data = bytes(self._buffer[:chunk_size])
                    buffer_io = io.BytesIO(chunk_data)

                    audio = AudioSegment.from_file(buffer_io, format="mp3")

                    # Only remove the bytes that were actually consumed by the decoder
                    bytes_consumed = buffer_io.tell()
                    if bytes_consumed > 0:
                        self._buffer = self._buffer[bytes_consumed:]
                    else:
                        # Decoder didn't consume anything, advance past current position
                        self._buffer = self._buffer[256:]

                    # Convert to numpy array
                    samples = np.array(audio.get_array_of_samples(), dtype=np.float32)

                    # Convert to mono if needed
                    if audio.channels == 2:
                        samples = samples.reshape((-1, 2))
                        samples = np.mean(samples, axis=1)

                    # Normalize
                    max_val = float(2 ** (audio.sample_width * 8 - 1))
                    samples = samples / max_val

                    # Successfully decoded
                    return samples

                except Exception as e:
                    decode_attempts += 1

                    # Try to find next MP3 frame sync
                    sync_pos = self._find_mp3_frame_sync(self._buffer, 1)

                    if sync_pos > 0:
                        # Found sync, skip to it
                        logger.debug(f"MP3 decode failed (attempt {decode_attempts}), skipping to frame sync at {sync_pos}")
                        self._buffer = self._buffer[sync_pos:]
                    elif len(self._buffer) > min_buffer_size:
                        # No sync found, drop small amount and continue
                        drop_amount = min(512, len(self._buffer) // 4)
                        logger.debug(f"MP3 decode failed (attempt {decode_attempts}), dropping {drop_amount} bytes")
                        self._buffer = self._buffer[drop_amount:]
                    else:
                        # Not enough data left
                        break

            # All decode attempts failed, but don't return None - wait for more data
            return None

        except ImportError:
            logger.error("pydub not available for MP3 stream decoding")
            self.status = AudioSourceStatus.ERROR
            self.error_message = "pydub library not available for MP3 decoding (install with: pip install pydub)"
            return None

    def _decode_aac_chunk(self) -> Optional[np.ndarray]:
        """Decode AAC audio from buffer."""
        # Analyze frame headers even if we can't decode yet
        if not self._analyzer_initialized and len(self._buffer) >= 4096:
            self._analyze_stream_frames()
            self._analyzer_initialized = True

        # AAC decoding would require additional libraries like faad
        logger.warning("AAC decoding not yet implemented - consider using MP3 streams")
        return None

    def _decode_ogg_chunk(self) -> Optional[np.ndarray]:
        """Decode OGG/Vorbis audio from buffer."""
        # Analyze frame headers even if we can't decode yet
        if not self._analyzer_initialized and len(self._buffer) >= 4096:
            self._analyze_stream_frames()
            self._analyzer_initialized = True

        # OGG decoding would require additional libraries
        logger.warning("OGG decoding not yet implemented - consider using MP3 streams")
        return None

    def _decode_raw_chunk(self) -> Optional[np.ndarray]:
        """Decode raw PCM audio from buffer."""
        try:
            # Assume 16-bit PCM
            bytes_needed = self.config.buffer_size * 2

            if len(self._buffer) < bytes_needed:
                return None

            # Extract samples
            chunk_data = bytes(self._buffer[:bytes_needed])
            self._buffer = self._buffer[bytes_needed:]

            # Convert to numpy array
            audio_array = np.frombuffer(chunk_data, dtype=np.int16)
            # Convert to float32 normalized to [-1, 1]
            audio_array = audio_array.astype(np.float32) / 32768.0

            return audio_array

        except Exception as e:
            logger.error(f"Error decoding raw audio: {e}")
            return None

    def _analyze_stream_frames(self) -> None:
        """
        Analyze stream buffer to detect codec and bitrate from frame headers.
        Updates stream metadata with detected values.
        """
        try:
            from app_core.audio.stream_analysis import analyze_stream

            # Analyze the current buffer
            stream_info = analyze_stream(self._buffer, hint_codec=self._stream_format)

            if stream_info:
                # Update metadata with detected values
                if stream_info.codec:
                    self._stream_metadata['codec'] = stream_info.codec
                    logger.info(f"  Detected codec from frames: {stream_info.codec}")

                if stream_info.bitrate_kbps:
                    self._stream_metadata['bitrate_kbps'] = stream_info.bitrate_kbps
                    vbr_note = " (VBR avg)" if stream_info.is_vbr else ""
                    logger.info(f"  Detected bitrate from frames: {stream_info.bitrate_kbps} kbps{vbr_note}")

                if stream_info.sample_rate:
                    self._stream_metadata['detected_sample_rate'] = stream_info.sample_rate
                    logger.info(f"  Detected sample rate: {stream_info.sample_rate} Hz")

                if stream_info.channels:
                    self._stream_metadata['detected_channels'] = stream_info.channels

                if stream_info.codec_version:
                    self._stream_metadata['codec_version'] = stream_info.codec_version
                    logger.info(f"  Codec version: {stream_info.codec_version}")

                if stream_info.is_vbr:
                    self._stream_metadata['is_vbr'] = True

                # Update metrics with the enhanced metadata
                self.metrics.metadata = self._stream_metadata.copy()

        except ImportError:
            logger.debug("Stream analysis module not available")
        except Exception as e:
            logger.debug(f"Error analyzing stream frames: {e}")


# Factory function for creating sources
def create_audio_source(config: AudioSourceConfig) -> AudioSourceAdapter:
    """Factory function to create the appropriate audio source adapter."""
    
    if config.source_type.value == "sdr":
        if not RADIO_AVAILABLE:
            raise RuntimeError("SDR source not available - radio manager missing")
        return SDRSourceAdapter(config)
    
    elif config.source_type.value == "alsa":
        if not ALSA_AVAILABLE:
            raise RuntimeError("ALSA source not available - install python3-alsaaudio")
        return ALSASourceAdapter(config)
    
    elif config.source_type.value == "pulse":
        if not PULSE_AVAILABLE:
            raise RuntimeError("PulseAudio source not available - install pyaudio")
        return PulseSourceAdapter(config)
    
    elif config.source_type.value == "file":
        return FileSourceAdapter(config)

    elif config.source_type.value == "stream":
        if not REQUESTS_AVAILABLE:
            raise RuntimeError("Stream source not available - install requests library")
        return StreamSourceAdapter(config)

    else:
        raise ValueError(f"Unsupported audio source type: {config.source_type}")