"""Decode SAME/EAS headers from audio files containing alert bursts."""

from __future__ import annotations

import math
import os
import shutil
import subprocess
from array import array
from dataclasses import dataclass, field
from typing import Dict, Iterable, List

from .eas import describe_same_header
from .eas_fsk import SAME_BAUD, SAME_MARK_FREQ, SAME_SPACE_FREQ


class AudioDecodeError(RuntimeError):
    """Raised when an audio payload cannot be decoded into SAME headers."""


@dataclass
class SAMEHeaderDetails:
    """Represents a decoded SAME header and the derived metadata."""

    header: str
    fields: Dict[str, object] = field(default_factory=dict)
    confidence: float = 0.0

    def to_dict(self) -> Dict[str, object]:
        return {
            "header": self.header,
            "fields": dict(self.fields),
            "confidence": float(self.confidence),
        }


@dataclass
class SAMEAudioDecodeResult:
    """Container holding the outcome of decoding an audio payload."""

    raw_text: str
    headers: List[SAMEHeaderDetails]
    bit_count: int
    frame_count: int
    frame_errors: int
    duration_seconds: float
    sample_rate: int
    bit_confidence: float
    min_bit_confidence: float

    def to_dict(self) -> Dict[str, object]:
        return {
            "raw_text": self.raw_text,
            "headers": [header.to_dict() for header in self.headers],
            "bit_count": self.bit_count,
            "frame_count": self.frame_count,
            "frame_errors": self.frame_errors,
            "duration_seconds": self.duration_seconds,
            "sample_rate": self.sample_rate,
            "bit_confidence": self.bit_confidence,
            "min_bit_confidence": self.min_bit_confidence,
        }


