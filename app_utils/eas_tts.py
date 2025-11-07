"""Text-to-speech helpers used by the EAS audio generator."""

from __future__ import annotations

import audioop
import ctypes.util
import io
import os
import re
import shutil
import struct
import subprocess
import tempfile
import wave
from typing import Dict, List, Optional

try:  # pragma: no cover - optional dependency for HTTP requests
    import requests  # type: ignore
except Exception:  # pragma: no cover - keep optional
    requests = None

try:  # pragma: no cover - optional dependency for Azure TTS
    import azure.cognitiveservices.speech as azure_speech  # type: ignore
except Exception:  # pragma: no cover - keep optional
    azure_speech = None

try:  # pragma: no cover - optional dependency for offline TTS
    import pyttsx3  # type: ignore
except Exception:  # pragma: no cover - keep optional
    pyttsx3 = None

LIBESPEAK_DEPENDENCY_TEXT = (
    "libespeak-ng1 (or libespeak1 on older distros; "
    'e.g., "sudo apt-get install libespeak-ng1")'
)

_ESPEAK_VOICE_TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9_.+-]+$")


def _espeak_voice_from_preference(preference: str) -> Optional[str]:
    """Return an espeak-compatible voice token if the preference looks valid."""

    preference = preference.strip()
    if not preference:
        return None

    if _ESPEAK_VOICE_TOKEN_PATTERN.fullmatch(preference):
        return preference

    return None


def _normalize_pcm_samples(
    raw_frames: bytes,
    sample_width: int,
    channels: int,
    source_rate: int,
    target_rate: int,
) -> List[int]:
    """Convert raw PCM frames into 16-bit mono samples at the desired rate."""

    if sample_width != 2:
        raw_frames = audioop.lin2lin(raw_frames, sample_width, 2)
    if channels != 1:
        raw_frames = audioop.tomono(raw_frames, 2, 0.5, 0.5)
    if source_rate != target_rate:
        raw_frames, _ = audioop.ratecv(raw_frames, 2, 1, source_rate, target_rate, None)

    sample_count = len(raw_frames) // 2
    if sample_count <= 0:
        return []

    return list(struct.unpack("<" + "h" * sample_count, raw_frames[: sample_count * 2]))

def _pyttsx3_dependency_hint() -> Optional[str]:
    """Suggest installation guidance for common pyttsx3 system dependencies."""

    missing: List[str] = []

    if not ctypes.util.find_library("espeak") and not ctypes.util.find_library("espeak-ng"):
        missing.append(LIBESPEAK_DEPENDENCY_TEXT)

    if shutil.which("ffmpeg") is None:
        missing.append('ffmpeg (e.g., "sudo apt-get install ffmpeg")')

    if not missing:
        return None

    if len(missing) == 1:
        return f"pyttsx3 requires {missing[0]}."

    dependency_list = ", ".join(missing[:-1]) + f", and {missing[-1]}"
    return f"pyttsx3 requires {dependency_list}."


def _pyttsx3_error_hint(exc: Exception) -> Optional[str]:
    """Return a friendly remediation hint for common pyttsx3 failures."""

    detail = str(exc).lower()
    if "libespeak" in detail:
        return (
            "pyttsx3 requires the libespeak shared library. "
            f"Install {LIBESPEAK_DEPENDENCY_TEXT}."
        )

    if "ffmpeg" in detail or "weakly-referenced object" in detail:
        dependency_hint = _pyttsx3_dependency_hint()
        if dependency_hint:
            return dependency_hint

    return _pyttsx3_dependency_hint()


