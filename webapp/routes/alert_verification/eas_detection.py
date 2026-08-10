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

from __future__ import annotations

"""Locating every EAS burst in a file, not just the first.

**Over the 400-line guidance.** ``_detect_comprehensive_eas_segments`` is one
276-line function; module-level splitting cannot shrink it. Tracked as a
follow-up in docs/development/LARGE_FILE_REFACTOR_PLAN.md.
"""

import os
from collections import OrderedDict
from typing import Optional

from app_utils.eas_decode import SAMEAudioSegment, decode_same_audio
from app_utils.eas_detection import detect_eas_from_file

from .audio_buffer import _PCMBuffer, _extract_audio_segment_wav
from .composite_audio import _build_composite_audio_segment
from .progress import ProgressTracker


def _detect_comprehensive_eas_segments(
    audio_path: str,
    route_logger,
    progress: Optional[ProgressTracker] = None,
    *,
    store_results: bool = True,
):
    """
    Perform comprehensive EAS detection and return properly separated segments.

    Returns a dict compatible with SAMEAudioDecodeResult format but with additional segments:
    - header: SAME header bursts
    - attention_tone: EBS two-tone or NWS 1050 Hz
    - narration: Voice narration (only when ``store_results=True``)
    - eom: End-of-Message marker
    - buffer: Lead-in/lead-out audio

    When ``store_results`` is False the user is only previewing the
    decode and we skip the narration extraction + composite-WAV
    assembly steps.  Those are the slowest parts of the comprehensive
    pipeline and only need to run when the result will be persisted.
    """
    try:
        # Step 1: Run comprehensive detection.  The "decode" phase claims a
        # large slice of the unified progress timeline (see
        # ProgressTracker.PHASE_RANGES); sub-steps below report into it.
        if progress:
            progress.update("decode", 1, 6, "Detecting SAME headers and audio segments...")

        # Trust the native sample rate for WAV uploads — their RIFF
        # header is reliable and the multi-rate sweep would just spend
        # ~6 redundant demod passes on a known-good input.  MP3 (and
        # anything else) keeps the existing sweep so mis-tagged files
        # still recover.
        ext = os.path.splitext(audio_path.lower())[1]
        wav_fast_path = ext == ".wav"

        decode_progress_cb = None
        if progress is not None:
            def decode_progress_cb(current: int, total: int, message: str) -> None:
                # Map per-rate decode progress into steps 1..3 of the
                # decode phase so the bar advances visibly while the
                # demod loop runs (previously sat frozen at 16 %).
                progress.update(
                    "decode",
                    1 + min(2, max(0, int(round(2 * current / max(total, 1))))),
                    6,
                    message,
                )

        detection_result = detect_eas_from_file(
            audio_path,
            detect_tones=True,
            detect_narration=store_results,
            auto_rate_sweep=not wav_fast_path,
            progress_callback=decode_progress_cb,
        )

        route_logger.info(f"Comprehensive detection: SAME={detection_result.same_detected}, "
                         f"EBS={detection_result.has_ebs_tone}, NWS={detection_result.has_nws_tone}, "
                         f"Narration={detection_result.has_narration}")

        if progress:
            progress.update("decode", 4, 6, "Processing SAME headers...")

        # Get the basic SAME decode result
        same_result = detection_result.raw_same_result
        if not same_result:
            # Fallback to basic decode if comprehensive failed
            same_result = decode_same_audio(
                audio_path, auto_rate_sweep=not wav_fast_path
            )

        if progress:
            progress.update("extract", 1, 4, "Extracting audio segments...")

        # Step 2: Build segment dictionary with comprehensive segments
        segments = {}
        sample_rate = detection_result.sample_rate or same_result.sample_rate
        pcm_cache = _PCMBuffer.from_segment(same_result.segments.get('buffer'))
        if pcm_cache and pcm_cache.sample_rate != sample_rate:
            pcm_cache = None
        if not pcm_cache:
            pcm_cache = _PCMBuffer.from_segment(same_result.segments.get('message'))
            if pcm_cache and pcm_cache.sample_rate != sample_rate:
                pcm_cache = None

        # Add SAME header segment (from original decode)
        if 'header' in same_result.segments:
            segments['header'] = same_result.segments['header']

        # Add attention tone segment (EBS or NWS 1050Hz)
        if detection_result.alert_tones:
            # Take the first/longest tone as the attention tone
            tone = max(detection_result.alert_tones, key=lambda t: t.duration_seconds)

            tone_segment: Optional[SAMEAudioSegment] = None
            if pcm_cache:
                tone_segment = pcm_cache.build_segment(
                    'attention_tone',
                    tone.start_sample,
                    tone.end_sample,
                )

            if not tone_segment:
                tone_wav = _extract_audio_segment_wav(
                    audio_path,
                    tone.start_sample,
                    tone.end_sample,
                    sample_rate
                )

                tone_segment = SAMEAudioSegment(
                    label='attention_tone',
                    start_sample=tone.start_sample,
                    end_sample=tone.end_sample,
                    sample_rate=sample_rate,
                    wav_bytes=tone_wav
                )
            segments['attention_tone'] = tone_segment

            route_logger.info(f"Extracted {tone.tone_type.upper()} tone: "
                            f"{tone.duration_seconds:.2f}s at {tone.start_sample / sample_rate:.2f}s")

        # Add narration segment.  Skipped entirely when the user is just
        # previewing (store_results=False); narration extraction + WAV
        # encoding is the slowest segment-extraction step and we don't
        # need it for an ephemeral display where buffer already covers it.
        if store_results and detection_result.narration_segments:
            # Take the first narration segment with speech
            narration = next((seg for seg in detection_result.narration_segments if seg.contains_speech),
                           detection_result.narration_segments[0] if detection_result.narration_segments else None)

            if narration:
                narration_segment: Optional[SAMEAudioSegment] = None
                if pcm_cache:
                    narration_segment = pcm_cache.build_segment(
                        'narration',
                        narration.start_sample,
                        narration.end_sample,
                    )

                if not narration_segment:
                    narration_wav = _extract_audio_segment_wav(
                        audio_path,
                        narration.start_sample,
                        narration.end_sample,
                        sample_rate
                    )

                    narration_segment = SAMEAudioSegment(
                        label='narration',
                        start_sample=narration.start_sample,
                        end_sample=narration.end_sample,
                        sample_rate=sample_rate,
                        wav_bytes=narration_wav
                    )
                segments['narration'] = narration_segment

                route_logger.info(f"Extracted narration: {narration.duration_seconds:.2f}s "
                                f"at {narration.start_sample / sample_rate:.2f}s, "
                                f"speech={narration.contains_speech}")
        elif 'buffer' in same_result.segments and not detection_result.alert_tones and store_results:
            # Fallback: If no narration detected and no tones, extract narration from buffer
            # This helps when the audio doesn't have clear attention tones
            buffer_seg = same_result.segments['buffer']
            header_seg = same_result.segments.get('header')
            eom_seg = same_result.segments.get('eom')
            
            # Calculate narration bounds: after both header AND eom, to end of buffer
            # (since EOM often overlaps with or is before the end of header)
            narration_start = buffer_seg.start_sample
            if header_seg and eom_seg:
                # Start after whichever ends later
                narration_start = max(header_seg.end_sample, eom_seg.end_sample)
            elif header_seg:
                narration_start = header_seg.end_sample
            elif eom_seg:
                narration_start = eom_seg.end_sample
                
            narration_end = buffer_seg.end_sample
            
            # Only create narration if there's meaningful content
            narration_duration = (narration_end - narration_start) / sample_rate
            if narration_duration > 0.5:  # At least 0.5 seconds
                route_logger.info(f"No specific narration detected; extracting {narration_duration:.2f}s from buffer as narration fallback")
                
                narration_wav = _extract_audio_segment_wav(
                    audio_path,
                    narration_start,
                    narration_end,
                    sample_rate
                )
                
                segments['narration'] = SAMEAudioSegment(
                    label='narration',
                    start_sample=narration_start,
                    end_sample=narration_end,
                    sample_rate=sample_rate,
                    wav_bytes=narration_wav
                )

        # Add EOM segment (from original decode)
        if 'eom' in same_result.segments:
            segments['eom'] = same_result.segments['eom']

        # Add buffer segment (from original decode)
        if 'buffer' in same_result.segments:
            segments['buffer'] = same_result.segments['buffer']

        if progress:
            progress.update("extract", 3, 4, "Building composite audio segment...")

        # Build composite audio segment combining all individual segments.
        # Skipped on preview to avoid the WAV decode + concat work — the
        # buffer segment already gives the user a playable artifact.
        composite = _build_composite_audio_segment(segments, sample_rate) if store_results else None
        if composite:
            route_logger.info(f"Created composite segment: {composite.duration_seconds:.2f}s")

        if progress:
            progress.update("extract", 4, 4, "Finalizing audio segments...")

        # Update the decode result with comprehensive segments in desired order
        # Composite first, then individual segments in chronological order
        same_result.segments.clear()
        ordered_segments = OrderedDict()
        
        # Add composite first if available
        if composite:
            ordered_segments['composite'] = composite
        
        # Then add individual segments in order
        for key in ['header', 'attention_tone', 'narration', 'eom', 'buffer']:
            if key in segments:
                ordered_segments[key] = segments[key]
        
        same_result.segments.update(ordered_segments)

        # Lift MDC1200 packets from the detection result into the SAME result
        # so the template and serialisation path see them without needing
        # to thread a separate detection_result through every caller.
        if getattr(detection_result, 'mdc1200_packets', None):
            same_result.mdc1200_packets = list(detection_result.mdc1200_packets)

        # Lift alert tones (EBS/NWS) as serialisable dicts.
        if getattr(detection_result, 'alert_tones', None):
            same_result.alert_tones = [
                {
                    'tone_type': t.tone_type,
                    'confidence': t.confidence,
                    'duration_seconds': t.duration_seconds,
                    'snr_db': t.snr_db,
                    'start_sample': t.start_sample,
                    'end_sample': t.end_sample,
                    'frequencies': list(getattr(t, 'frequencies_detected', []) or []),
                }
                for t in detection_result.alert_tones
            ]

        # Lift DTMF tones as serialisable dicts.
        if getattr(detection_result, 'dtmf_tones', None):
            same_result.dtmf_tones = [t.to_dict() for t in detection_result.dtmf_tones]

        # Lift QC-II tones as serialisable dicts.
        if getattr(detection_result, 'qc2_tones', None):
            same_result.qc2_tones = [t.to_dict() for t in detection_result.qc2_tones]

        return same_result, detection_result

    except Exception as e:
        if progress:
            progress.error(f"Audio decode failed: {str(e)}")
        route_logger.error(f"Comprehensive detection failed: {e}", exc_info=True)
        # Fallback to basic decode
        return decode_same_audio(audio_path), None
