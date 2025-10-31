"""Decode SAME/EAS headers from audio files containing alert bursts."""

from __future__ import annotations

import math
import os
import shutil
import subprocess
from array import array
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Tuple

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


def _extract_bits(
    samples: List[float], sample_rate: int, bit_rate: float
) -> Tuple[List[int], float, float]:
    """Slice PCM audio into SAME bit periods and detect mark/space symbols."""

    bits: List[int] = []
    bit_confidences: List[float] = []

    bit_rate = float(bit_rate)
    if bit_rate <= 0:
        raise AudioDecodeError("Bit rate must be positive when decoding SAME audio.")

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
    _extract_bits.bit_confidences = list(bit_confidences)  # type: ignore[attr-defined]

    return bits, average_confidence, minimum_confidence


def _bits_to_text(bits: List[int]) -> Dict[str, object]:
    """Convert mark/space bits into ASCII SAME text and headers."""

    characters: List[str] = []
    char_positions: List[int] = []
    error_positions: List[int] = []

    confidences: List[float] = list(getattr(_extract_bits, "bit_confidences", []))
    confidence_threshold = 0.6  # Empirically high enough to isolate real SAME bursts

    i = 0
    while i + 10 <= len(bits):
        if bits[i] != 0:
            i += 1
            continue

        frame_confidence = 0.0
        if i + 10 <= len(confidences):
            frame_confidence = sum(confidences[i:i + 10]) / 10.0
        if frame_confidence < confidence_threshold:
            error_positions.append(i)
            i += 1
            continue

        stop_bit = bits[i + 9]
        if stop_bit != 1:
            error_positions.append(i)
            i += 1
            continue

        data_bits = bits[i + 1 : i + 8]

        value = 0
        for position, bit in enumerate(data_bits):
            value |= (bit & 1) << position

        try:
            character = chr(value)
        except ValueError:
            error_positions.append(i)
            i += 10
            continue

        characters.append(character)
        char_positions.append(i)
        i += 10

    raw_text = "".join(characters)
    trimmed_characters = characters
    trimmed_positions = char_positions

    if raw_text:
        upper_text = raw_text.upper()

        start_index = upper_text.find("ZCZC")
        if start_index > 0:
            trimmed_characters = trimmed_characters[start_index:]
            trimmed_positions = trimmed_positions[start_index:]
            raw_text = "".join(trimmed_characters)
            upper_text = raw_text.upper()

        end_index = upper_text.rfind("NNNN")
        if end_index != -1:
            end_offset = end_index + 4
            if end_offset < len(trimmed_characters) and trimmed_characters[end_offset] == "\r":
                end_offset += 1
            trimmed_characters = trimmed_characters[:end_offset]
            trimmed_positions = trimmed_positions[:end_offset]
            raw_text = "".join(trimmed_characters)
        else:
            last_break = raw_text.rfind("\r")
            if last_break != -1:
                trimmed_characters = trimmed_characters[: last_break + 1]
                trimmed_positions = trimmed_positions[: last_break + 1]
                raw_text = "".join(trimmed_characters)

    headers: List[str] = []
    for segment in raw_text.split("\r"):
        cleaned = segment.strip()
        if not cleaned:
            continue

        upper_segment = cleaned.upper()
        if "ZCZC" not in upper_segment and "NNNN" not in upper_segment:
            continue

        header_start = upper_segment.find("ZCZC")
        if header_start == -1:
            header_start = upper_segment.find("NNNN")

        candidate = cleaned[header_start:]
        if candidate:
            headers.append(candidate)

    valid_frame_count = len(trimmed_characters)

    if headers:
        raw_text = "\r".join(headers) + "\r"

    if trimmed_positions:
        first_bit = trimmed_positions[0]
        last_bit = trimmed_positions[-1]
        relevant_errors = [
            pos for pos in error_positions if first_bit <= pos <= last_bit
        ]
    else:
        relevant_errors = list(error_positions)

    frame_errors = len(relevant_errors)
    frame_count_value = valid_frame_count + frame_errors

    return {
        "text": raw_text,
        "headers": headers,
        "frame_count": frame_count_value,
        "frame_errors": frame_errors,
    }


