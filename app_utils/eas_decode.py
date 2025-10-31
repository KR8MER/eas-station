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
from .fips_codes import get_same_lookup


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


def _read_audio_samples(path: str, sample_rate: int) -> List[float]:
    """Return normalised PCM samples from an arbitrary audio file."""

    try:
        import wave

        with wave.open(path, "rb") as handle:
            params = handle.getparams()
            native_rate = params.framerate

            # Read the raw PCM data
            if params.nchannels == 1 and params.sampwidth == 2:
                pcm = handle.readframes(params.nframes)
                if pcm:
                    samples = _convert_pcm_to_floats(pcm)

                    # If sample rates match, return as-is
                    if native_rate == sample_rate:
                        return samples

                    # Try scipy resampling first as it's faster and more reliable
                    try:
                        return _resample_with_scipy(samples, native_rate, sample_rate)
                    except (ImportError, AudioDecodeError):
                        # Fall back to ffmpeg if scipy isn't available
                        pass
    except Exception:
        pass

    # Fall back to ffmpeg for non-WAV files or if resampling failed
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
    confidences = []

    while idx + corr_len < len(samples):
        # Compute correlation (mark - space)
        mark_i_corr = sum(samples[idx + i] * mark_i[i] for i in range(corr_len))
        mark_q_corr = sum(samples[idx + i] * mark_q[i] for i in range(corr_len))
        space_i_corr = sum(samples[idx + i] * space_i[i] for i in range(corr_len))
        space_q_corr = sum(samples[idx + i] * space_q[i] for i in range(corr_len))

        correlation = (mark_i_corr**2 + mark_q_corr**2) - (space_i_corr**2 + space_q_corr**2)

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
                                if dash_count >= 8:  # 8 dashes includes station ID field
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
    avg_confidence = 0.6  # Placeholder since we're using correlation

    return messages, avg_confidence


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

        # Extract data bits (7 or 8 bits depending on position)
        # For preamble: 8 bits, for message: 7 bits
        data_bits = bits[i + 1 : i + 9]

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


def _process_decoded_text(raw_text: str, frame_count: int, frame_errors: int) -> Dict[str, object]:
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

    return {
        "text": trimmed_text,
        "headers": headers,
        "frame_count": frame_count,
        "frame_errors": frame_errors,
    }


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

    # First, try to find the three SAME bursts
    burst_positions = _find_same_bursts(bits)

    # If we found multiple bursts, use voting
    if len(burst_positions) >= 2:
        burst_bytes: List[List[int]] = []

        for burst_start in burst_positions[:3]:  # Use up to 3 bursts
            # burst_start now points to the start of ZCZC (no preamble skip needed)
            bytes_in_burst, _ = _extract_bytes_from_bits(
                bits, burst_start, max_bytes=200, confidence_threshold=0.3
            )
            burst_bytes.append(bytes_in_burst)

        # Perform voting
        voted_bytes = _vote_on_bytes(burst_bytes)

        # Convert voted bytes to characters
        characters: List[str] = []
        for byte_val in voted_bytes:
            try:
                # Mask to 7 bits for ASCII
                char = chr(byte_val & 0x7F)
                characters.append(char)
            except ValueError:
                continue

        raw_text = "".join(characters)

        # If voting produced a valid result, use it
        if "ZCZC" in raw_text.upper() or "NNNN" in raw_text.upper():
            return _process_decoded_text(raw_text, len(voted_bytes), 0)

    # Fallback to original single-pass decode if voting didn't work
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

    # Calculate frame errors for fallback
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

    return _process_decoded_text(raw_text, frame_count, frame_errors)


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


def decode_same_audio(path: str, *, sample_rate: int = 22050) -> SAMEAudioDecodeResult:
    """Decode SAME headers from a WAV or MP3 file located at ``path``."""

    if not os.path.exists(path):
        raise AudioDecodeError(f"Audio file does not exist: {path}")

    samples = _read_audio_samples(path, sample_rate)
    duration_seconds = len(samples) / float(sample_rate)

    # Try the new correlation-based decoder first (multimon-ng style)
    try:
        messages, confidence = _correlate_and_decode_with_dll(samples, sample_rate)

        if messages:
            # Perform 2-of-3 message-level voting
            from collections import Counter

            # Filter to only ZCZC messages (not NNNN)
            zczc_messages = [msg for msg in messages if 'ZCZC' in msg]

            if len(zczc_messages) >= 2:
                # Count identical messages
                counter = Counter(zczc_messages)
                most_common = counter.most_common(1)[0]

                # If at least 2 out of 3 agree, use that message
                if most_common[1] >= 2:
                    decoded_header = most_common[0]

                    # Clean up the header
                    if 'ZCZC' in decoded_header:
                        zczc_idx = decoded_header.find('ZCZC')
                        decoded_header = decoded_header[zczc_idx:]

                    raw_text = decoded_header + '\r'

                    # Get FIPS code lookup for county names
                    fips_lookup = get_same_lookup()

                    headers = [
                        SAMEHeaderDetails(
                            header=decoded_header,
                            fields=describe_same_header(decoded_header, lookup=fips_lookup),
                            confidence=confidence,
                        )
                    ]

                    return SAMEAudioDecodeResult(
                        raw_text=raw_text,
                        headers=headers,
                        bit_count=len(samples) // int(sample_rate / float(SAME_BAUD)),
                        frame_count=len(decoded_header),
                        frame_errors=0,
                        duration_seconds=duration_seconds,
                        sample_rate=sample_rate,
                        bit_confidence=confidence,
                        min_bit_confidence=confidence,
                    )
            elif len(zczc_messages) == 1:
                # Got exactly one message - use it
                decoded_header = zczc_messages[0]

                if 'ZCZC' in decoded_header:
                    zczc_idx = decoded_header.find('ZCZC')
                    decoded_header = decoded_header[zczc_idx:]

                raw_text = decoded_header + '\r'

                # Get FIPS code lookup for county names
                fips_lookup = get_same_lookup()

                headers = [
                    SAMEHeaderDetails(
                        header=decoded_header,
                        fields=describe_same_header(decoded_header, lookup=fips_lookup),
                        confidence=confidence,
                    )
                ]

                return SAMEAudioDecodeResult(
                    raw_text=raw_text,
                    headers=headers,
                    bit_count=len(samples) // int(sample_rate / float(SAME_BAUD)),
                    frame_count=len(decoded_header),
                    frame_errors=0,
                    duration_seconds=duration_seconds,
                    sample_rate=sample_rate,
                    bit_confidence=confidence,
                    min_bit_confidence=confidence,
                )

    except Exception:
        # Correlation decoder failed, fall back to legacy method
        pass

    # Fallback to legacy Goertzel-based decoder
    base_rate = float(SAME_BAUD)
    bits, metadata, average_confidence, minimum_confidence = _decode_with_candidate_rates(
        samples, sample_rate, base_rate=base_rate
    )

    raw_text = metadata["text"]

    # Get FIPS code lookup for county names
    fips_lookup = get_same_lookup()

    headers: List[SAMEHeaderDetails] = []
    for header in metadata["headers"]:
        headers.append(
            SAMEHeaderDetails(
                header=header,
                fields=describe_same_header(header, lookup=fips_lookup),
                confidence=average_confidence,
            )
        )

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
