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

"""Fetching and decoding embedded/IPAWS audio into PCM sample buffers."""

import io
import struct
import subprocess
import wave
from typing import Dict, List, Optional, Tuple



#: ECIG §3.5.1 — recorded-audio download timeout cap (2 minutes).
EMBEDDED_AUDIO_DOWNLOAD_TIMEOUT = 120



#: ECIG §3.5.1 — streaming-audio fetch timeout cap (30 seconds).
EMBEDDED_AUDIO_STREAMING_TIMEOUT = 30




def _fetch_embedded_audio(
    resources: List[Dict[str, str]],
    target_sample_rate: int,
    logger,
    timeout: Optional[int] = None,
) -> Tuple[Optional[List[int]], Optional[str]]:
    """Fetch and convert embedded audio from CAP resources.

    IPAWS alerts can contain pre-recorded audio in <resource> elements.
    Audio may be provided as an external URL (``uri``) to download or as
    inline base64-encoded content (``derefUri``).  Both cases are handled.
    When a resource carries ``derefUri`` but no ``mimeType`` the format is
    inferred from the decoded bytes so that alerts that omit MIME metadata
    still produce valid audio.

    ECIG §3.5.1 caps per-resource fetch time at 2 minutes for downloads and
    30 seconds for streaming sources; on timeout the caller falls back to
    TTS for that alert.

    Args:
        resources: List of resource dicts from CAP XML parsing
        target_sample_rate: Target sample rate for output
        logger: Logger instance
        timeout: Optional override for the per-resource timeout (seconds).
            When ``None`` the spec-mandated cap is selected per resource
            (streaming → 30 s, otherwise → 120 s).

    Returns:
        Tuple of (audio_samples, source_description) or (None, None) if no
        usable audio resource was found.
    """
    import base64
    import binascii
    import requests

    # Collect candidate audio resources.
    # A resource is a candidate when:
    #  - its mimeType or resourceDesc explicitly indicates audio, OR
    #  - it carries a derefUri with no conflicting (non-audio) MIME type.
    # Resources that advertise a non-audio MIME type are excluded even if
    # they have a derefUri, to avoid treating e.g. image attachments as audio.
    audio_resources = []
    for resource in resources:
        mime_type = (resource.get('mimeType') or '').lower()
        resource_desc = (resource.get('resourceDesc') or '').lower()
        uri = resource.get('uri', '')
        deref_uri = resource.get('derefUri', '')

        has_audio_hint = (
            'audio' in mime_type or
            'eas broadcast' in resource_desc or
            uri.endswith(('.mp3', '.wav', '.ogg', '.m4a'))
        )
        # A MIME type present but NOT containing 'audio' is a conflict.
        has_non_audio_mime = bool(mime_type) and 'audio' not in mime_type

        has_content = bool(uri) or bool(deref_uri)
        is_candidate = has_content and (has_audio_hint or (bool(deref_uri) and not has_non_audio_mime))

        if is_candidate:
            audio_resources.append(resource)

    if not audio_resources:
        return None, None

    # Try each candidate until one produces valid PCM samples.
    # Prefer inline derefUri (already available locally) over downloading.
    for resource in audio_resources:
        uri = resource.get('uri', '')
        deref_uri = resource.get('derefUri', '')
        mime_type = resource.get('mimeType', '')
        resource_desc = resource.get('resourceDesc', '')

        # --- inline base64 audio ---
        if deref_uri:
            logger.info(
                f"Decoding inline IPAWS audio: {resource_desc or 'unnamed'} "
                f"({mime_type or 'auto-detect'}, {len(deref_uri)} base64 chars)"
            )
            try:
                audio_data = base64.b64decode(deref_uri, validate=False)
                logger.info(f"Decoded {len(audio_data)} bytes of inline IPAWS audio")

                samples = _convert_audio_to_samples(audio_data, mime_type, target_sample_rate, logger)
                if samples:
                    logger.info(
                        f"Successfully converted inline IPAWS audio: {len(samples)} samples "
                        f"({len(samples) / target_sample_rate:.1f}s at {target_sample_rate}Hz)"
                    )
                    return samples, f"derefUri:{resource_desc or 'inline'}"
                else:
                    logger.warning("Failed to convert inline IPAWS audio; will try URI if available")
            except (binascii.Error, ValueError) as exc:
                logger.warning(f"Failed to base64-decode inline IPAWS audio: {exc}")
            except Exception as exc:
                logger.error(f"Error processing inline IPAWS audio: {exc}")

        # --- external URI audio ---
        if uri:
            # ECIG §3.5.1: streaming sources are capped at 30 s, downloadable
            # MP3/WAV at 120 s; on timeout the loop continues to the next
            # resource and ultimately falls back to TTS for the alert.
            mime_lower = mime_type.lower() if mime_type else ''
            desc_lower = resource_desc.lower() if resource_desc else ''
            is_streaming = ('streaming' in mime_lower) or ('streaming' in desc_lower)
            if timeout is not None:
                per_resource_timeout = timeout
            elif is_streaming:
                per_resource_timeout = EMBEDDED_AUDIO_STREAMING_TIMEOUT
            else:
                per_resource_timeout = EMBEDDED_AUDIO_DOWNLOAD_TIMEOUT
            logger.info(
                f"Fetching embedded audio from IPAWS: {resource_desc or 'unnamed'} "
                f"({mime_type}) from {uri[:80]}... "
                f"[timeout={per_resource_timeout}s, "
                f"{'streaming' if is_streaming else 'download'}]"
            )
            try:
                # Disable proxy to allow direct download from IPAWS
                response = requests.get(uri, timeout=per_resource_timeout, stream=True, proxies={'http': None, 'https': None})
                response.raise_for_status()

                audio_data = response.content
                logger.info(f"Downloaded {len(audio_data)} bytes of audio from IPAWS")

                samples = _convert_audio_to_samples(audio_data, mime_type, target_sample_rate, logger)
                if samples:
                    logger.info(
                        f"Successfully converted IPAWS audio: {len(samples)} samples "
                        f"({len(samples) / target_sample_rate:.1f}s at {target_sample_rate}Hz)"
                    )
                    return samples, uri
                else:
                    logger.warning(f"Failed to convert audio from {uri}")

            except requests.exceptions.Timeout:
                logger.warning(f"Timeout fetching audio from {uri}")
            except requests.exceptions.RequestException as exc:
                logger.warning(f"Failed to fetch audio from {uri}: {exc}")
            except Exception as exc:
                logger.error(f"Error processing audio from {uri}: {exc}")

    return None, None