def _run_ffmpeg_decode(path: str, sample_rate: int) -> bytes:
    """Invoke ffmpeg to normalise an audio file to mono PCM samples."""

    if not shutil.which("ffmpeg"):
        raise AudioDecodeError(
            "ffmpeg is required to decode audio files. Install ffmpeg and try again."
        )

    command = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        path,
        "-ar",
        str(sample_rate),
        "-ac",
        "1",
        "-f",
        "s16le",
        "-",
    ]

    try:
        result = subprocess.run(
            command,
            capture_output=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:  # pragma: no cover - subprocess
        detail = exc.stderr.decode("utf-8", "ignore") if hasattr(exc, "stderr") else ""
        raise AudioDecodeError(
            f"Unable to decode audio with ffmpeg: {exc}" + (f" ({detail.strip()})" if detail else "")
        ) from exc

    if not result.stdout:
        raise AudioDecodeError("ffmpeg produced no audio samples for decoding.")

    return bytes(result.stdout)


def _read_audio_samples(path: str, sample_rate: int) -> List[float]:
    """Return normalised PCM samples from an arbitrary audio file."""

    try:
        import wave

        with wave.open(path, "rb") as handle:
            params = handle.getparams()
            if params.nchannels == 1 and params.sampwidth == 2 and params.framerate == sample_rate:
                pcm = handle.readframes(params.nframes)
                if pcm:
                    return _convert_pcm_to_floats(pcm)
    except Exception:
        pass

    pcm_bytes = _run_ffmpeg_decode(path, sample_rate)
    return _convert_pcm_to_floats(pcm_bytes)


def _convert_pcm_to_floats(payload: bytes) -> List[float]:
    """Convert 16-bit little-endian PCM bytes into a list of floats."""

    pcm = array("h")
    pcm.frombytes(payload)
    if not pcm:
        raise AudioDecodeError("Audio payload contained no PCM samples to decode.")

    scale = 1.0 / 32768.0
    return [sample * scale for sample in pcm]


def _goertzel(samples: Iterable[float], sample_rate: int, target_freq: float) -> float:
    """Compute the Goertzel power for ``target_freq`` within ``samples``."""

    coeff = 2.0 * math.cos(2.0 * math.pi * target_freq / sample_rate)
    s_prev = 0.0
    s_prev2 = 0.0
    for sample in samples:
        s = sample + coeff * s_prev - s_prev2
        s_prev2 = s_prev
        s_prev = s
    power = s_prev2 ** 2 + s_prev ** 2 - coeff * s_prev * s_prev2
    return power if power > 0.0 else 0.0


def _extract_bits(samples: List[float], sample_rate: int) -> List[int]:
    """Slice PCM audio into SAME bit periods and detect mark/space symbols."""

    bits: List[int] = []
    bit_confidences: List[float] = []

    bit_rate = float(SAME_BAUD)
    samples_per_bit = sample_rate / bit_rate
    carry = 0.0
    index = 0

    while index < len(samples):
        total = samples_per_bit + carry
        chunk_length = int(total)
        if chunk_length <= 0:
            chunk_length = 1
        carry = total - chunk_length
        end = index + chunk_length
        if end > len(samples):
            break

        chunk = samples[index:end]
        mark_power = _goertzel(chunk, sample_rate, SAME_MARK_FREQ)
        space_power = _goertzel(chunk, sample_rate, SAME_SPACE_FREQ)
        bit = 1 if mark_power >= space_power else 0
        bits.append(bit)

        if mark_power + space_power > 0:
            confidence = abs(mark_power - space_power) / (mark_power + space_power)
        else:
            confidence = 0.0
        bit_confidences.append(confidence)

        index = end

    if not bits:
        raise AudioDecodeError("The audio payload did not contain detectable SAME bursts.")

    average_confidence = sum(bit_confidences) / len(bit_confidences)
    minimum_confidence = min(bit_confidences) if bit_confidences else 0.0
    _extract_bits.last_confidence = average_confidence  # type: ignore[attr-defined]
    _extract_bits.min_confidence = minimum_confidence  # type: ignore[attr-defined]

    return bits


def _bits_to_text(bits: List[int]) -> Dict[str, object]:
    """Convert mark/space bits into ASCII SAME text and headers."""

    characters: List[str] = []
    frame_errors = 0
    frame_count = 0

    i = 0
    while i + 10 <= len(bits):
        frame_count += 1
        start_bit = bits[i]
        if start_bit != 0:
            i += 1
            continue

        data_bits = bits[i + 1 : i + 8]
        parity_or_unused = bits[i + 8]
        stop_bit = bits[i + 9]

        if stop_bit != 1:
            frame_errors += 1
            i += 1
            continue

        value = 0
        for position, bit in enumerate(data_bits):
            value |= (bit & 1) << position

        if parity_or_unused not in (0, 1):
            frame_errors += 1

        try:
            character = chr(value)
        except ValueError:
            frame_errors += 1
            i += 10
            continue

        characters.append(character)
        i += 10

    raw_text = "".join(characters)

    headers: List[str] = []
    for segment in raw_text.split("\r"):
        cleaned = segment.strip()
        if not cleaned:
            continue
        if cleaned.upper().startswith("ZCZC") or cleaned.upper().startswith("NNNN"):
            headers.append(cleaned)

    return {
        "text": raw_text,
        "headers": headers,
        "frame_count": frame_count,
        "frame_errors": frame_errors,
    }


def decode_same_audio(path: str, *, sample_rate: int = 44100) -> SAMEAudioDecodeResult:
    """Decode SAME headers from a WAV or MP3 file located at ``path``."""

    if not os.path.exists(path):
        raise AudioDecodeError(f"Audio file does not exist: {path}")

    samples = _read_audio_samples(path, sample_rate)
    bits = _extract_bits(samples, sample_rate)
    metadata = _bits_to_text(bits)

    raw_text = metadata["text"]
    headers: List[SAMEHeaderDetails] = []
    for header in metadata["headers"]:
        headers.append(
            SAMEHeaderDetails(
                header=header,
                fields=describe_same_header(header),
                confidence=float(getattr(_extract_bits, "last_confidence", 0.0)),
            )
        )

    duration_seconds = len(samples) / float(sample_rate)
    average_confidence = float(getattr(_extract_bits, "last_confidence", 0.0))
    min_confidence = float(getattr(_extract_bits, "min_confidence", 0.0))

    return SAMEAudioDecodeResult(
        raw_text=raw_text,
        headers=headers,
        bit_count=len(bits),
        frame_count=metadata["frame_count"],
        frame_errors=metadata["frame_errors"],
        duration_seconds=duration_seconds,
        sample_rate=sample_rate,
        bit_confidence=average_confidence,
        min_bit_confidence=min_confidence,
    )


__all__ = [
    "AudioDecodeError",
    "SAMEAudioDecodeResult",
    "SAMEHeaderDetails",
    "decode_same_audio",
]
