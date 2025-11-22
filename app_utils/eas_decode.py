"""
EAS Station - Emergency Alert System
Copyright (c) 2025 Timothy Kramer (KR8MER)

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

from __future__ import annotations

"""Decode SAME/EAS headers from audio files containing alert bursts."""

import io
import math
import os
import shutil
import subprocess
import wave
from datetime import datetime, timedelta, timezone
from array import array
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from .eas import ORIGINATOR_DESCRIPTIONS, decode_county_originator, describe_same_header
from .eas_fsk import SAME_BAUD, SAME_MARK_FREQ, SAME_SPACE_FREQ, encode_same_bits
from .fips_codes import get_same_lookup
from app_utils.event_codes import EVENT_CODE_REGISTRY


class AudioDecodeError(RuntimeError):
    """Raised when an audio payload cannot be decoded into SAME headers."""


@dataclass
class SAMEHeaderDetails:
    """Represents a decoded SAME header and the derived metadata."""

    header: str
    fields: Dict[str, object] = field(default_factory=dict)
    confidence: float = 0.0
    summary: Optional[str] = None

    def to_dict(self) -> Dict[str, object]:
        payload = {
            "header": self.header,
            "fields": dict(self.fields),
            "confidence": float(self.confidence),
        }
        if self.summary:
            payload["summary"] = self.summary
        return payload


def _select_article(phrase: str) -> str:
    cleaned = (phrase or "").strip().lower()
    if not cleaned:
        return "A"
    return "An" if cleaned[0] in {"a", "e", "i", "o", "u"} else "A"


def _parse_issue_datetime(fields: Dict[str, object]) -> Optional[datetime]:
    value = fields.get("issue_time_iso") if isinstance(fields, dict) else None
    if isinstance(value, str) and value:
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            if value.endswith("Z"):
                try:
                    return datetime.fromisoformat(value[:-1] + "+00:00")
                except ValueError:
                    pass

    components = fields.get("issue_components") if isinstance(fields, dict) else None
    if isinstance(components, dict):
        try:
            ordinal = int(components.get("day_of_year"))
            hour = int(components.get("hour", 0))
            minute = int(components.get("minute", 0))
        except (TypeError, ValueError):
            return None

        base_year = datetime.now(timezone.utc).year
        try:
            return datetime(base_year, 1, 1, tzinfo=timezone.utc) + timedelta(
                days=ordinal - 1,
                hours=hour,
                minutes=minute,
            )
        except ValueError:
            return None

    return None


def _format_clock(value: datetime) -> str:
    formatted = value.strftime("%I:%M %p")
    return formatted.lstrip("0") if formatted else ""


def _format_date(value: datetime) -> str:
    month = value.strftime("%b").upper()
    return f"{month} {value.day}, {value.year}"


def _build_locations_list(fields: Dict[str, object]) -> List[str]:
    locations = []
    raw_locations = fields.get("locations") if isinstance(fields, dict) else None
    if not isinstance(raw_locations, list):
        return locations

    for item in raw_locations:
        if not isinstance(item, dict):
            continue

        description = (item.get("description") or "").strip()
        state_abbr = (item.get("state_abbr") or "").strip()
        state_name = (item.get("state_name") or "").strip()
        code = (item.get("code") or "").strip()

        if description:
            label = description
        elif state_name:
            label = state_name
        elif state_abbr:
            label = state_abbr
        else:
            label = code

        label = (label or "").strip()
        if label:
            locations.append(label)

    return locations


def _clean_originator_label(fields: Dict[str, object]) -> str:
    description = (fields.get("originator_description") or "").strip()
    if description:
        if "/" in description:
            description = description.split("/", 1)[0].strip()
        return description

    code = (fields.get("originator") or "").strip()
    if code:
        # Try to decode county-based originator first
        county_desc = decode_county_originator(code)
        if county_desc:
            return county_desc

        # Fall back to standard originator descriptions
        mapping = ORIGINATOR_DESCRIPTIONS.get(code)
        if mapping:
            if "/" in mapping:
                return mapping.split("/", 1)[0].strip()
            return mapping
        return f"originator {code}"

    return "the originator"


def _format_event_phrase(fields: Dict[str, object]) -> str:
    code = (fields.get("event_code") or "").strip().upper()
    entry = EVENT_CODE_REGISTRY.get(code)

    if entry:
        event_name = (entry.get("name") or code or "").strip()
        if not event_name:
            return "an alert"
        article = _select_article(event_name)
        return f"{article} {event_name.upper()}"

    if code:
        return f"an alert with event code {code}"

    return "an alert"


def build_plain_language_summary(header: str, fields: Dict[str, object]) -> Optional[str]:
    if not header:
        return None

    originator_label = _clean_originator_label(fields).strip()
    if not originator_label:
        originator_phrase = "The originator"
    else:
        lower_label = originator_label.lower()
        if lower_label.startswith(("the ", "national", "state", "department", "city", "county", "emergency")):
            if lower_label.startswith("the "):
                originator_phrase = originator_label[0].upper() + originator_label[1:]
            else:
                originator_phrase = f"The {originator_label}"
        else:
            originator_article = _select_article(originator_label)
            originator_phrase = f"{originator_article} {originator_label}"

    event_phrase = _format_event_phrase(fields)

    summary = f"{originator_phrase} has issued {event_phrase}"

    locations = _build_locations_list(fields)
    if locations:
        summary += f" for the following counties/areas: {'; '.join(locations)};"
    else:
        summary += " for the specified area"

    issue_dt = _parse_issue_datetime(fields)
    if issue_dt:
        issue_dt = issue_dt.astimezone(timezone.utc)
        summary += f" at {_format_clock(issue_dt)} on {_format_date(issue_dt)}"

    if summary.endswith(";") and not issue_dt:
        summary = summary[:-1] + "."
    elif not issue_dt and not summary.endswith("."):
        summary += "."

    purge_minutes = fields.get("purge_minutes")
    if isinstance(purge_minutes, (int, float)) and purge_minutes > 0 and issue_dt:
        try:
            expire_dt = issue_dt + timedelta(minutes=float(purge_minutes))
            expire_dt = expire_dt.astimezone(timezone.utc)
            expiry_phrase = _format_clock(expire_dt)
            if expire_dt.date() != issue_dt.date():
                expiry_phrase += f" on {_format_date(expire_dt)}"
            summary += f" Effective until {expiry_phrase}."
        except Exception:
            pass
    elif isinstance(purge_minutes, (int, float)) and purge_minutes == 0:
        summary += " Effective immediately."
    elif not summary.endswith("."):
        summary += "."

    station = (fields.get("station_identifier") or "").strip()
    if station:
        summary += f" Message from {station}."

    return summary


@dataclass
class SAMEAudioSegment:
    """Represents an extracted audio segment from a decoded SAME payload."""

    label: str
    start_sample: int
    end_sample: int
    sample_rate: int
    wav_bytes: bytes = field(repr=False)

    @property
    def duration_seconds(self) -> float:
        return max(0.0, (self.end_sample - self.start_sample) / float(self.sample_rate))

    @property
    def start_seconds(self) -> float:
        return self.start_sample / float(self.sample_rate)

    @property
    def end_seconds(self) -> float:
        return self.end_sample / float(self.sample_rate)

    @property
    def byte_length(self) -> int:
        return len(self.wav_bytes)

    def to_metadata(self) -> Dict[str, object]:
        return {
            "label": self.label,
            "start_sample": self.start_sample,
            "end_sample": self.end_sample,
            "sample_rate": self.sample_rate,
            "start_seconds": self.start_seconds,
            "end_seconds": self.end_seconds,
            "duration_seconds": self.duration_seconds,
            "byte_length": self.byte_length,
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
    segments: Dict[str, SAMEAudioSegment] = field(default_factory=OrderedDict)

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
            "segments": {
                name: segment.to_metadata() for name, segment in self.segments.items()
            },
        }

    @property
    def segment_metadata(self) -> Dict[str, Dict[str, object]]:
        return {
            name: segment.to_metadata() for name, segment in self.segments.items()
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


def _resample_with_scipy(samples: List[float], orig_rate: int, target_rate: int) -> List[float]:
    """Resample audio using scipy when ffmpeg is unavailable."""
    try:
        from scipy import signal
        import numpy as np

        # Convert to numpy array
        samples_array = np.array(samples, dtype=np.float32)

        # Calculate the number of output samples
        num_samples = int(len(samples_array) * target_rate / orig_rate)

        # Resample using scipy
        resampled = signal.resample(samples_array, num_samples)

        return resampled.tolist()
    except ImportError:
        raise AudioDecodeError(
            "Neither ffmpeg nor scipy is available for audio resampling. "
            "Install ffmpeg or run: pip install scipy"
        )


def _read_audio_samples(path: str, sample_rate: int) -> Tuple[List[float], bytes]:
    """Return normalised PCM samples and raw PCM bytes from an audio file."""

    try:
        with wave.open(path, "rb") as handle:
            params = handle.getparams()
            native_rate = params.framerate

            if params.nchannels == 1 and params.sampwidth == 2:
                pcm = handle.readframes(params.nframes)
                if pcm:
                    samples = _convert_pcm_to_floats(pcm)
                    if native_rate == sample_rate:
                        return samples, pcm

                    try:
                        resampled = _resample_with_scipy(samples, native_rate, sample_rate)
                        return resampled, _floats_to_pcm_bytes(resampled)
                    except (ImportError, AudioDecodeError):
                        pass
    except Exception:
        pass

    pcm_bytes = _run_ffmpeg_decode(path, sample_rate)
    return _convert_pcm_to_floats(pcm_bytes), pcm_bytes


def _floats_to_pcm_bytes(samples: Sequence[float]) -> bytes:
    """Convert floating point samples in range [-1, 1) back to PCM bytes."""

    pcm = array("h")
    for sample in samples:
        clamped = max(-1.0, min(1.0, float(sample)))
        pcm.append(int(clamped * 32767.0))
    return pcm.tobytes()


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


def _generate_correlation_tables(sample_rate: int, corr_len: int) -> Tuple[List[float], List[float], List[float], List[float]]:
    """Generate correlation tables for mark and space frequencies (multimon-ng style)."""

    mark_i = []
    mark_q = []
    space_i = []
    space_q = []

    # Generate mark frequency correlation table (2083.3 Hz)
    phase = 0.0
    for i in range(corr_len):
        mark_i.append(math.cos(phase))
        mark_q.append(math.sin(phase))
        phase += 2.0 * math.pi * SAME_MARK_FREQ / sample_rate

    # Generate space frequency correlation table (1562.5 Hz)
    phase = 0.0
    for i in range(corr_len):
        space_i.append(math.cos(phase))
        space_q.append(math.sin(phase))
        phase += 2.0 * math.pi * SAME_SPACE_FREQ / sample_rate

    return mark_i, mark_q, space_i, space_q


def _correlate_and_decode_with_dll(samples: List[float], sample_rate: int) -> Tuple[List[str], float]:
    """
    Decode SAME messages using correlation and DLL timing recovery (multimon-ng algorithm).

    Improved version with better noise handling and error correction.

    Returns tuple of (decoded_messages, confidence)
    """

    # Constants based on multimon-ng with improvements
    SUBSAMP = 2  # Downsampling factor
    PREAMBLE_BYTE = 0xAB  # Preamble pattern
    DLL_GAIN = 0.4  # Reduced from 0.5 for more stable timing recovery
    INTEGRATOR_MAX = 12  # Increased from 10 for better noise immunity
    MAX_MSG_LEN = 268  # Maximum message length

    baud_rate = float(SAME_BAUD)
    corr_len = int(sample_rate / baud_rate)  # Samples per bit period

    # Generate correlation tables
    mark_i, mark_q, space_i, space_q = _generate_correlation_tables(sample_rate, corr_len)

    # State variables
    dcd_shreg = 0  # Shift register for bit history
    dcd_integrator = 0  # Integrator for noise immunity
    sphase = 1  # Sampling phase (16-bit fixed point)
    lasts = 0  # Last 8 bits received
    byte_counter = 0  # Bits received in current byte
    synced = False  # Whether we've found preamble

    # Message storage
    messages: List[str] = []
    current_msg = []
    in_message = False

    # Phase increment per sample
    sphaseinc = int(0x10000 * baud_rate * SUBSAMP / sample_rate)

    # Process samples with subsampling
    idx = 0
    bit_confidences: List[float] = []

    while idx + corr_len < len(samples):
        # Compute correlation (mark - space)
        mark_i_corr = sum(samples[idx + i] * mark_i[i] for i in range(corr_len))
        mark_q_corr = sum(samples[idx + i] * mark_q[i] for i in range(corr_len))
        space_i_corr = sum(samples[idx + i] * space_i[i] for i in range(corr_len))
        space_q_corr = sum(samples[idx + i] * space_q[i] for i in range(corr_len))

        mark_power = mark_i_corr**2 + mark_q_corr**2
        space_power = space_i_corr**2 + space_q_corr**2
        correlation = mark_power - space_power
        total_power = mark_power + space_power

        # Update DCD shift register
        dcd_shreg = (dcd_shreg << 1) & 0xFFFFFFFF
        if correlation > 0:
            dcd_shreg |= 1

        # Update integrator
        if correlation > 0 and dcd_integrator < INTEGRATOR_MAX:
            dcd_integrator += 1
        elif correlation < 0 and dcd_integrator > -INTEGRATOR_MAX:
            dcd_integrator -= 1

        # DLL: Check for bit transitions and adjust timing
        if (dcd_shreg ^ (dcd_shreg >> 1)) & 1:
            if sphase < 0x8000:
                if sphase > sphaseinc // 2:
                    adjustment = min(int(sphase * DLL_GAIN), 8192)
                    sphase -= adjustment
            else:
                if sphase < 0x10000 - sphaseinc // 2:
                    adjustment = min(int((0x10000 - sphase) * DLL_GAIN), 8192)
                    sphase += adjustment

        # Advance sampling phase
        sphase += sphaseinc

        # End of bit period?
        if sphase >= 0x10000:
            sphase = 1
            lasts = (lasts >> 1) & 0x7F

            # Make bit decision based on integrator
            if dcd_integrator >= 0:
                lasts |= 0x80

            curbit = (lasts >> 7) & 1

            # Estimate confidence for this bit using correlation energy
            if synced or in_message:
                if total_power > 0:
                    bit_confidence = min(abs(correlation) / total_power, 1.0)
                else:
                    bit_confidence = 0.0
                bit_confidences.append(bit_confidence)

            # Check for preamble sync
            if (lasts & 0xFF) == PREAMBLE_BYTE and not in_message:
                synced = True
                byte_counter = 0
            elif synced:
                byte_counter += 1
                if byte_counter == 8:
                    # Got a complete byte
                    byte_val = lasts & 0xFF

                    # Check if it's a valid ASCII character
                    if 32 <= byte_val <= 126 or byte_val in (10, 13):
                        char = chr(byte_val)

                        if not in_message and char == 'Z':
                            # Possible start of ZCZC
                            in_message = True
                            current_msg = [char]
                        elif in_message:
                            current_msg.append(char)

                            # Check for end of message
                            msg_text = ''.join(current_msg)
                            if char == '\r' or char == '\n':
                                # Carriage return or line feed terminates message
                                if 'ZCZC' in msg_text or 'NNNN' in msg_text:
                                    # Clean up the message - include trailing dash
                                    if '-' in msg_text:
                                        msg_text = msg_text[:msg_text.rfind('-')+1]
                                    messages.append(msg_text.strip())
                                current_msg = []
                                in_message = False
                                synced = False
                            elif char == '-' and len(current_msg) > 40:
                                # Complete SAME message format: ZCZC-ORG-EEE-PSSCCC+TTTT-JJJHHMM-LLLLLLLL-
                                # Counting dashes: ZCZC-ORG-EEE-PSSCCC+TTTT-JJJHHMM-LLLLLLLL-
                                #                      1   2   3+location dashes  N   N+1     N+2 (final)
                                # With 3 location codes: 1+1+1+3+1+1+1 = 9 dashes total
                                # The 8th dash comes after station ID, which is what we want
                                dash_count = msg_text.count('-')
                                location_count = 0
                                has_time_section = '+' in msg_text
                                if has_time_section:
                                    pre_expiration, _ = msg_text.split('+', 1)
                                    location_segments = pre_expiration.split('-')[3:]
                                    for segment in location_segments:
                                        cleaned = segment.strip()
                                        if len(cleaned) == 6 and cleaned.isdigit():
                                            location_count += 1

                                    if location_count <= 0:
                                        min_dashes = 6
                                    else:
                                        min_dashes = 6 + max(location_count - 1, 0)

                                    # Only terminate if we have the time section and enough dashes
                                    if dash_count >= min_dashes:
                                        if 'ZCZC' in msg_text or 'NNNN' in msg_text:
                                            messages.append(msg_text.strip())
                                        current_msg = []
                                        in_message = False
                                        synced = False
                            elif len(current_msg) > MAX_MSG_LEN:
                                # Safety: prevent runaway messages
                                if 'ZCZC' in msg_text or 'NNNN' in msg_text:
                                    messages.append(msg_text.strip())
                                current_msg = []
                                in_message = False
                                synced = False
                    else:
                        # Invalid character, lost sync
                        synced = False
                        in_message = False
                        if current_msg:
                            current_msg = []

                    byte_counter = 0

        # Advance by SUBSAMP samples
        idx += SUBSAMP

    # Calculate average confidence
    if bit_confidences:
        avg_confidence = sum(bit_confidences) / len(bit_confidences)
    else:
        avg_confidence = 0.0

    return messages, avg_confidence


def _extract_bits(
    samples: List[float], sample_rate: int, bit_rate: float
) -> Tuple[List[int], float, float]:
    """Slice PCM audio into SAME bit periods and detect mark/space symbols."""

    bits: List[int] = []
    bit_confidences: List[float] = []
    bit_sample_ranges: List[Tuple[int, int]] = []

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

        start_index = index
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
        bit_sample_ranges.append((start_index, end))

        index = end

    if not bits:
        raise AudioDecodeError("The audio payload did not contain detectable SAME bursts.")

    average_confidence = sum(bit_confidences) / len(bit_confidences)
    minimum_confidence = min(bit_confidences) if bit_confidences else 0.0
    _extract_bits.last_confidence = average_confidence  # type: ignore[attr-defined]
    _extract_bits.min_confidence = minimum_confidence  # type: ignore[attr-defined]
    _extract_bits.bit_confidences = list(bit_confidences)  # type: ignore[attr-defined]
    _extract_bits.bit_sample_ranges = list(bit_sample_ranges)  # type: ignore[attr-defined]
    _extract_bits.samples_per_bit = float(samples_per_bit)  # type: ignore[attr-defined]

    return bits, average_confidence, minimum_confidence


def _extract_bytes_from_bits(
    bits: List[int], start_pos: int, max_bytes: int, *, confidence_threshold: float = 0.3
) -> Tuple[List[int], List[int]]:
    """Extract byte values and their positions from a bit stream starting at start_pos.

    Improved version with adaptive threshold and better frame validation.
    """

    confidences: List[float] = list(getattr(_extract_bits, "bit_confidences", []))
    byte_values: List[int] = []
    byte_positions: List[int] = []

    i = start_pos
    consecutive_failures = 0
    max_consecutive_failures = 5  # Allow up to 5 failed frames in a row

    while i + 10 <= len(bits) and len(byte_values) < max_bytes:
        # Check for valid frame: start bit (0) and stop bit (1)
        if bits[i] != 0:
            consecutive_failures += 1
            if consecutive_failures > max_consecutive_failures:
                break  # Too many errors, likely end of valid data
            i += 1
            continue

        # Check confidence for this frame
        frame_confidence = 0.0
        if i + 10 <= len(confidences):
            frame_confidence = sum(confidences[i:i + 10]) / 10.0

        # Adaptive threshold: lower threshold if we're already decoding successfully
        adaptive_threshold = confidence_threshold if len(byte_values) < 5 else confidence_threshold * 0.8

        if frame_confidence < adaptive_threshold:
            consecutive_failures += 1
            if consecutive_failures > max_consecutive_failures:
                break
            i += 1
            continue

        if bits[i + 9] != 1:
            consecutive_failures += 1
            if consecutive_failures > max_consecutive_failures:
                break
            i += 1
            continue

        # Extract 7-bit ASCII payload (8N1 format: 7 data bits + null bit)
        # Per FCC 47 CFR §11.31: 7-bit ASCII + eighth null bit
        data_bits = bits[i + 1 : i + 8]
        # Bit 8 (position i+8) is the null bit, which we ignore

        value = 0
        for position, bit in enumerate(data_bits):
            value |= (bit & 1) << position

        # Validate that it's a printable ASCII character or control character
        if 32 <= value <= 126 or value in (10, 13, 45):  # Printable ASCII, LF, CR, dash
            byte_values.append(value)
            byte_positions.append(i)
            consecutive_failures = 0  # Reset on success
        else:
            consecutive_failures += 1
            if consecutive_failures > max_consecutive_failures:
                break

        i += 10

    return byte_values, byte_positions


def _find_same_bursts(bits: List[int]) -> List[int]:
    """Find the starting positions of SAME bursts by looking for ZCZC markers."""

    # Look for 'ZCZC' pattern which marks the start of each SAME header
    # 'Z' = 0x5A, 'C' = 0x43
    # We'll search for sequences that look like ZCZC

    burst_positions: List[int] = []

    # Define character patterns using 8N1 framing (8 data bits, no parity, 1 stop)
    # Per FCC 47 CFR §11.31: 7-bit ASCII + eighth null bit
    # 'Z' = 0x5A = 0b01011010 -> LSB first: 0,1,0,1,1,0,1 + null(0)
    # Frame: [start=0][7 data bits LSB first][null bit=0][stop=1]
    Z_pattern = [0, 0, 1, 0, 1, 1, 0, 1, 0, 1]
    # 'C' = 0x43 = 0b01000011 -> LSB first: 1,1,0,0,0,0,1 + null(0)
    C_pattern = [0, 1, 1, 0, 0, 0, 0, 1, 0, 1]

    # Skip the preamble (16 bytes of 0xAB * 10 bits per byte = 160 bits)
    # The preamble can cause false matches, so start searching after it
    preamble_bits = 160
    i = min(preamble_bits, len(bits) // 4)  # Start after preamble or 25% into bits
    while i < len(bits) - 40:  # Need at least 4 * 10 bits for ZCZC
        # Check for ZCZC pattern
        z1_matches = sum(1 for j in range(10) if i+j < len(bits) and bits[i+j] == Z_pattern[j])
        c1_matches = sum(1 for j in range(10) if i+10+j < len(bits) and bits[i+10+j] == C_pattern[j])
        z2_matches = sum(1 for j in range(10) if i+20+j < len(bits) and bits[i+20+j] == Z_pattern[j])
        c2_matches = sum(1 for j in range(10) if i+30+j < len(bits) and bits[i+30+j] == C_pattern[j])

        # If we found a reasonably good ZCZC match
        total_matches = z1_matches + c1_matches + z2_matches + c2_matches
        if total_matches >= 28:  # Allow ~30% bit errors (12 out of 40 bits can be wrong)
            # Found a burst! Record the position
            # This is the start of the message (ZCZC position)
            burst_positions.append(i)
            i += 400  # Skip ahead to avoid finding the same burst multiple times
        else:
            i += 10

    return burst_positions


def _find_pattern_positions(
    bits: List[int], pattern: str, *, max_mismatches: Optional[int] = None
) -> List[int]:
    """Locate approximate occurrences of ``pattern`` within the decoded bit stream."""

    pattern_bits = encode_same_bits(pattern, include_preamble=False)
    if not pattern_bits:
        return []

    pattern_length = len(pattern_bits)
    if max_mismatches is None:
        max_mismatches = max(4, pattern_length // 5)

    positions: List[int] = []
    i = 0
    limit = len(bits) - pattern_length

    while i <= limit:
        mismatches = 0
        for j in range(pattern_length):
            if bits[i + j] != pattern_bits[j]:
                mismatches += 1
                if mismatches > max_mismatches:
                    break
        if mismatches <= max_mismatches:
            positions.append(i)
            i += pattern_length
        else:
            i += 1

    return positions


def _process_decoded_text(
    raw_text: str,
    frame_count: int,
    frame_errors: int,
    extra_metadata: Optional[Dict[str, object]] = None,
) -> Dict[str, object]:
    """Process decoded text to extract and clean SAME headers."""

    trimmed_text = raw_text

    if raw_text:
        upper_text = raw_text.upper()

        # Trim to start at ZCZC if found
        start_index = upper_text.find("ZCZC")
        if start_index > 0:
            trimmed_text = raw_text[start_index:]
            upper_text = trimmed_text.upper()

        # Trim to end at NNNN if found
        end_index = upper_text.rfind("NNNN")
        if end_index != -1:
            end_offset = end_index + 4
            if end_offset < len(trimmed_text) and trimmed_text[end_offset] == "\r":
                end_offset += 1
            trimmed_text = trimmed_text[:end_offset]
        else:
            # Otherwise trim at last carriage return
            last_break = trimmed_text.rfind("\r")
            if last_break != -1:
                trimmed_text = trimmed_text[: last_break + 1]

    # Extract headers
    headers: List[str] = []
    for segment in trimmed_text.split("\r"):
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

    if headers:
        trimmed_text = "\r".join(headers) + "\r"

    metadata: Dict[str, object] = {
        "text": trimmed_text,
        "headers": headers,
        "frame_count": frame_count,
        "frame_errors": frame_errors,
    }

    if extra_metadata:
        metadata.update(extra_metadata)

    return metadata


def _vote_on_bytes(burst_bytes: List[List[int]]) -> List[int]:
    """Perform 2-out-of-3 majority voting on byte sequences from multiple bursts."""

    if not burst_bytes:
        return []

    # Find the maximum length among all bursts
    max_len = max(len(burst) for burst in burst_bytes)
    voted_bytes: List[int] = []

    for pos in range(max_len):
        # Collect byte values at this position from all bursts
        candidates: List[int] = []
        for burst in burst_bytes:
            if pos < len(burst):
                candidates.append(burst[pos])

        if not candidates:
            continue

        # Perform majority voting
        if len(candidates) == 1:
            voted_bytes.append(candidates[0])
        elif len(candidates) == 2:
            # With 2 candidates, take the first one (or could average)
            voted_bytes.append(candidates[0])
        else:
            # With 3 candidates, find the majority
            # Count occurrences
            from collections import Counter
            counts = Counter(candidates)
            most_common = counts.most_common(1)[0]

            # If there's a clear majority (at least 2), use it
            if most_common[1] >= 2:
                voted_bytes.append(most_common[0])
            else:
                # No majority, take the first one
                voted_bytes.append(candidates[0])

    return voted_bytes


def _bits_to_text(bits: List[int]) -> Dict[str, object]:
    """Convert mark/space bits into ASCII SAME text and headers with 2-of-3 voting."""

    burst_positions = _find_same_bursts(bits)
    burst_bit_ranges: List[Tuple[int, int]] = []

    if len(burst_positions) >= 2:
        burst_bytes: List[List[int]] = []
        typical_length = burst_positions[1] - burst_positions[0]
        if typical_length <= 0:
            typical_length = len(encode_same_bits("ZCZC", include_preamble=True))
        for index, burst_start in enumerate(burst_positions[:3]):
            bytes_in_burst, positions = _extract_bytes_from_bits(
                bits, burst_start, max_bytes=200, confidence_threshold=0.3
            )
            burst_bytes.append(bytes_in_burst)
            trimmed_positions = positions
            if positions and bytes_in_burst:
                for idx, value in enumerate(bytes_in_burst):
                    if (value & 0x7F) == 0x0D:  # carriage return
                        trimmed_positions = positions[: idx + 1]
                        break
            if trimmed_positions:
                start_bit = trimmed_positions[0]
                end_bit = trimmed_positions[-1] + 10
            else:
                start_bit = burst_start
                if index + 1 < len(burst_positions):
                    end_bit = burst_positions[index + 1]
                else:
                    end_bit = burst_start + typical_length
            burst_bit_ranges.append((start_bit, end_bit))

        voted_bytes = _vote_on_bytes(burst_bytes)

        characters: List[str] = []
        for byte_val in voted_bytes:
            try:
                char = chr(byte_val & 0x7F)
                characters.append(char)
            except ValueError:
                continue

        raw_text = "".join(characters)

        if "ZCZC" in raw_text.upper() or "NNNN" in raw_text.upper():
            return _process_decoded_text(
                raw_text,
                len(voted_bytes),
                0,
                extra_metadata={
                    "burst_bit_ranges": burst_bit_ranges,
                    "burst_positions": burst_positions,
                },
            )

    characters = []
    char_positions: List[int] = []
    error_positions: List[int] = []
    confidences: List[float] = list(getattr(_extract_bits, "bit_confidences", []))
    confidence_threshold = 0.6

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

        # Extract 7-bit ASCII payload (8N1 format: 7 data bits + null bit)
        # Bit 8 is the null bit per FCC spec, which we ignore
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

    if not burst_bit_ranges and burst_positions:
        for burst_start in burst_positions[:3]:
            bytes_in_burst, positions = _extract_bytes_from_bits(
                bits, burst_start, max_bytes=200, confidence_threshold=0.3
            )
            trimmed_positions = positions
            if positions and bytes_in_burst:
                for idx, value in enumerate(bytes_in_burst):
                    if (value & 0x7F) == 0x0D:
                        trimmed_positions = positions[: idx + 1]
                        break
            if trimmed_positions:
                start_bit = trimmed_positions[0]
                end_bit = trimmed_positions[-1] + 10
                burst_bit_ranges.append((start_bit, end_bit))

    if char_positions:
        first_bit = char_positions[0]
        last_bit = char_positions[-1]
        relevant_errors = [
            pos for pos in error_positions if first_bit <= pos <= last_bit
        ]
    else:
        relevant_errors = list(error_positions)

    frame_errors = len(relevant_errors)
    frame_count = len(characters) + frame_errors

    metadata = _process_decoded_text(
        raw_text,
        frame_count,
        frame_errors,
        extra_metadata={
            "burst_bit_ranges": burst_bit_ranges,
            "burst_positions": burst_positions,
        },
    )
    metadata["char_bit_positions"] = list(char_positions)
    return metadata


def _score_candidate(metadata: Dict[str, object]) -> float:
    """Return a quality score for decoded SAME metadata."""

    headers = metadata.get("headers") or []
    text = metadata.get("text") or ""
    frame_count = int(metadata.get("frame_count") or 0)
    frame_errors = int(metadata.get("frame_errors") or 0)

    # Validate headers for corruption (control characters)
    valid_headers = []
    for header in headers:
        is_valid = True
        for char in str(header):
            code = ord(char)
            # Reject headers with control characters (except CR/LF)
            if code < 32 and code not in (10, 13):
                is_valid = False
                break
        if is_valid:
            valid_headers.append(header)

    # Count valid ZCZC headers
    uppercase_headers = [header.upper() for header in valid_headers]
    zczc_count = sum(1 for header in uppercase_headers if header.startswith("ZCZC"))
    nnnn_count = sum(1 for header in uppercase_headers if header.startswith("NNNN"))

    # Start score based on frame quality
    # If we have valid ZCZC headers, frame errors matter less (bit rate sync issues)
    if zczc_count >= 1:
        # Reduce frame error penalty when we have valid headers
        score = float(frame_count - frame_errors)
        score -= float(frame_errors * 0.5)  # Much lower penalty
    else:
        # Full penalty when no valid headers
        score = float(frame_count - frame_errors)
        score -= float(frame_errors * 2)

    # Heavily penalize corrupted headers
    corrupted_count = len(headers) - len(valid_headers)
    if corrupted_count > 0:
        score -= 10000.0 * corrupted_count

    # Reward valid headers
    if valid_headers:
        score += 500.0 * len(valid_headers)
        score += 200.0 * zczc_count
        score += 100.0 * nnnn_count

        # Large bonus for having 3 ZCZC headers (standard SAME format)
        if zczc_count == 3:
            score += 5000.0
        # Bonus for having at least 1 valid ZCZC header
        elif zczc_count >= 1:
            score += 1000.0

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
    best_bit_sample_ranges: Optional[List[Tuple[int, int]]] = None
    best_bit_confidences: Optional[List[float]] = None

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
        bit_sample_ranges = list(getattr(_extract_bits, "bit_sample_ranges", []))
        bit_confidences = list(getattr(_extract_bits, "bit_confidences", []))

        if best_score is None or score > best_score + 1e-6:
            best_bits = bits
            best_metadata = metadata
            best_average = average_confidence
            best_minimum = minimum_confidence
            best_score = score
            best_rate = bit_rate
            best_bit_sample_ranges = bit_sample_ranges
            best_bit_confidences = bit_confidences
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
            best_bit_sample_ranges = bit_sample_ranges
            best_bit_confidences = bit_confidences

    if best_bits is None or best_metadata is None:
        raise AudioDecodeError("The audio payload did not contain detectable SAME bursts.")

    if best_bit_sample_ranges is not None:
        _extract_bits.bit_sample_ranges = list(best_bit_sample_ranges)  # type: ignore[attr-defined]
    if best_bit_confidences is not None:
        _extract_bits.bit_confidences = list(best_bit_confidences)  # type: ignore[attr-defined]

    return best_bits, best_metadata, best_average, best_minimum


def _bit_range_to_sample_range(
    bit_range: Tuple[int, int],
    bit_sample_ranges: Sequence[Tuple[int, int]],
    total_samples: int,
) -> Optional[Tuple[int, int]]:
    if not bit_sample_ranges:
        return None

    start_bit, end_bit = bit_range
    if start_bit >= len(bit_sample_ranges):
        return None

    if end_bit <= start_bit:
        end_bit = start_bit + 1

    start_index = max(0, min(start_bit, len(bit_sample_ranges) - 1))
    end_index = max(0, min(end_bit - 1, len(bit_sample_ranges) - 1))

    start_sample = bit_sample_ranges[start_index][0]
    end_sample = bit_sample_ranges[end_index][1]
    end_sample = min(end_sample, total_samples)
    start_sample = max(0, min(start_sample, end_sample))

    if end_sample <= start_sample:
        return None

    return start_sample, end_sample


def _clamp_sample_range(start: int, end: int, total: int) -> Tuple[int, int]:
    start = max(0, min(start, total))
    end = max(start, min(end, total))
    return start, end


def _render_wav_segment(
    pcm_bytes: bytes, sample_rate: int, start_sample: int, end_sample: int
) -> bytes:
    start_sample, end_sample = _clamp_sample_range(start_sample, end_sample, len(pcm_bytes) // 2)
    if end_sample <= start_sample:
        return b""

    start_byte = start_sample * 2
    end_byte = end_sample * 2
    segment_pcm = pcm_bytes[start_byte:end_byte]

    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(segment_pcm)

    return buffer.getvalue()


def _create_segment(
    label: str,
    start_sample: int,
    end_sample: int,
    *,
    sample_rate: int,
    pcm_bytes: bytes,
) -> Optional[SAMEAudioSegment]:
    start_sample, end_sample = _clamp_sample_range(start_sample, end_sample, len(pcm_bytes) // 2)
    if end_sample <= start_sample:
        return None

    wav_bytes = _render_wav_segment(pcm_bytes, sample_rate, start_sample, end_sample)
    if not wav_bytes:
        return None

    return SAMEAudioSegment(
        label=label,
        start_sample=start_sample,
        end_sample=end_sample,
        sample_rate=sample_rate,
        wav_bytes=wav_bytes,
    )


def _detect_audio_sample_rate(path: str) -> int:
    """Detect the native sample rate of an audio file using multiple methods."""

    # Method 1: Try Python's wave module (works for standard PCM WAV files)
    try:
        with wave.open(path, "rb") as handle:
            return handle.getframerate()
    except Exception:
        pass

    # Method 2: Try reading WAV header manually (works for IEEE Float and other WAV formats)
    try:
        with open(path, "rb") as f:
            # Read RIFF header
            riff = f.read(4)
            if riff == b"RIFF":
                f.read(4)  # Skip file size
                wave_tag = f.read(4)
                if wave_tag == b"WAVE":
                    # Find fmt chunk
                    while True:
                        chunk_id = f.read(4)
                        if not chunk_id:
                            break
                        chunk_size = int.from_bytes(f.read(4), byteorder="little")

                        if chunk_id == b"fmt ":
                            # Read format chunk
                            format_tag = int.from_bytes(f.read(2), byteorder="little")
                            channels = int.from_bytes(f.read(2), byteorder="little")
                            sample_rate = int.from_bytes(f.read(4), byteorder="little")
                            if 1000 <= sample_rate <= 192000:  # Sanity check
                                return sample_rate
                            break
                        else:
                            # Skip this chunk
                            f.seek(chunk_size, 1)
    except Exception:
        pass

    # Method 3: Try ffprobe if available
    if shutil.which("ffprobe"):
        try:
            result = subprocess.run(
                [
                    "ffprobe",
                    "-v", "error",
                    "-select_streams", "a:0",
                    "-show_entries", "stream=sample_rate",
                    "-of", "default=noprint_wrappers=1:nokey=1",
                    path
                ],
                capture_output=True,
                check=True,
                timeout=5,
            )
            if result.stdout:
                sample_rate = int(result.stdout.decode("utf-8").strip())
                if 1000 <= sample_rate <= 192000:  # Sanity check
                    return sample_rate
        except (subprocess.CalledProcessError, ValueError, subprocess.TimeoutExpired):
            pass

    # Fallback to default
    return 16000


def _calculate_adjusted_confidence(
    raw_confidence: float,
    headers: List[SAMEHeaderDetails],
    frame_count: int,
    frame_errors: int
) -> float:
    """Calculate an adjusted confidence score based on decode quality indicators.

    The raw correlation-based confidence is conservative. Boost it when we have
    strong indicators of a good decode.
    """
    # Start with raw confidence
    confidence = raw_confidence

    if headers:
        # Strong indicator: valid ZCZC header decoded
        for header in headers:
            header_text = header.header

            # Check for clean ASCII (no control characters except CR/LF)
            has_clean_ascii = all(
                32 <= ord(c) <= 126 or c in "\r\n"
                for c in header_text
            )

            # Check for valid ZCZC structure
            has_valid_structure = (
                header_text.startswith("ZCZC-") and
                header_text.count('-') >= 6 and  # Minimum dashes for valid header
                '+' in header_text  # Has time field
            )

            # Check for completion (ends with dash or callsign)
            is_complete = header_text.endswith("-") or (
                header_text.count('-') >= 7 and len(header_text) > 50
            )

            # Calculate quality boost
            quality_multiplier = 1.0

            if has_clean_ascii:
                quality_multiplier += 0.3  # +30% for clean ASCII

            if has_valid_structure:
                quality_multiplier += 0.4  # +40% for valid structure

            if is_complete:
                quality_multiplier += 0.3  # +30% for complete header

            # Apply boost (can increase confidence up to 2x for perfect decode)
            confidence *= quality_multiplier

    # Factor in frame error rate
    if frame_count > 0:
        error_rate = frame_errors / frame_count
        # Penalize high error rates, reward low ones
        if error_rate < 0.05:  # <5% errors
            confidence *= 1.1  # +10% bonus
        elif error_rate > 0.4:  # >40% errors
            confidence *= 0.8  # -20% penalty

    # Cap at 1.0
    return min(confidence, 1.0)


def _score_decode_result(result: SAMEAudioDecodeResult, expected_rate: int, actual_rate: int) -> float:
    """Score a decode result for multi-rate selection.

    Higher score = better decode quality.
    """
    score = 0.0

    # Major bonus for finding valid headers
    if result.headers:
        score += 1000.0

        # Bonus for each header found
        score += len(result.headers) * 100.0

        # Check header quality
        for header in result.headers:
            # Valid ZCZC header structure
            if header.header.startswith("ZCZC-"):
                score += 500.0

            # Complete header (ends with dash)
            if header.header.endswith("-"):
                score += 200.0

            # Check if all characters are valid ASCII (no control chars)
            valid_chars = all(
                32 <= ord(c) <= 126 or c in "\r\n"
                for c in header.header
            )
            if valid_chars:
                score += 300.0

            # Longer headers are generally better (more complete)
            score += len(header.header)

    # Confidence scoring (scale: 0.0-1.0 -> 0-500 points)
    score += result.bit_confidence * 500.0

    # Low frame error rate is good
    if result.frame_count > 0:
        error_rate = result.frame_errors / result.frame_count
        score += (1.0 - error_rate) * 200.0

    # Prefer sample rate close to file metadata (small penalty if different)
    if expected_rate > 0 and actual_rate != expected_rate:
        rate_diff_pct = abs(actual_rate - expected_rate) / expected_rate
        score -= rate_diff_pct * 50.0

    return score


def _try_multiple_sample_rates(path: str, native_rate: int) -> Tuple[SAMEAudioDecodeResult, int, bool]:
    """Try decoding at multiple sample rates and return the best result.

    Returns: (best_result, best_rate, rate_mismatch_detected)
    """
    # Common sample rates to try (in order of preference)
    # Lower sample rates are preferred for efficiency (less CPU, memory, bandwidth)
    # Testing shows 16kHz is optimal: 39% faster than 22kHz, 100% reliable
    candidate_rates = [
        native_rate,  # Try native rate first
        16000,  # Optimal: 7.7× highest SAME frequency, fastest reliable rate
        11025,  # Good: 5.3× highest SAME frequency
        22050,  # Legacy: May have timing issues with some signals
        24000,  # Alternative standard rate
        44100,  # High quality but 3× slower than 16kHz
        48000,  # Professional audio but very slow
    ]

    # Remove duplicates while preserving order
    seen = set()
    unique_rates = []
    for rate in candidate_rates:
        if rate not in seen:
            seen.add(rate)
            unique_rates.append(rate)

    best_result: Optional[SAMEAudioDecodeResult] = None
    best_score = -float('inf')
    best_rate = native_rate

    for rate in unique_rates:
        try:
            # Try decoding at this sample rate
            result = _decode_at_sample_rate(path, rate)

            # Score this result
            score = _score_decode_result(result, native_rate, rate)

            if score > best_score:
                best_score = score
                best_result = result
                best_rate = rate

        except (AudioDecodeError, Exception):
            # This rate didn't work, try next one
            continue

    if best_result is None:
        raise AudioDecodeError("Unable to decode SAME audio at any sample rate")

    rate_mismatch = (best_rate != native_rate)

    return best_result, best_rate, rate_mismatch


def _decode_at_sample_rate(path: str, sample_rate: int) -> SAMEAudioDecodeResult:
    """Internal helper to decode at a specific sample rate."""
    samples, pcm_bytes = _read_audio_samples(path, sample_rate)
    sample_count = len(samples)
    if sample_count == 0:
        raise AudioDecodeError("Audio payload contained no PCM samples to decode.")
    duration_seconds = sample_count / float(sample_rate)

    correlation_headers: Optional[List[SAMEHeaderDetails]] = None
    correlation_raw_text: Optional[str] = None
    correlation_confidence: Optional[float] = None

    # Enable correlation decoder to handle external files with timing variations
    USE_CORRELATION_DECODER = True

    if USE_CORRELATION_DECODER:
        try:
            messages, confidence = _correlate_and_decode_with_dll(samples, sample_rate)

            if messages:
                from collections import Counter

                zczc_messages = [msg for msg in messages if "ZCZC" in msg]
                if zczc_messages:
                    counter = Counter(zczc_messages)
                    most_common = counter.most_common(1)[0]

                    decoded_header: Optional[str] = None
                    if most_common[1] >= 2:
                        decoded_header = most_common[0]
                    elif len(zczc_messages) == 1:
                        decoded_header = zczc_messages[0]

                    if decoded_header:
                        if "ZCZC" in decoded_header:
                            zczc_idx = decoded_header.find("ZCZC")
                            decoded_header = decoded_header[zczc_idx:]

                        raw_text = decoded_header + "\r"
                        fips_lookup = get_same_lookup()
                        header_fields = describe_same_header(
                            decoded_header, lookup=fips_lookup
                        )
                        correlation_headers = [
                            SAMEHeaderDetails(
                                header=decoded_header,
                                fields=header_fields,
                                confidence=confidence,
                                summary=build_plain_language_summary(
                                    decoded_header, header_fields
                                ),
                            )
                        ]
                        correlation_raw_text = raw_text
                        correlation_confidence = confidence

        except Exception:
            pass

    base_rate = float(SAME_BAUD)
    try:
        bits, metadata, average_confidence, minimum_confidence = _decode_with_candidate_rates(
            samples, sample_rate, base_rate=base_rate
        )
    except AudioDecodeError:
        if correlation_headers:
            return SAMEAudioDecodeResult(
                raw_text=correlation_raw_text or "",
                headers=correlation_headers,
                bit_count=0,
                frame_count=0,
                frame_errors=0,
                duration_seconds=duration_seconds,
                sample_rate=sample_rate,
                bit_confidence=correlation_confidence or 0.0,
                min_bit_confidence=correlation_confidence or 0.0,
                segments=OrderedDict(),
            )
        raise

    metadata_text = str(metadata.get("text") or "")
    metadata_headers = [str(item) for item in metadata.get("headers") or []]
    header_confidence = (
        correlation_confidence if correlation_confidence is not None else average_confidence
    )
    if metadata_headers:
        fips_lookup = get_same_lookup()
        headers: List[SAMEHeaderDetails] = []
        for header in metadata_headers:
            fields = describe_same_header(header, lookup=fips_lookup)
            headers.append(
                SAMEHeaderDetails(
                    header=header,
                    fields=fields,
                    confidence=header_confidence,
                    summary=build_plain_language_summary(header, fields),
                )
            )
        raw_text = metadata_text or correlation_raw_text or ""
    else:
        headers = correlation_headers or []
        raw_text = correlation_raw_text or metadata_text or ""

    bit_confidence = average_confidence
    min_bit_confidence = minimum_confidence
    if correlation_confidence is not None:
        bit_confidence = max(bit_confidence, correlation_confidence)
        min_bit_confidence = min(min_bit_confidence, correlation_confidence)

    bit_sample_ranges: Sequence[Tuple[int, int]] = list(
        getattr(_extract_bits, "bit_sample_ranges", [])
    )
    header_ranges_bits: Sequence[Tuple[int, int]] = metadata.get("burst_bit_ranges") or []
    header_sample_ranges: List[Tuple[int, int]] = []
    header_last_bit: Optional[int] = None

    burst_positions_bits: List[int] = [
        int(pos) for pos in metadata.get("burst_positions") or []
    ]
    burst_positions_bits.sort()
    if burst_positions_bits and bit_sample_ranges:
        samples_per_bit = float(
            getattr(_extract_bits, "samples_per_bit", sample_rate / float(SAME_BAUD))
        )
        estimated_bits = len(encode_same_bits("ZCZC", include_preamble=True))
        typical_bits = estimated_bits
        typical_samples = int(samples_per_bit * estimated_bits)

        if len(burst_positions_bits) >= 2:
            delta_bits = burst_positions_bits[1] - burst_positions_bits[0]
            if delta_bits > 0:
                typical_bits = delta_bits
                typical_samples = max(
                    1,
                    bit_sample_ranges[burst_positions_bits[1]][0]
                    - bit_sample_ranges[burst_positions_bits[0]][0],
                )

        normalized_bits: List[int] = []
        normalized_samples: List[int] = []

        first_bit = burst_positions_bits[0]
        if 0 <= first_bit < len(bit_sample_ranges):
            normalized_bits.append(first_bit)
            normalized_samples.append(bit_sample_ranges[first_bit][0])

        index = 1
        while len(normalized_bits) < 3:
            expected_bit = (
                normalized_bits[-1] + typical_bits if normalized_bits else typical_bits
            )
            expected_sample = (
                normalized_samples[-1] + typical_samples
                if normalized_samples
                else typical_samples
            )

            candidate_bit = None
            candidate_sample = None
            if index < len(burst_positions_bits):
                raw_bit = burst_positions_bits[index]
                if 0 <= raw_bit < len(bit_sample_ranges):
                    candidate_bit = raw_bit
                    candidate_sample = bit_sample_ranges[raw_bit][0]
                index += 1

            if (
                candidate_bit is not None
                and abs(candidate_bit - expected_bit) <= max(5, typical_bits * 0.75)
            ):
                normalized_bits.append(candidate_bit)
                normalized_samples.append(candidate_sample or expected_sample)
            else:
                normalized_bits.append(int(expected_bit))
                normalized_samples.append(int(expected_sample))

        for bit_position, start_sample in zip(normalized_bits, normalized_samples):
            end_sample = start_sample + typical_samples
            end_sample = min(end_sample, sample_count)
            end_sample = max(start_sample, end_sample)
            header_sample_ranges.append((start_sample, end_sample))
            header_last_bit = max(header_last_bit or bit_position, bit_position + typical_bits)

    if not header_sample_ranges:
        for start_bit, end_bit in header_ranges_bits:
            start_bit = int(start_bit)
            end_bit = int(end_bit)
            header_last_bit = max(header_last_bit or start_bit, end_bit)
            sample_range = _bit_range_to_sample_range(
                (start_bit, end_bit), bit_sample_ranges, sample_count
            )
            if sample_range:
                header_sample_ranges.append(sample_range)

    header_segment = None
    if header_sample_ranges:
        header_start = min(start for start, _ in header_sample_ranges)
        header_end = max(end for _, end in header_sample_ranges)
        header_segment = _create_segment(
            "header",
            header_start,
            header_end,
            sample_rate=sample_rate,
            pcm_bytes=pcm_bytes,
        )

    eom_segment = None
    eom_positions = _find_pattern_positions(bits, "NNNN")
    if header_last_bit is not None:
        eom_positions = [pos for pos in eom_positions if pos >= header_last_bit] or eom_positions
    if eom_positions:
        eom_length_bits = len(encode_same_bits("NNNN", include_preamble=False))
        first_eom = eom_positions[0]
        eom_sample_range = _bit_range_to_sample_range(
            (first_eom, first_eom + eom_length_bits), bit_sample_ranges, sample_count
        )
        if eom_sample_range:
            eom_segment = _create_segment(
                "eom",
                eom_sample_range[0],
                eom_sample_range[1],
                sample_rate=sample_rate,
                pcm_bytes=pcm_bytes,
            )

    message_start = header_segment.end_sample if header_segment else 0
    if eom_segment and eom_segment.start_sample > message_start:
        message_end = eom_segment.start_sample
    else:
        message_end = sample_count
    message_segment = _create_segment(
        "message",
        message_start,
        message_end,
        sample_rate=sample_rate,
        pcm_bytes=pcm_bytes,
    )

    buffer_samples = min(sample_count, int(sample_rate * 120))
    buffer_segment = _create_segment(
        "buffer",
        0,
        buffer_samples,
        sample_rate=sample_rate,
        pcm_bytes=pcm_bytes,
    )

    segments: Dict[str, SAMEAudioSegment] = OrderedDict()
    if header_segment:
        segments["header"] = header_segment
    if message_segment:
        segments["message"] = message_segment
    if eom_segment:
        segments["eom"] = eom_segment
    if buffer_segment:
        segments["buffer"] = buffer_segment

    frame_count = int(metadata.get("frame_count") or 0)
    frame_errors = int(metadata.get("frame_errors") or 0)

    # Apply adjusted confidence scoring based on decode quality
    adjusted_confidence = _calculate_adjusted_confidence(
        bit_confidence,
        headers,
        frame_count,
        frame_errors
    )

    return SAMEAudioDecodeResult(
        raw_text=raw_text,
        headers=headers,
        bit_count=len(bits),
        frame_count=frame_count,
        frame_errors=frame_errors,
        duration_seconds=duration_seconds,
        sample_rate=sample_rate,
        bit_confidence=adjusted_confidence,
        min_bit_confidence=min_bit_confidence,
        segments=segments,
    )


def decode_same_audio(path: str, *, sample_rate: Optional[int] = None) -> SAMEAudioDecodeResult:
    """Decode SAME headers from a WAV or MP3 file located at ``path``.

    If sample_rate is not provided, multi-rate auto-detection will be used to find
    the best sample rate. This handles files with incorrect sample rate metadata.

    If sample_rate is provided explicitly, it will be used directly without trying
    other rates.
    """

    if not os.path.exists(path):
        raise AudioDecodeError(f"Audio file does not exist: {path}")

    # If sample rate is explicitly provided, use it directly
    if sample_rate is not None:
        return _decode_at_sample_rate(path, sample_rate)

    # Auto-detect and try multiple rates
    native_rate = _detect_audio_sample_rate(path)
    result, actual_rate, rate_mismatch = _try_multiple_sample_rates(path, native_rate)

    # Log warning if sample rate mismatch detected
    if rate_mismatch and result.headers:
        import warnings
        warnings.warn(
            f"Sample rate mismatch detected: file metadata indicates {native_rate} Hz, "
            f"but signal decoded successfully at {actual_rate} Hz. "
            f"The file may have been resampled incorrectly or have incorrect metadata.",
            UserWarning
        )

    return result


__all__ = [
    "AudioDecodeError",
    "SAMEAudioSegment",
    "SAMEAudioDecodeResult",
    "SAMEHeaderDetails",
    "decode_same_audio",
]