class TTSEngine:
    """Encapsulate text-to-speech rendering for the EAS audio generator."""

    def __init__(self, config: Dict[str, object], logger, sample_rate: int) -> None:
        self.config = config
        self.logger = logger
        self.sample_rate = sample_rate
        self._last_error: Optional[str] = None

    @property
    def last_error(self) -> Optional[str]:
        return self._last_error

    @property
    def provider(self) -> str:
        return (str(self.config.get("tts_provider") or "").strip().lower())

    def clear_error(self) -> None:
        self._remember_error(None)

    def generate(self, text: str) -> Optional[List[int]]:
        provider = self.provider
        self._remember_error(None)

        if not text.strip():
            return None

        if provider == "azure":
            return self._generate_azure_voiceover(text)
        if provider == "azure_openai":
            return self._generate_azure_openai_voiceover(text)
        if provider == "pyttsx3":
            return self._generate_pyttsx3_voiceover(text)

        if provider and self.logger:
            self.logger.warning('Unknown TTS provider "%s"; skipping voiceover.', provider)
            self._remember_error(f'Unknown TTS provider "{provider}".')

        return None

    def _remember_error(self, message: Optional[str]) -> None:
        self._last_error = message or None

    def _generate_azure_openai_voiceover(self, text: str) -> Optional[List[int]]:
        """Generate voiceover using Azure OpenAI TTS (OpenAI API format)."""
        if requests is None:
            self._remember_error("requests library not installed.")
            if self.logger:
                self.logger.warning("requests library not installed; skipping TTS voiceover.")
            return None

        endpoint = (self.config.get("azure_openai_endpoint") or "").strip()
        api_key = (self.config.get("azure_openai_key") or "").strip()

        if not endpoint or not api_key:
            self._remember_error("Azure OpenAI TTS credentials are missing.")
            if self.logger:
                self.logger.warning("Azure OpenAI TTS credentials not configured; skipping TTS voiceover.")
            return None

        # Validate endpoint format and provide helpful hints
        if self.logger:
            if 'azure.com' in endpoint.lower():
                if '/audio/speech' not in endpoint:
                    self.logger.warning(
                        "Azure OpenAI endpoint may be incomplete. "
                        "Expected format: https://YOUR_RESOURCE.openai.azure.com/openai/deployments/YOUR_DEPLOYMENT/audio/speech?api-version=2024-02-15-preview"
                    )
            elif 'api.openai.com' in endpoint.lower():
                if endpoint != 'https://api.openai.com/v1/audio/speech':
                    self.logger.warning(
                        "OpenAI endpoint may be incorrect. "
                        "Expected: https://api.openai.com/v1/audio/speech"
                    )

        voice = (self.config.get("azure_openai_voice") or "alloy").strip()
        model = (self.config.get("azure_openai_model") or "tts-1-hd").strip()
        speed = float(self.config.get("azure_openai_speed", 1.0) or 1.0)

        target_rate = self.sample_rate

        try:
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            }
            payload = {
                "model": model,
                "input": text,
                "voice": voice,
                "speed": speed,
                "response_format": "wav",  # Request WAV format
            }

            # Log the request for debugging
            if self.logger:
                self.logger.debug(f"Azure OpenAI TTS request to: {endpoint}")
                self.logger.debug(f"Azure OpenAI TTS payload: model={model}, voice={voice}, speed={speed}")

            response = requests.post(
                endpoint,
                headers=headers,
                json=payload,
                timeout=30,
            )

            # Log response details for debugging
            if self.logger:
                self.logger.debug(f"Azure OpenAI TTS response status: {response.status_code}")
                self.logger.debug(f"Azure OpenAI TTS response content-type: {response.headers.get('content-type', 'unknown')}")
                self.logger.debug(f"Azure OpenAI TTS response size: {len(response.content)} bytes")

            if response.status_code != 200:
                error_msg = f"Azure OpenAI TTS API returned status {response.status_code}"
                try:
                    error_detail = response.json()
                    error_msg += f": {error_detail}"
                except Exception:
                    error_msg += f": {response.text[:200]}"

                self._remember_error(error_msg)
                if self.logger:
                    self.logger.error(error_msg)
                return None

            audio_bytes = response.content

            if not audio_bytes:
                error_msg = "Azure OpenAI TTS returned no audio data."
                # Try to show what we actually got
                try:
                    response_preview = response.text[:500] if response.text else "(empty response)"
                    error_msg += f" Response preview: {response_preview}"
                except Exception:
                    pass

                self._remember_error(error_msg)
                if self.logger:
                    self.logger.error(error_msg)
                return None

            # Check if response looks like audio or an error message
            content_type = response.headers.get('content-type', '')
            if 'json' in content_type.lower() or 'html' in content_type.lower() or 'text' in content_type.lower():
                error_msg = f"Azure OpenAI TTS returned wrong content type: {content_type}. "
                try:
                    error_msg += f"Response: {response.text[:500]}"
                except Exception:
                    pass
                self._remember_error(error_msg)
                if self.logger:
                    self.logger.error(error_msg)
                return None

        except requests.exceptions.RequestException as exc:
            self._remember_error(f"Azure OpenAI TTS request failed: {exc}")
            if self.logger:
                self.logger.error(f"Azure OpenAI TTS request failed: {exc}")
            return None
        except Exception as exc:
            self._remember_error(f"Azure OpenAI TTS synthesis failed: {exc}")
            if self.logger:
                self.logger.error(f"Azure OpenAI TTS synthesis failed: {exc}")
            return None

        try:
            # Parse the WAV audio
            with wave.open(io.BytesIO(audio_bytes), "rb") as wav_data:
                raw_frames = wav_data.readframes(wav_data.getnframes())
                sample_width = wav_data.getsampwidth()
                channels = wav_data.getnchannels()
                source_rate = wav_data.getframerate()

            samples = _normalize_pcm_samples(
                raw_frames,
                sample_width,
                channels,
                source_rate,
                target_rate,
            )
            if self.logger:
                self.logger.info("Appended Azure OpenAI TTS voiceover using voice %s", voice)
            self._remember_error(None)
            return samples
        except Exception as exc:
            self._remember_error(f"Failed to decode Azure OpenAI TTS audio: {exc}")
            if self.logger:
                self.logger.error(f"Failed to decode Azure OpenAI TTS audio: {exc}")
            return None

    def _generate_azure_voiceover(self, text: str) -> Optional[List[int]]:
        if azure_speech is None:
            self._remember_error("Azure Speech SDK not installed.")
            if self.logger:
                self.logger.warning("Azure Speech SDK not installed; skipping TTS voiceover.")
            return None

        key = (self.config.get("azure_speech_key") or "").strip()
        region = (self.config.get("azure_speech_region") or "").strip()
        if not key or not region:
            self._remember_error("Azure Speech credentials are missing.")
            if self.logger:
                self.logger.warning("Azure Speech credentials not configured; skipping TTS voiceover.")
            return None

        voice = (self.config.get("azure_speech_voice") or "en-US-AriaNeural").strip()
        target_rate = self.sample_rate
        desired_source_rate = int(self.config.get("azure_speech_sample_rate", target_rate) or target_rate)

        try:
            speech_config = azure_speech.SpeechConfig(subscription=key, region=region)
            speech_config.speech_synthesis_voice_name = voice
            format_map = {
                16000: azure_speech.SpeechSynthesisOutputFormat.Riff16Khz16BitMonoPcm,
                22050: azure_speech.SpeechSynthesisOutputFormat.Riff22050Hz16BitMonoPcm,
                24000: azure_speech.SpeechSynthesisOutputFormat.Riff24Khz16BitMonoPcm,
                44100: azure_speech.SpeechSynthesisOutputFormat.Riff44100Hz16BitMonoPcm,
            }
            selected_format = format_map.get(
                desired_source_rate,
                azure_speech.SpeechSynthesisOutputFormat.Riff24Khz16BitMonoPcm,
            )
            speech_config.set_speech_synthesis_output_format(selected_format)

            audio_config = azure_speech.audio.AudioOutputConfig(use_default_speaker=False)
            synthesizer = azure_speech.SpeechSynthesizer(
                speech_config=speech_config,
                audio_config=audio_config,
            )
            result = synthesizer.speak_text(text)
        except Exception as exc:  # pragma: no cover - network/service specific
            self._remember_error(f"Azure speech synthesis failed: {exc}")
            if self.logger:
                self.logger.error(f"Azure speech synthesis failed: {exc}")
            return None

        reason = getattr(azure_speech, "ResultReason", None)
        if reason and result.reason != reason.SynthesizingAudioCompleted:
            self._remember_error(f"Azure speech synthesis did not complete: {result.reason}")
            if self.logger:
                self.logger.error(
                    "Azure speech synthesis did not complete successfully: %s",
                    result.reason,
                )
            return None

        audio_bytes = getattr(result, "audio_data", None)
        if not audio_bytes:
            self._remember_error("Azure speech synthesis returned no audio data.")
            if self.logger:
                self.logger.warning("Azure speech synthesis returned no audio data.")
            return None

        try:
            with wave.open(io.BytesIO(audio_bytes), "rb") as wav_data:
                raw_frames = wav_data.readframes(wav_data.getnframes())
                sample_width = wav_data.getsampwidth()
                channels = wav_data.getnchannels()
                source_rate = wav_data.getframerate()

            samples = _normalize_pcm_samples(
                raw_frames,
                sample_width,
                channels,
                source_rate,
                target_rate,
            )
            if self.logger:
                self.logger.info("Appended Azure voiceover using voice %s", voice)
            self._remember_error(None)
            return samples
        except Exception as exc:  # pragma: no cover - audio decoding errors
            self._remember_error(f"Failed to decode Azure speech audio: {exc}")
            if self.logger:
                self.logger.error(f"Failed to decode Azure speech audio: {exc}")
            return None

    def _generate_pyttsx3_voiceover(self, text: str) -> Optional[List[int]]:
        target_rate = self.sample_rate
        voice_preference = (self.config.get("pyttsx3_voice") or "").strip()
        espeak_voice = _espeak_voice_from_preference(voice_preference)

        rate_preference_raw = (self.config.get("pyttsx3_rate") or "").strip()
        rate_preference_value: Optional[int] = None
        if rate_preference_raw:
            try:
                rate_preference_value = int(rate_preference_raw)
            except ValueError:
                if self.logger:
                    self.logger.warning('Invalid pyttsx3 rate "%s"; ignoring.', rate_preference_raw)

        volume_preference_raw = (self.config.get("pyttsx3_volume") or "").strip()
        volume_preference_value: Optional[float] = None
        if volume_preference_raw:
            try:
                volume_preference_value = float(volume_preference_raw)
            except ValueError:
                if self.logger:
                    self.logger.warning('Invalid pyttsx3 volume "%s"; ignoring.', volume_preference_raw)

        def fallback(reason: str) -> Optional[List[int]]:
            samples = self._generate_espeak_cli_fallback(
                text,
                target_rate,
                voice_token=espeak_voice,
                rate_value=rate_preference_value,
                volume_value=volume_preference_value,
                reason=reason,
            )
            if samples is not None and self.logger:
                self.logger.warning('pyttsx3 fallback activated (%s).', reason)
            return samples

        if pyttsx3 is None:
            fallback_samples = fallback("pyttsx3 package missing")
            if fallback_samples is not None:
                return fallback_samples

            self._remember_error("pyttsx3 package is not installed.")
            if self.logger:
                self.logger.warning("pyttsx3 not installed; skipping TTS voiceover.")
            return None

        try:
            engine = pyttsx3.init()
        except Exception as exc:  # pragma: no cover - platform specific
            hint = _pyttsx3_error_hint(exc)
            fallback_samples = fallback("pyttsx3 initialisation failed")
            if fallback_samples is not None:
                return fallback_samples

            if hint:
                self._remember_error(hint)
            else:
                self._remember_error(f"Failed to initialise pyttsx3: {exc}")
            if self.logger:
                self.logger.error(f"Failed to initialise pyttsx3: {exc}")
            return None

        configured_voice_id: Optional[str] = None
        if voice_preference:
            try:
                voices = engine.getProperty("voices") or []
            except Exception:  # pragma: no cover - driver specific failures
                voices = []
            for voice in voices:
                voice_id = getattr(voice, "id", "") or ""
                voice_name = getattr(voice, "name", "") or ""
                if voice_preference.lower() in voice_id.lower() or voice_preference.lower() in voice_name.lower():
                    configured_voice_id = voice_id
                    break
            if configured_voice_id:
                try:
                    engine.setProperty("voice", configured_voice_id)
                except Exception as exc:  # pragma: no cover - driver specific
                    if self.logger:
                        self.logger.warning('Unable to apply pyttsx3 voice %s: %s', configured_voice_id, exc)
                    configured_voice_id = None
            else:
                if self.logger:
                    self.logger.warning(
                        'pyttsx3 voice "%s" not found; using default voice.',
                        voice_preference,
                    )

        if rate_preference_value is not None:
            try:
                engine.setProperty("rate", rate_preference_value)
            except Exception as exc:  # pragma: no cover - driver specific
                if self.logger:
                    self.logger.warning('Unable to apply pyttsx3 rate %s: %s', rate_preference_raw, exc)

        if volume_preference_value is not None:
            try:
                engine.setProperty("volume", volume_preference_value)
            except Exception as exc:  # pragma: no cover - driver specific
                if self.logger:
                    self.logger.warning('Unable to apply pyttsx3 volume %s: %s', volume_preference_raw, exc)

        tmp_path: Optional[str] = None
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as tmp_file:
                tmp_path = tmp_file.name

            engine.save_to_file(text, tmp_path)
            engine.runAndWait()
            try:
                configured_voice_id = engine.getProperty("voice") or configured_voice_id
            except Exception:
                pass
        except Exception as exc:  # pragma: no cover - platform specific
            hint = _pyttsx3_error_hint(exc)
            fallback_samples = fallback("pyttsx3 synthesis failed")
            if fallback_samples is not None:
                return fallback_samples

            if hint:
                self._remember_error(hint)
            else:
                self._remember_error(f"pyttsx3 synthesis failed: {exc}")
            if self.logger:
                self.logger.error(f"pyttsx3 synthesis failed: {exc}")
            if tmp_path and os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass
            return None
        finally:
            try:
                engine.stop()
            except Exception:
                pass

        file_missing = not tmp_path or not os.path.exists(tmp_path)
        file_empty = False
        if not file_missing and tmp_path:
            try:
                file_empty = os.path.getsize(tmp_path) == 0
            except OSError:
                file_empty = True

        if file_missing or file_empty:
            fallback_samples = fallback("pyttsx3 produced no audio file")
            if fallback_samples is not None:
                if tmp_path and os.path.exists(tmp_path):
                    try:
                        os.remove(tmp_path)
                    except OSError:
                        pass
                return fallback_samples

            dependency_hint = _pyttsx3_dependency_hint()
            if dependency_hint:
                self._remember_error(dependency_hint)
            else:
                self._remember_error("pyttsx3 did not produce an audio file.")
            if self.logger:
                self.logger.warning("pyttsx3 did not produce an audio file; skipping voiceover.")
            if tmp_path and os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass
            return None

        try:
            with wave.open(tmp_path, "rb") as wav_data:
                raw_frames = wav_data.readframes(wav_data.getnframes())
                sample_width = wav_data.getsampwidth()
                channels = wav_data.getnchannels()
                source_rate = wav_data.getframerate()

            samples = _normalize_pcm_samples(
                raw_frames,
                sample_width,
                channels,
                source_rate,
                target_rate,
            )
            if self.logger:
                voice_label = configured_voice_id or "default"
                self.logger.info("Appended pyttsx3 voiceover using voice %s", voice_label)
            self._remember_error(None)
            return samples
        except Exception as exc:  # pragma: no cover - audio decoding errors
            hint = _pyttsx3_error_hint(exc)
            fallback_samples = fallback("pyttsx3 audio decode failed")
            if fallback_samples is not None:
                if tmp_path and os.path.exists(tmp_path):
                    try:
                        os.remove(tmp_path)
                    except OSError:
                        pass
                return fallback_samples

            if hint:
                self._remember_error(hint)
            else:
                self._remember_error(f"Failed to decode pyttsx3 audio: {exc}")
            if self.logger:
                self.logger.error(f"Failed to decode pyttsx3 audio: {exc}")
            return None
        finally:
            if tmp_path and os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass

    def _generate_espeak_cli_fallback(
        self,
        text: str,
        target_rate: int,
        *,
        voice_token: Optional[str],
        rate_value: Optional[int],
        volume_value: Optional[float],
        reason: str,
    ) -> Optional[List[int]]:
        """Use the espeak/espeak-ng CLI as a last-resort narration fallback."""

        espeak_cmd = shutil.which("espeak-ng") or shutil.which("espeak")
        if espeak_cmd is None:
            return None

        tmp_path: Optional[str] = None
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as tmp_file:
                tmp_path = tmp_file.name

            command: List[str] = [espeak_cmd, "-w", tmp_path]
            if voice_token:
                command.extend(["-v", voice_token])
            if rate_value is not None:
                espeak_rate = max(80, min(450, rate_value))
                command.extend(["-s", str(espeak_rate)])
            if volume_value is not None:
                normalized_volume = max(0.0, min(1.0, volume_value))
                espeak_volume = max(0, min(200, int(round(normalized_volume * 200))))
                command.extend(["-a", str(espeak_volume)])

            command.append("--stdin")
            completed = subprocess.run(
                command,
                input=text,
                text=True,
                capture_output=True,
                check=False,
            )
            if completed.returncode != 0:
                if self.logger:
                    stderr = (completed.stderr or "").strip()
                    self.logger.error(
                        "espeak fallback failed (%s): %s",
                        reason,
                        stderr or completed.returncode,
                    )
                return None

            with wave.open(tmp_path, "rb") as wav_data:
                raw_frames = wav_data.readframes(wav_data.getnframes())
                sample_width = wav_data.getsampwidth()
                channels = wav_data.getnchannels()
                source_rate = wav_data.getframerate()

            samples = _normalize_pcm_samples(
                raw_frames,
                sample_width,
                channels,
                source_rate,
                target_rate,
            )
            if self.logger:
                voice_label = voice_token or "default"
                self.logger.info(
                    "Appended espeak CLI fallback voiceover using voice %s",
                    voice_label,
                )
            self._remember_error(None)
            return samples
        except FileNotFoundError:
            return None
        except Exception as exc:  # pragma: no cover - CLI fallback errors
            if self.logger:
                self.logger.error("espeak fallback crashed (%s): %s", reason, exc)
            return None
        finally:
            if tmp_path and os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass


__all__ = ["TTSEngine"]
