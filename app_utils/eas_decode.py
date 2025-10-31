"""Decode SAME/EAS headers from audio files containing alert bursts."""

from __future__ import annotations

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

from .eas import ORIGINATOR_DESCRIPTIONS, describe_same_header
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
    return value.strftime("%b %d, %Y").upper()


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
        state_label = state_abbr or state_name
        code = (item.get("code") or "").strip()

        if description:
            label = description
            if state_label and state_label not in description:
                label = f"{label}, {state_label}"
        else:
            if code and state_label:
                label = f"{state_label} ({code})"
            else:
                label = code or state_label

        if code:
            normalised_code = code
            if normalised_code not in label:
                if normalised_code.isdigit():
                    label = f"{label} (FIPS {normalised_code})"
                else:
                    label = f"{label} ({normalised_code})"
        label = label.strip()
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
        event_name = entry.get("name") or code
        article = _select_article(event_name).lower()
        phrase = f"{article} {event_name}"
        if code:
            phrase += f" ({code})"
        return phrase

    if code:
        return f"an alert with event code {code}"

    return "an alert"


def build_plain_language_summary(header: str, fields: Dict[str, object]) -> Optional[str]:
    if not header:
        return None

    originator_label = _clean_originator_label(fields)
    cleaned_originator = originator_label.strip()
    if cleaned_originator.lower().startswith("the "):
        originator_phrase = cleaned_originator[0].upper() + cleaned_originator[1:]
    elif cleaned_originator:
        originator_phrase = f"The {cleaned_originator}"
    else:
        originator_phrase = "The originator"

    event_phrase = _format_event_phrase(fields)

    summary = f"{originator_phrase} has issued {event_phrase}"

    locations = _build_locations_list(fields)
    if locations:
        summary += f" for the following counties/areas: {'; '.join(locations)}"
    else:
        summary += " for the specified area"

    issue_dt = _parse_issue_datetime(fields)
    if issue_dt:
        issue_dt = issue_dt.astimezone(timezone.utc)
        summary += f" at {_format_clock(issue_dt)} on {_format_date(issue_dt)}"

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

    Returns tuple of (decoded_messages, confidence)
    """

    # Constants based on multimon-ng
    SUBSAMP = 2  # Downsampling factor
    PREAMBLE_BYTE = 0xAB  # Preamble pattern
    DLL_GAIN = 0.5  # DLL loop gain
    INTEGRATOR_MAX = 10  # Integrator bounds
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
                                if '+' in msg_text:
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
    """Extract byte values and their positions from a bit stream starting at start_pos."""

    confidences: List[float] = list(getattr(_extract_bits, "bit_confidences", []))
    byte_values: List[int] = []
    byte_positions: List[int] = []

    i = start_pos
    while i + 10 <= len(bits) and len(byte_values) < max_bytes:
        # Check for valid frame: start bit (0) and stop bit (1)
        if bits[i] != 0:
            i += 1
            continue

        # Check confidence for this frame
        frame_confidence = 0.0
        if i + 10 <= len(confidences):
            frame_confidence = sum(confidences[i:i + 10]) / 10.0
        if frame_confidence < confidence_threshold:
            i += 1
            continue

        if bits[i + 9] != 1:
            i += 1
            continue

        # Extract 7-bit ASCII payload and parity bit
        data_bits = bits[i + 1 : i + 8]
        parity_bit = bits[i + 8]

        # Validate even parity – SAME frames use 7 data bits plus even parity
        ones_total = sum(data_bits) + parity_bit
        if ones_total % 2 != 0:
            i += 1
            continue

        value = 0
        for position, bit in enumerate(data_bits):
            value |= (bit & 1) << position

        byte_values.append(value)
        byte_positions.append(i)
        i += 10

    return byte_values, byte_positions


def _find_same_bursts(bits: List[int]) -> List[int]:
    """Find the starting positions of SAME bursts by looking for ZCZC markers."""

    # Look for 'ZCZC' pattern which marks the start of each SAME header
    # 'Z' = 0x5A, 'C' = 0x43
    # We'll search for sequences that look like ZCZC

    burst_positions: List[int] = []

    # Define character patterns (LSB first, 7 bits, framed)
    # 'Z' = 0x5A = 0101101 (7 bits) -> LSB first = 0101101 -> framed: 0 + 0101101 + 0 + 1
    Z_pattern = [0, 0, 1, 0, 1, 1, 0, 1, 0, 1]
    C_pattern = [0, 1, 1, 0, 0, 0, 1, 1, 0, 1]  # 'C' = 0x43 = 1000011 -> LSB = 1100001

    i = 0
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


def decode_same_audio(path: str, *, sample_rate: int = 22050) -> SAMEAudioDecodeResult:
    """Decode SAME headers from a WAV or MP3 file located at ``path``."""

    if not os.path.exists(path):
        raise AudioDecodeError(f"Audio file does not exist: {path}")

    samples, pcm_bytes = _read_audio_samples(path, sample_rate)
    sample_count = len(samples)
    if sample_count == 0:
        raise AudioDecodeError("Audio payload contained no PCM samples to decode.")
    duration_seconds = sample_count / float(sample_rate)

    correlation_headers: Optional[List[SAMEHeaderDetails]] = None
    correlation_raw_text: Optional[str] = None
    correlation_confidence: Optional[float] = None

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
        headers = [
            SAMEHeaderDetails(
                header=header,
                fields=describe_same_header(header, lookup=fips_lookup),
                confidence=header_confidence,
            )
            for header in metadata_headers
        ]
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

    return SAMEAudioDecodeResult(
        raw_text=raw_text,
        headers=headers,
        bit_count=len(bits),
        frame_count=frame_count,
        frame_errors=frame_errors,
        duration_seconds=duration_seconds,
        sample_rate=sample_rate,
        bit_confidence=bit_confidence,
        min_bit_confidence=min_bit_confidence,
        segments=segments,
    )


__all__ = [
    "AudioDecodeError",
    "SAMEAudioSegment",
    "SAMEAudioDecodeResult",
    "SAMEHeaderDetails",
    "decode_same_audio",
]
