"""
Audio Source Adapters

Concrete implementations of AudioSourceAdapter for different input types.
"""

from __future__ import annotations

import copy
import logging
import os
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin, urlparse

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
    """Audio source adapter that delegates streaming + decoding to FFmpeg."""

    def __init__(self, config: AudioSourceConfig):
        super().__init__(config)
        self._stream_url = self.config.device_params.get('stream_url', '')
        self._resolved_stream_url: Optional[str] = None
        self._ffmpeg_process: Optional[subprocess.Popen] = None
        self._stderr_thread: Optional[threading.Thread] = None
        self._pcm_backlog = bytearray()
        self._stream_metadata: Dict[str, Any] = {}
        self._last_restart = 0.0
        self._restart_delay_seconds = 3.0
        self._metadata_thread: Optional[threading.Thread] = None
        self._metadata_stop_event = threading.Event()
        self._metadata_lock = threading.Lock()
        self._last_icy_metadata: Optional[str] = None

    def _resolve_stream_url(self, url: str) -> str:
        """Validate the configured URL and resolve playlists when needed."""
        if not url:
            raise ValueError("stream_url must be configured for stream sources")

        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            raise ValueError(f"Unsupported stream URL scheme '{parsed.scheme}'")
        if not parsed.netloc:
            raise ValueError("Invalid stream URL: missing hostname")

        lower_path = parsed.path.lower()
        if lower_path.endswith('.m3u') or lower_path.endswith('.m3u8'):
            if not REQUESTS_AVAILABLE:
                raise RuntimeError("Requests library not available to resolve playlist URLs")

            try:
                response = requests.get(url, timeout=10)
                response.raise_for_status()
            except Exception as exc:
                raise RuntimeError(f"Failed to fetch playlist {url}: {exc}") from exc

            for line in response.text.splitlines():
                entry = line.strip()
                if not entry or entry.startswith('#'):
                    continue

                candidate = urljoin(url, entry)
                candidate_parsed = urlparse(candidate)
                if candidate_parsed.scheme in ("http", "https") and candidate_parsed.netloc:
                    logger.info(f"Resolved M3U entry to stream URL: {candidate}")
                    return candidate

            raise RuntimeError(f"Playlist {url} did not contain a playable stream URL")

        return url

    def _build_ffmpeg_command(self, stream_url: str) -> List[str]:
        """Construct the FFmpeg command used for streaming + decoding."""
        return [
            'ffmpeg',
            '-hide_banner',
            '-loglevel', 'error',
            '-nostdin',
            '-user_agent', 'EAS-Station/1.0',
            '-headers', 'Icy-MetaData:1\r\n',
            '-reconnect', '1',
            '-reconnect_streamed', '1',
            '-reconnect_on_network_error', '1',
            '-reconnect_delay_max', '5',
            '-fflags', '+genpts',
            '-i', stream_url,
            '-vn',
            '-acodec', 'pcm_s16le',
            '-ar', str(self.config.sample_rate),
            '-ac', str(self.config.channels),
            '-f', 's16le',
            'pipe:1',
        ]

    def _launch_ffmpeg_process(self) -> None:
        """Start a fresh FFmpeg process that reads from the resolved stream URL."""
        if not self._resolved_stream_url:
            raise RuntimeError("Stream URL has not been resolved yet")

        self._stop_ffmpeg_process()
        command = self._build_ffmpeg_command(self._resolved_stream_url)
        logger.info(f"{self.config.name}: launching FFmpeg decoder")

        try:
            process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                stdin=subprocess.DEVNULL,
                bufsize=0,
            )
        except FileNotFoundError as exc:
            raise RuntimeError("FFmpeg executable not found in PATH") from exc
        except Exception as exc:
            raise RuntimeError(f"Failed to start FFmpeg: {exc}") from exc

        if process.stdout is None:
            process.kill()
            raise RuntimeError("FFmpeg stdout pipe was not created")

        # Make stdout non-blocking so the capture loop can poll without hanging
        os.set_blocking(process.stdout.fileno(), False)

        # Drain stderr in a background thread to avoid the pipe filling up
        if process.stderr is not None:
            self._stderr_thread = threading.Thread(
                target=self._stderr_pump,
                args=(process,),
                name=f"ffmpeg-stderr-{self.config.name}",
                daemon=True,
            )
            self._stderr_thread.start()
        else:
            self._stderr_thread = None

        self._ffmpeg_process = process
        self._pcm_backlog.clear()
        self._last_restart = time.time()

    def _stop_ffmpeg_process(self) -> None:
        """Terminate any running FFmpeg process and clean up resources."""
        process = self._ffmpeg_process
        self._ffmpeg_process = None

        if process is None:
            return

        try:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    process.kill()
        finally:
            if process.stdout is not None:
                try:
                    process.stdout.close()
                except Exception:
                    pass
            if process.stderr is not None:
                try:
                    process.stderr.close()
                except Exception:
                    pass

        if self._stderr_thread and self._stderr_thread.is_alive():
            self._stderr_thread.join(timeout=1)
        self._stderr_thread = None

    def _restart_ffmpeg_process(self, reason: str) -> None:
        """Restart FFmpeg with a small backoff to avoid tight crash loops."""
        now = time.time()
        if now - self._last_restart < self._restart_delay_seconds:
            return

        logger.warning(f"{self.config.name}: restarting FFmpeg decoder ({reason})")
        try:
            self._launch_ffmpeg_process()
        except Exception as exc:
            self.status = AudioSourceStatus.ERROR
            self.error_message = str(exc)
            logger.error(f"{self.config.name}: failed to restart FFmpeg: {exc}")
        else:
            # Successful restart - clear error state and refresh metadata
            self.status = AudioSourceStatus.RUNNING
            self.error_message = None

            metadata_updates: Dict[str, Any] = {
                'connection_timestamp': time.time(),
                'last_error': None,
                'restart_reason': reason,
            }

            icy_state = self._stream_metadata.get('icy')
            if isinstance(icy_state, dict):
                metadata_updates['icy'] = {
                    'last_error': None,
                    'last_check': time.time(),
                    'supported': icy_state.get('supported', False),
                    'metaint': icy_state.get('metaint'),
                }

            self._apply_metadata_update(metadata_updates)
            logger.info(f"{self.config.name}: FFmpeg decoder restarted successfully")

    def _stderr_pump(self, process: subprocess.Popen) -> None:
        """Continuously drain FFmpeg stderr so it never blocks."""
        stderr = process.stderr
        if stderr is None:
            return

        try:
            for raw_line in iter(stderr.readline, b''):
                if not raw_line:
                    break
                text = raw_line.decode('utf-8', errors='replace').strip()
                if text:
                    logger.warning(f"{self.config.name}: FFmpeg stderr: {text}")
        except Exception as exc:
            logger.debug(f"{self.config.name}: stderr pump stopped: {exc}")

    def _start_capture(self) -> None:
        """Resolve the stream URL and start FFmpeg decoding."""
        resolved = self._resolve_stream_url(self._stream_url)
        self._resolved_stream_url = resolved

        self._stream_metadata = {
            'stream_url': self._stream_url,
            'resolved_url': resolved,
            'connection_timestamp': time.time(),
            'decoder': 'ffmpeg',
            'icy': {
                'supported': False,
            },
        }
        with self._metadata_lock:
            self.metrics.metadata = copy.deepcopy(self._stream_metadata)
        self._last_icy_metadata = None

        logger.info(f"{self.config.name}: resolved stream to {resolved}")
        self._launch_ffmpeg_process()
        self.status = AudioSourceStatus.RUNNING
        self._start_metadata_listener()

    def _stop_capture(self) -> None:
        """Stop FFmpeg decoding for the stream source."""
        self._stop_metadata_listener()
        self._stop_ffmpeg_process()
        self._pcm_backlog.clear()

    def _read_audio_chunk(self) -> Optional[np.ndarray]:
        """Read decoded PCM samples from FFmpeg stdout."""
        self._had_data_activity = False

        process = self._ffmpeg_process
        if process is None or process.poll() is not None:
            self._restart_ffmpeg_process("decoder not running")
            return None

        stdout = process.stdout
        if stdout is None:
            self._restart_ffmpeg_process("stdout pipe missing")
            return None

        bytes_per_sample = 2 * self.config.channels
        target_bytes = self.config.buffer_size * bytes_per_sample

        try:
            while len(self._pcm_backlog) < target_bytes:
                try:
                    chunk = stdout.read(target_bytes - len(self._pcm_backlog))
                except BlockingIOError:
                    break

                if not chunk:
                    if process.poll() is not None:
                        self._restart_ffmpeg_process("decoder exited")
                    break

                self._pcm_backlog.extend(chunk)
                self._had_data_activity = True
        except Exception as exc:
            logger.error(f"{self.config.name}: error reading from FFmpeg stdout: {exc}")
            self._restart_ffmpeg_process("stdout read error")
            return None

        if len(self._pcm_backlog) < target_bytes:
            return None

        raw = bytes(self._pcm_backlog[:target_bytes])
        del self._pcm_backlog[:target_bytes]

        samples = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
        return samples

    def _start_metadata_listener(self) -> None:
        """Start a background thread that harvests ICY metadata from the stream."""
        if not REQUESTS_AVAILABLE:
            return

        if self._metadata_thread and self._metadata_thread.is_alive():
            return

        self._metadata_stop_event.clear()
        self._metadata_thread = threading.Thread(
            target=self._metadata_loop,
            name=f"metadata-{self.config.name}",
            daemon=True,
        )
        self._metadata_thread.start()

    def _stop_metadata_listener(self) -> None:
        """Stop the ICY metadata harvesting thread."""
        self._metadata_stop_event.set()
        if self._metadata_thread and self._metadata_thread.is_alive():
            self._metadata_thread.join(timeout=2.0)
        self._metadata_thread = None

    def _metadata_loop(self) -> None:
        """Continuously poll the stream for ICY metadata updates."""
        if not REQUESTS_AVAILABLE:
            return

        session = requests.Session()
        session.headers.update({
            'User-Agent': 'EAS-Station/1.0',
            'Icy-MetaData': '1',
        })

        try:
            while not self._metadata_stop_event.is_set():
                stream_url = self._resolved_stream_url or self._stream_url
                if not stream_url:
                    break

                try:
                    response = session.get(
                        stream_url,
                        stream=True,
                        timeout=(5.0, 15.0),
                    )
                    response.raise_for_status()
                except Exception as exc:
                    logger.debug(
                        "%s: metadata request failed: %s",
                        self.config.name,
                        exc,
                    )
                    if self._metadata_stop_event.wait(5.0):
                        break
                    continue

                metaint_header = response.headers.get('icy-metaint')
                try:
                    metaint = int(metaint_header)
                except (TypeError, ValueError):
                    metaint = 0

                if metaint <= 0:
                    logger.debug(
                        "%s: stream does not advertise ICY metadata (icy-metaint=%s)",
                        self.config.name,
                        metaint_header,
                    )
                    self._apply_metadata_update({
                        'icy': {
                            'supported': False,
                            'last_error': 'ICY metadata not available',
                            'last_check': time.time(),
                        }
                    })
                    response.close()
                    if self._metadata_stop_event.wait(30.0):
                        break
                    continue

                self._apply_metadata_update({
                    'icy': {
                        'supported': True,
                        'metaint': metaint,
                        'last_error': None,
                        'last_check': time.time(),
                    }
                })

                raw = response.raw
                raw.decode_content = False

                try:
                    while not self._metadata_stop_event.is_set():
                        if not raw.read(metaint):
                            break

                        length_byte = raw.read(1)
                        if not length_byte:
                            break

                        block_length = length_byte[0] * 16
                        if block_length == 0:
                            continue

                        metadata_block = raw.read(block_length) or b''
                        metadata_text = metadata_block.rstrip(b'\x00').decode(
                            'utf-8', errors='replace'
                        ).strip()

                        if metadata_text:
                            self._handle_icy_metadata(metadata_text)

                except Exception as exc:
                    logger.debug(
                        "%s: error while reading ICY metadata: %s",
                        self.config.name,
                        exc,
                    )
                    self._apply_metadata_update({
                        'icy': {
                            'last_error': str(exc),
                            'last_check': time.time(),
                        }
                    })
                finally:
                    response.close()

                if self._metadata_stop_event.wait(3.0):
                    break
        finally:
            session.close()

    def _handle_icy_metadata(self, metadata_text: str) -> None:
        """Parse raw ICY metadata and update the source metadata cache."""
        if metadata_text == self._last_icy_metadata:
            return

        self._last_icy_metadata = metadata_text

        fields: Dict[str, Any] = {}
        for part in metadata_text.split(';'):
            part = part.strip()
            if not part or '=' not in part:
                continue

            key, value = part.split('=', 1)
            key = key.strip()
            value = value.strip().strip("'\"")
            if key:
                fields[key] = value

        updates: Dict[str, Any] = {
            'icy': {
                'supported': True,
                'fields': fields,
                'raw': metadata_text,
                'last_update': time.time(),
            }
        }

        stream_title = fields.get('StreamTitle')
        if stream_title:
            updates['song'] = stream_title

            # Parse rich metadata from StreamTitle (e.g., iHeartRadio format)
            # Example: text="Golden" song_spot="M" MediaBaseId="3136003" ... amgArtworkURL="..." length="00:03:11"
            import re

            title = stream_title.strip()
            artist = None

            # Try to extract text="" or song="" attribute (iHeartRadio format)
            text_match = re.search(r'text="([^"]+)"', stream_title)
            song_attr_match = re.search(r'song="([^"]+)"', stream_title)
            if text_match:
                title = text_match.group(1).strip()
                updates['song_title'] = title
                updates['title'] = title
            elif song_attr_match:
                title = song_attr_match.group(1).strip()
                updates['song_title'] = title
                updates['title'] = title

            # Try to extract artist="" attribute
            artist_match = re.search(r'artist="([^"]+)"', stream_title)
            if artist_match:
                artist = artist_match.group(1).strip()
                updates['artist'] = artist
                updates['song_artist'] = artist
            elif text_match or song_attr_match:
                # Pattern like "Artist - text=\"Title\" ..." or "Artist - song=\"Title\" ..."
                attr_key = 'text' if text_match else 'song'
                prefix_pattern = rf'(?P<artist>.+?)-\s*{attr_key}="'
                prefix_match = re.match(prefix_pattern, stream_title)
                if prefix_match:
                    artist_candidate = prefix_match.group('artist').strip()
                    if artist_candidate:
                        artist = artist_candidate
                        updates['artist'] = artist
                        updates['song_artist'] = artist

            # Try to extract album art URL
            artwork_match = re.search(r'(?:amgArtworkURL|artworkURL|artwork_url)="([^"]+)"', stream_title)
            if artwork_match:
                updates['artwork_url'] = artwork_match.group(1).strip()

            # Try to extract song length/duration
            length_match = re.search(r'(?:length|duration)="([^"]+)"', stream_title)
            if length_match:
                updates['length'] = length_match.group(1).strip()

            # Try to extract album name
            album_match = re.search(r'album="([^"]+)"', stream_title)
            if album_match:
                updates['album'] = album_match.group(1).strip()

            # If we didn't find text="" attribute, try traditional "Artist - Title" format
            if not text_match and ' - ' in stream_title:
                # Remove any XML-like attributes before splitting
                clean_title = re.sub(r'\s+\w+="[^"]*"', '', stream_title)
                clean_title = re.sub(r'\s+\w+=\S+', '', clean_title)
                clean_title = ' '.join(clean_title.split()).strip()

                if ' - ' in clean_title:
                    artist_candidate, title_candidate = clean_title.split(' - ', 1)
                    artist = artist_candidate.strip() or artist
                    title = title_candidate.strip() or title

                    if not artist_match and artist:
                        updates['artist'] = artist
                        updates.setdefault('song_artist', artist)
                    if not text_match:
                        updates['song_title'] = title
                        updates['title'] = title

            now_playing: Dict[str, Any] = {'raw': stream_title}
            if title:
                now_playing['title'] = title
            if artist:
                now_playing['artist'] = artist

            updates['now_playing'] = now_playing

        stream_url = fields.get('StreamUrl')
        if stream_url:
            updates['resolved_url'] = stream_url

        self._apply_metadata_update(updates)

    def _apply_metadata_update(self, updates: Dict[str, Any]) -> None:
        """Merge metadata updates into the shared cache and sync metrics."""

        def _merge_dict(base: Dict[str, Any], new_data: Dict[str, Any]) -> bool:
            changed = False
            for key, value in new_data.items():
                if isinstance(value, dict):
                    existing = base.get(key)
                    if isinstance(existing, dict):
                        if _merge_dict(existing, value):
                            changed = True
                    else:
                        base[key] = copy.deepcopy(value)
                        changed = True
                else:
                    if base.get(key) != value:
                        base[key] = value
                        changed = True
            return changed

        with self._metadata_lock:
            if _merge_dict(self._stream_metadata, updates):
                self.metrics.metadata = copy.deepcopy(self._stream_metadata)

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