def _score_candidate(metadata: Dict[str, object]) -> float:
    """Return a quality score for decoded SAME metadata."""

    headers = metadata.get("headers") or []
    text = metadata.get("text") or ""
    frame_count = int(metadata.get("frame_count") or 0)
    frame_errors = int(metadata.get("frame_errors") or 0)

    score = float(frame_count - frame_errors)
    score -= float(frame_errors * 2)

    if headers:
        score += 500.0 * len(headers)
        uppercase_headers = [header.upper() for header in headers]
        score += 200.0 * sum(1 for header in uppercase_headers if header.startswith("ZCZC"))
        score += 100.0 * sum(1 for header in uppercase_headers if header.startswith("NNNN"))

    if isinstance(text, str):
        score += 50.0 * text.upper().count("ZCZC")

    return score


def _decode_with_candidate_rates(
    samples: List[float],
    sample_rate: int,
    *,
    base_rate: float,
) -> Tuple[List[int], Dict[str, object], float, float]:
    """Try decoding SAME bits using a range of baud rates."""

    candidate_offsets = [0.0]
    for step in (0.005, 0.01, 0.015, 0.02, 0.025, 0.03, 0.035, 0.04):
        candidate_offsets.extend((-step, step))

    best_bits: Optional[List[int]] = None
    best_metadata: Optional[Dict[str, object]] = None
    best_average: float = 0.0
    best_minimum: float = 0.0
    best_score: Optional[float] = None
    best_rate: Optional[float] = None

    for offset in candidate_offsets:
        bit_rate = base_rate * (1.0 + offset)
        try:
            bits, average_confidence, minimum_confidence = _extract_bits(
                samples, sample_rate, bit_rate
            )
        except AudioDecodeError:
            continue

        metadata = _bits_to_text(bits)
        score = _score_candidate(metadata)

        if best_score is None or score > best_score + 1e-6:
            best_bits = bits
            best_metadata = metadata
            best_average = average_confidence
            best_minimum = minimum_confidence
            best_score = score
            best_rate = bit_rate
        elif (
            best_score is not None
            and abs(score - best_score) <= 1e-6
            and best_rate is not None
            and abs(bit_rate - base_rate) < abs(best_rate - base_rate)
        ):
            best_bits = bits
            best_metadata = metadata
            best_average = average_confidence
            best_minimum = minimum_confidence
            best_rate = bit_rate

    if best_bits is None or best_metadata is None:
        raise AudioDecodeError("The audio payload did not contain detectable SAME bursts.")

    return best_bits, best_metadata, best_average, best_minimum


def decode_same_audio(path: str, *, sample_rate: int = 44100) -> SAMEAudioDecodeResult:
    """Decode SAME headers from a WAV or MP3 file located at ``path``."""

    if not os.path.exists(path):
        raise AudioDecodeError(f"Audio file does not exist: {path}")

    samples = _read_audio_samples(path, sample_rate)
    base_rate = float(SAME_BAUD)
    bits, metadata, average_confidence, minimum_confidence = _decode_with_candidate_rates(
        samples, sample_rate, base_rate=base_rate
    )

    raw_text = metadata["text"]
    headers: List[SAMEHeaderDetails] = []
    for header in metadata["headers"]:
        headers.append(
            SAMEHeaderDetails(
                header=header,
                fields=describe_same_header(header),
                confidence=average_confidence,
            )
        )

    duration_seconds = len(samples) / float(sample_rate)

    return SAMEAudioDecodeResult(
        raw_text=raw_text,
        headers=headers,
        bit_count=len(bits),
        frame_count=metadata["frame_count"],
        frame_errors=metadata["frame_errors"],
        duration_seconds=duration_seconds,
        sample_rate=sample_rate,
        bit_confidence=average_confidence,
        min_bit_confidence=minimum_confidence,
    )


__all__ = [
    "AudioDecodeError",
    "SAMEAudioDecodeResult",
    "SAMEHeaderDetails",
    "decode_same_audio",
]
