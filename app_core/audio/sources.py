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

    def _start_capture(self) -> None:
        """Start SDR audio capture via radio manager."""
        if not RADIO_AVAILABLE:
            raise RuntimeError("Radio manager not available")

        receiver_id = self.config.device_params.get('receiver_id')
        if not receiver_id:
            raise ValueError("receiver_id required in device_params")

        self._radio_manager = RadioManager()
        self._receiver_id = receiver_id

        # Start audio capture from the specified receiver
        self._capture_handle = self._radio_manager.start_audio_capture(
            receiver_id=self._receiver_id,
            sample_rate=self.config.sample_rate,
            channels=self.config.channels,
            format='pcm'  # Get PCM audio instead of IQ
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
            # Get audio data from radio manager
            audio_data = self._radio_manager.get_audio_data(
                self._capture_handle,
                chunk_size=self.config.buffer_size
            )
            
            if audio_data is not None:
                # Convert to numpy array if needed
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
        self._ffmpeg_process = None  # FFmpeg subprocess for decoding
        self._pcm_buffer = bytearray()  # Buffer for decoded PCM audio
        self._ffmpeg_thread = None  # Thread for feeding data to FFmpeg

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
        # Stop FFmpeg process first
        if self._ffmpeg_process:
            try:
                self._ffmpeg_process.terminate()
                self._ffmpeg_process.wait(timeout=2)
            except Exception:
                try:
                    self._ffmpeg_process.kill()
                except Exception:
                    pass
            self._ffmpeg_process = None

        if self._ffmpeg_thread and self._ffmpeg_thread.is_alive():
            self._ffmpeg_thread.join(timeout=2)
        self._ffmpeg_thread = None

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
        self._pcm_buffer.clear()
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

    def _start_ffmpeg_decoder(self) -> None:
        """Start FFmpeg subprocess for decoding stream audio."""
        import subprocess

        if self._ffmpeg_process:
            return  # Already running

        try:
            # Start FFmpeg to decode stream to raw PCM
            self._ffmpeg_process = subprocess.Popen([
                'ffmpeg',
                '-f', self._stream_format,  # Input format (mp3, aac, etc.)
                '-i', 'pipe:0',              # Read from stdin
                '-f', 's16le',               # Output 16-bit PCM little-endian
                '-ar', str(self.config.sample_rate),  # Sample rate
                '-ac', '1',                  # Mono output
                '-loglevel', 'error',        # Only show errors
                'pipe:1'                     # Output to stdout
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=4096
            )

            # Start thread to feed data to FFmpeg
            self._ffmpeg_thread = threading.Thread(
                target=self._feed_ffmpeg,
                name=f"ffmpeg-feeder-{self.config.name}",
                daemon=True
            )
            self._ffmpeg_thread.start()

            logger.info(f"Started FFmpeg decoder for {self.config.name}")

        except Exception as e:
            logger.error(f"Failed to start FFmpeg decoder: {e}")
            self.status = AudioSourceStatus.ERROR
            self.error_message = f"FFmpeg decoder error: {e}"

    def _feed_ffmpeg(self) -> None:
        """Thread function to feed encoded data from buffer to FFmpeg stdin."""
        while self._ffmpeg_process and self._ffmpeg_process.poll() is None:
            try:
                if len(self._buffer) > 0:
                    # Send data to FFmpeg stdin
                    chunk = bytes(self._buffer[:4096])
                    self._buffer = self._buffer[4096:]

                    if self._ffmpeg_process and self._ffmpeg_process.stdin:
                        self._ffmpeg_process.stdin.write(chunk)
                        self._ffmpeg_process.stdin.flush()
                else:
                    # No data to send, sleep briefly
                    time.sleep(0.01)

            except Exception as e:
                logger.error(f"Error feeding FFmpeg: {e}")
                break

    def _decode_mp3_chunk(self) -> Optional[np.ndarray]:
        """Decode MP3 audio from buffer using FFmpeg subprocess."""
        try:
            # Start FFmpeg decoder if not already running
            if not self._ffmpeg_process or self._ffmpeg_process.poll() is not None:
                self._start_ffmpeg_decoder()

            if not self._ffmpeg_process:
                return None

            # Read decoded PCM from FFmpeg stdout (non-blocking)
            import select
            import os

            # Check if data is available to read
            if self._ffmpeg_process.stdout:
                # Try to read decoded PCM data
                try:
                    # Read up to 16KB of PCM data
                    chunk = self._ffmpeg_process.stdout.read(16384)
                    if chunk:
                        self._pcm_buffer.extend(chunk)
                except Exception:
                    pass

            # Convert PCM buffer to numpy array when we have enough data
            bytes_per_sample = 2  # 16-bit = 2 bytes
            samples_available = len(self._pcm_buffer) // bytes_per_sample

            # Aim for ~0.05 seconds of audio per chunk
            target_samples = int(self.config.sample_rate * 0.05)

            if samples_available >= target_samples:
                # Extract samples
                bytes_to_extract = target_samples * bytes_per_sample
                pcm_data = bytes(self._pcm_buffer[:bytes_to_extract])
                self._pcm_buffer = self._pcm_buffer[bytes_to_extract:]

                # Convert to numpy array
                samples = np.frombuffer(pcm_data, dtype=np.int16)

                # Convert to float32 normalized to [-1, 1]
                samples = samples.astype(np.float32) / 32768.0

                return samples

            return None

        except Exception as e:
            logger.error(f"Error in FFmpeg decoding: {e}")
            return None

    def _decode_aac_chunk(self) -> Optional[np.ndarray]:
        """Decode AAC audio from buffer using FFmpeg."""
        # FFmpeg handles AAC natively, use the same decoder
        return self._decode_mp3_chunk()

    def _decode_ogg_chunk(self) -> Optional[np.ndarray]:
        """Decode OGG/Vorbis audio from buffer using FFmpeg."""
        # FFmpeg handles OGG natively, use the same decoder
        return self._decode_mp3_chunk()

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