def _convert_audio_to_samples(
    audio_data: bytes,
    mime_type: str,
    target_sample_rate: int,
    logger,
) -> Optional[List[int]]:
    """Convert audio bytes to PCM samples at target sample rate.
    
    Supports WAV, MP3 (via pydub if available), and other formats.
    """
    mime_lower = mime_type.lower()
    
    # Try WAV first
    if 'wav' in mime_lower or audio_data[:4] == b'RIFF':
        try:
            with io.BytesIO(audio_data) as audio_io:
                with wave.open(audio_io, 'rb') as wav:
                    channels = wav.getnchannels()
                    sample_width = wav.getsampwidth()
                    frame_rate = wav.getframerate()
                    frames = wav.readframes(wav.getnframes())
                    
                    # Convert to mono if stereo
                    if channels == 2:
                        if sample_width == 2:
                            samples = struct.unpack(f'<{len(frames)//2}h', frames)
                            mono_samples = [(samples[i] + samples[i+1]) // 2 
                                          for i in range(0, len(samples), 2)]
                        else:
                            mono_samples = list(frames[::2])
                    else:
                        if sample_width == 2:
                            mono_samples = list(struct.unpack(f'<{len(frames)//2}h', frames))
                        elif sample_width == 1:
                            mono_samples = [(b - 128) * 256 for b in frames]
                        else:
                            logger.warning(f"Unsupported WAV sample width: {sample_width}")
                            return None
                    
                    # Resample if needed
                    if frame_rate != target_sample_rate:
                        mono_samples = _resample_audio(mono_samples, frame_rate, target_sample_rate)
                    
                    return mono_samples
        except Exception as e:
            logger.warning(f"Failed to parse WAV audio: {e}")
    
    # MPEG audio frame sync: first byte 0xFF, second byte high-nibble 0xE or 0xF
    # This covers MPEG-1/2/2.5 Layers 1-3 (e.g. 0xFB=MPEG1-L3, 0xF3=MPEG2-L3, 0xE2=MPEG2.5-L3)
    _is_mpeg_sync = len(audio_data) >= 2 and audio_data[0] == 0xFF and (audio_data[1] & 0xE0) == 0xE0
    if 'mp3' in mime_lower or 'mpeg' in mime_lower or audio_data[:3] == b'ID3' or _is_mpeg_sync:
        # Try pydub first (no subprocess overhead)
        try:
            from pydub import AudioSegment

            audio_io = io.BytesIO(audio_data)
            audio = AudioSegment.from_mp3(audio_io)

            # Convert to mono
            audio = audio.set_channels(1)

            # Resample to target rate
            audio = audio.set_frame_rate(target_sample_rate)

            # Get raw samples
            raw_data = audio.raw_data
            samples = list(struct.unpack(f'<{len(raw_data)//2}h', raw_data))

            return samples

        except ImportError:
            logger.warning("pydub not available for MP3 conversion; trying ffmpeg directly")
        except Exception as e:
            logger.warning(f"pydub MP3 conversion failed ({e}); trying ffmpeg directly")

        # Fallback: pipe raw MP3 bytes into ffmpeg and get back s16le PCM
        try:
            import shutil
            if shutil.which("ffmpeg"):
                result = subprocess.run(
                    [
                        "ffmpeg", "-hide_banner", "-loglevel", "error",
                        "-i", "pipe:0",
                        "-ar", str(target_sample_rate),
                        "-ac", "1",
                        "-f", "s16le",
                        "pipe:1",
                    ],
                    input=audio_data,
                    capture_output=True,
                    timeout=30,
                )
                if result.returncode == 0 and result.stdout:
                    samples = list(struct.unpack(f'<{len(result.stdout)//2}h', result.stdout))
                    logger.info(f"Converted MP3 via ffmpeg subprocess: {len(samples)} samples")
                    return samples
                else:
                    stderr = result.stderr.decode("utf-8", "ignore").strip()
                    logger.warning(f"ffmpeg MP3 decode failed: {stderr}")
            else:
                logger.warning("ffmpeg not found; cannot decode MP3 audio for TTS narration")
        except Exception as e:
            logger.warning(f"ffmpeg MP3 fallback failed: {e}")

    # Last-resort: try pydub auto-format detection for any unrecognised format
    if mime_type == '' or ('audio' in mime_lower and not any(k in mime_lower for k in ('wav', 'mp3', 'mpeg'))):
        try:
            from pydub import AudioSegment

            audio_io = io.BytesIO(audio_data)
            audio = AudioSegment.from_file(audio_io)
            audio = audio.set_channels(1)
            audio = audio.set_frame_rate(target_sample_rate)
            raw_data = audio.raw_data
            samples = list(struct.unpack(f'<{len(raw_data)//2}h', raw_data))
            logger.info("Converted audio via pydub auto-detection")
            return samples
        except ImportError:
            pass
        except Exception as e:
            logger.warning(f"pydub auto-detection failed: {e}")

    logger.warning(f"Unsupported audio format: {mime_type}")
    return None




def _resample_audio(samples: List[int], source_rate: int, target_rate: int) -> List[int]:
    """Simple linear interpolation resampling."""
    if source_rate == target_rate:
        return samples
    
    ratio = target_rate / source_rate
    new_length = int(len(samples) * ratio)
    
    if new_length < 1:
        return samples
    
    result = []
    for i in range(new_length):
        src_idx = i / ratio
        idx_low = int(src_idx)
        idx_high = min(idx_low + 1, len(samples) - 1)
        frac = src_idx - idx_low
        
        value = int(samples[idx_low] * (1 - frac) + samples[idx_high] * frac)
        result.append(value)
    
    return result




def convert_audio_to_samples(
    audio_data: bytes,
    mime_type: str,
    target_sample_rate: int,
    logger,
) -> Optional[List[int]]:
    """Public wrapper for audio conversion. See :func:`_convert_audio_to_samples`."""
    return _convert_audio_to_samples(audio_data, mime_type, target_sample_rate, logger)
