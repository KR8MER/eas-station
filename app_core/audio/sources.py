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
        if not self._alsa_device:
            return None

        try:
            # Read data from ALSA
            length, data = self._alsa_device.read()
            
            if length > 0 and data:
                # Convert bytes to numpy array
                audio_array = np.frombuffer(data, dtype=np.int16)
                # Convert to float32 normalized to [-1, 1]
                audio_array = audio_array.astype(np.float32) / 32768.0
                return audio_array
                
        except Exception as e:
            logger.error(f"Error reading ALSA audio: {e}")
            
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
        if not self._stream:
            return None

        try:
            # Read data from stream
            data = self._stream.read(self.config.buffer_size, exception_on_overflow=False)
            
            if data:
                # Convert bytes to numpy array
                audio_array = np.frombuffer(data, dtype=np.int16)
                # Convert to float32 normalized to [-1, 1]
                audio_array = audio_array.astype(np.float32) / 32768.0
                return audio_array
                
        except Exception as e:
            logger.error(f"Error reading PulseAudio audio: {e}")
            
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
    
    else:
        raise ValueError(f"Unsupported audio source type: {config.source_type}")