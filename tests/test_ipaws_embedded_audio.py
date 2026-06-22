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

"""Regression tests for IPAWS embedded-audio handling.

IPAWS alerts can carry pre-recorded audio in the CAP ``<resource>``
element's ``derefUri`` field (base64-encoded binary).  Alerts from some
originators omit the ``mimeType`` and ``resourceDesc`` fields entirely,
leaving only ``derefUri``.  Prior to this fix, both ``_fetch_embedded_audio``
and ``save_ipaws_audio`` silently ignored those resources and fell back to
TTS synthesis (or produced no audio at all when no TTS provider was
configured).

These tests verify that:
  1. ``_fetch_embedded_audio`` decodes inline ``derefUri`` audio even when
     ``mimeType``, ``resourceDesc`` and ``uri`` are all absent.
  2. ``_fetch_embedded_audio`` rejects resources whose MIME type explicitly
     indicates a non-audio format.
  3. ``_fetch_embedded_audio`` still handles the external-URI case correctly.
  4. ``save_ipaws_audio`` saves ``derefUri`` audio when ``mimeType`` /
     ``resourceDesc`` are missing.
  5. The EASAudioGenerator uses embedded audio (``provider='ipaws_embedded'``)
     when resources contain a ``derefUri`` instead of calling TTS.
"""

import base64
import io
import math
import os
import struct
import tempfile
import wave
from types import SimpleNamespace
from typing import Dict, Any
from unittest.mock import MagicMock, patch

import pytest

from app_utils.eas import _fetch_embedded_audio, _convert_audio_to_samples, EASAudioGenerator, load_eas_config
from app_utils.ipaws_enrichment import save_ipaws_audio


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

SAMPLE_RATE = 8000


def _make_wav_bytes(duration: float = 0.5, sample_rate: int = SAMPLE_RATE) -> bytes:
    """Return minimal mono 16-bit PCM WAV bytes."""
    num_samples = int(sample_rate * duration)
    samples = [int(16000 * math.sin(2 * math.pi * 440 * i / sample_rate)) for i in range(num_samples)]
    frames = struct.pack(f'<{num_samples}h', *samples)
    buf = io.BytesIO()
    with wave.open(buf, 'wb') as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(frames)
    return buf.getvalue()


def _wav_b64(duration: float = 0.5) -> str:
    """Return base64-encoded WAV audio as a string."""
    return base64.b64encode(_make_wav_bytes(duration)).decode('ascii')


# ---------------------------------------------------------------------------
# _fetch_embedded_audio
# ---------------------------------------------------------------------------

class TestFetchEmbeddedAudio:
    """Unit tests for _fetch_embedded_audio()."""

    def test_deref_uri_only_no_mime_type(self):
        """Resource with only derefUri (no mimeType/resourceDesc/uri) must be used."""
        resources = [{'derefUri': _wav_b64()}]
        logger = MagicMock()

        samples, source = _fetch_embedded_audio(resources, SAMPLE_RATE, logger)

        assert samples is not None, "Expected audio samples from derefUri resource"
        assert len(samples) > 0
        assert source is not None
        assert 'derefUri' in source

    def test_deref_uri_with_audio_mime_type(self):
        """Resource with derefUri and 'audio/wav' mimeType must be used."""
        resources = [{'derefUri': _wav_b64(), 'mimeType': 'audio/wav'}]
        logger = MagicMock()

        samples, source = _fetch_embedded_audio(resources, SAMPLE_RATE, logger)

        assert samples is not None
        assert len(samples) > 0

    def test_deref_uri_with_eas_broadcast_desc(self):
        """Resource with derefUri and 'EAS Broadcast Content' description must be used."""
        resources = [{'derefUri': _wav_b64(), 'resourceDesc': 'EAS Broadcast Content'}]
        logger = MagicMock()

        samples, source = _fetch_embedded_audio(resources, SAMPLE_RATE, logger)

        assert samples is not None

    def test_non_audio_mime_type_excluded(self):
        """Resource with a non-audio MIME type must NOT be used, even if it has derefUri."""
        dummy_b64 = base64.b64encode(b'<image data>').decode('ascii')
        resources = [{'derefUri': dummy_b64, 'mimeType': 'image/jpeg'}]
        logger = MagicMock()

        samples, source = _fetch_embedded_audio(resources, SAMPLE_RATE, logger)

        assert samples is None, "Non-audio MIME type must not produce samples"
        assert source is None

    def test_no_resources_returns_none(self):
        """Empty resource list must return (None, None)."""
        logger = MagicMock()
        samples, source = _fetch_embedded_audio([], SAMPLE_RATE, logger)
        assert samples is None
        assert source is None

    def test_resource_without_content_ignored(self):
        """Resource with no uri and no derefUri must be ignored."""
        resources = [{'mimeType': 'audio/mpeg', 'resourceDesc': 'EAS audio'}]
        logger = MagicMock()

        samples, source = _fetch_embedded_audio(resources, SAMPLE_RATE, logger)

        assert samples is None

    def test_invalid_base64_skipped_gracefully(self):
        """Corrupted base64 must not raise; function must return (None, None)."""
        resources = [{'derefUri': '!!!NOT_VALID_BASE64!!!'}]
        logger = MagicMock()

        samples, source = _fetch_embedded_audio(resources, SAMPLE_RATE, logger)

        assert samples is None

    def test_external_uri_resource_still_works(self):
        """uri-based resources must still be downloaded and used."""
        wav_bytes = _make_wav_bytes()
        resources = [{'uri': 'http://example.com/audio.wav', 'mimeType': 'audio/wav'}]
        logger = MagicMock()

        mock_response = MagicMock()
        mock_response.content = wav_bytes
        mock_response.raise_for_status = MagicMock()

        with patch('requests.get', return_value=mock_response) as mock_get:
            samples, source = _fetch_embedded_audio(resources, SAMPLE_RATE, logger)

        assert samples is not None
        assert source == 'http://example.com/audio.wav'
        mock_get.assert_called_once()

    def test_deref_uri_preferred_over_uri(self):
        """When a resource has both derefUri and uri, derefUri must be used first."""
        resources = [{
            'derefUri': _wav_b64(),
            'uri': 'http://example.com/audio.wav',
            'mimeType': 'audio/wav',
        }]
        logger = MagicMock()

        with patch('requests.get') as mock_get:
            samples, source = _fetch_embedded_audio(resources, SAMPLE_RATE, logger)

        # derefUri was decoded without a network request
        mock_get.assert_not_called()
        assert samples is not None
        assert 'derefUri' in source


# ---------------------------------------------------------------------------
# save_ipaws_audio
# ---------------------------------------------------------------------------

class TestSaveIpawsAudio:
    """Unit tests for save_ipaws_audio()."""

    def test_deref_uri_only_no_mime_type(self):
        """Resource with only derefUri (no mimeType/resourceDesc) must be saved."""
        wav_bytes = _make_wav_bytes()
        b64 = base64.b64encode(wav_bytes).decode('ascii')
        raw_json = {'properties': {'resources': [{'derefUri': b64}]}}

        with tempfile.TemporaryDirectory() as tmpdir:
            filename = save_ipaws_audio(raw_json, 'TEST-ALERT-001', tmpdir)

        assert filename is not None, "Expected save_ipaws_audio to return a filename"
        assert filename.endswith('.mp3')  # IPAWS default extension

    def test_deref_uri_with_audio_mime_type(self):
        """Resource with derefUri and audio/wav mimeType must be saved."""
        wav_bytes = _make_wav_bytes()
        b64 = base64.b64encode(wav_bytes).decode('ascii')
        raw_json = {'properties': {'resources': [{'derefUri': b64, 'mimeType': 'audio/wav'}]}}

        with tempfile.TemporaryDirectory() as tmpdir:
            filename = save_ipaws_audio(raw_json, 'TEST-ALERT-002', tmpdir)

        assert filename is not None
        assert filename.endswith('.wav')

    def test_non_audio_mime_type_excluded(self):
        """Resource with a non-audio MIME type must NOT be saved."""
        b64 = base64.b64encode(b'<not audio>').decode('ascii')
        raw_json = {'properties': {'resources': [{'derefUri': b64, 'mimeType': 'image/png'}]}}

        with tempfile.TemporaryDirectory() as tmpdir:
            filename = save_ipaws_audio(raw_json, 'TEST-ALERT-003', tmpdir)

        assert filename is None

    def test_no_resources_returns_none(self):
        """Alert with no resources returns None."""
        raw_json = {'properties': {'resources': []}}

        with tempfile.TemporaryDirectory() as tmpdir:
            filename = save_ipaws_audio(raw_json, 'TEST-ALERT-004', tmpdir)

        assert filename is None

    def test_file_written_to_disk(self):
        """Saved audio file must exist on disk with non-zero size."""
        wav_bytes = _make_wav_bytes()
        b64 = base64.b64encode(wav_bytes).decode('ascii')
        raw_json = {'properties': {'resources': [{'derefUri': b64}]}}

        with tempfile.TemporaryDirectory() as tmpdir:
            filename = save_ipaws_audio(raw_json, 'TEST-ALERT-005', tmpdir)
            assert filename is not None
            filepath = os.path.join(tmpdir, filename)
            assert os.path.exists(filepath)
            assert os.path.getsize(filepath) == len(wav_bytes)


# ---------------------------------------------------------------------------
# EASAudioGenerator integration: embedded audio vs TTS
# ---------------------------------------------------------------------------

class TestEASAudioGeneratorEmbeddedAudio:
    """EASAudioGenerator must use embedded audio instead of TTS when available."""

    def _build_generator(self) -> EASAudioGenerator:
        base = load_eas_config()
        cfg: Dict[str, Any] = dict(base)
        cfg['enabled'] = True
        cfg['output_dir'] = tempfile.mkdtemp()
        cfg['sample_rate'] = SAMPLE_RATE
        cfg['attention_tone_seconds'] = 0.5
        cfg['tts_provider'] = ''
        logger = MagicMock()
        return EASAudioGenerator(cfg, logger)

    def _build_alert(self) -> SimpleNamespace:
        from datetime import datetime, timezone, timedelta
        now = datetime.now(timezone.utc)
        return SimpleNamespace(
            id=None,
            identifier='CAPNET-1-1949-20260318094500',
            event='REQUIRED MONTHLY TEST',
            headline='Emergency Alert System Test',
            description='This is only a test.',
            instruction='No action is needed.',
            sent=now,
            expires=now + timedelta(hours=1),
            status='Actual',
            message_type='Alert',
            severity='Minor',
            urgency='Expected',
            certainty='Observed',
            raw_json=None,
        )

    def _build_payload_with_deref_uri(self, wav_b64: str) -> Dict[str, Any]:
        """Build a payload mimicking the IPAWS alert from the bug report."""
        from datetime import datetime, timezone, timedelta
        now = datetime.now(timezone.utc)
        return {
            'identifier': 'CAPNET-1-1949-20260318094500',
            'event': 'REQUIRED MONTHLY TEST',
            'status': 'Actual',
            'message_type': 'Alert',
            'sent': now,
            'expires': now + timedelta(hours=1),
            'raw_json': {
                'properties': {
                    'geocode': {'SAME': ['039000']},
                    # Only derefUri, no mimeType, no resourceDesc, no uri
                    'resources': [{'derefUri': wav_b64}],
                }
            },
            'forwarding_decision': 'forwarded',
            'forwarded': True,
        }

    def test_build_files_uses_embedded_audio_not_tts(self):
        """When resources contain derefUri audio, provider must be 'ipaws_embedded'."""
        gen = self._build_generator()
        alert = self._build_alert()
        wav_b64 = _wav_b64(duration=1.0)
        payload = self._build_payload_with_deref_uri(wav_b64)

        (
            audio_filename,
            _text_filename,
            _message_text,
            audio_bytes,
            text_payload,
            segment_payload,
        ) = gen.build_files(alert, payload, 'ZCZC-CIV-RMT-039000+0100-0790000-OHIOSTEM-', ['039000'])

        assert text_payload.get('voiceover_provider') == 'ipaws_embedded', (
            "Expected provider 'ipaws_embedded' but got: "
            f"{text_payload.get('voiceover_provider')!r}"
        )
        assert segment_payload.get('tts') is not None, \
            "Expected tts segment to contain the embedded audio samples"

    def test_build_files_falls_back_when_no_resources(self):
        """When no resources are present, provider must NOT be 'ipaws_embedded'."""
        gen = self._build_generator()
        alert = self._build_alert()
        from datetime import datetime, timezone, timedelta
        now = datetime.now(timezone.utc)
        payload = {
            'identifier': 'CAPNET-NOAUDIO',
            'event': 'REQUIRED MONTHLY TEST',
            'status': 'Actual',
            'message_type': 'Alert',
            'sent': now,
            'expires': now + timedelta(hours=1),
            'raw_json': {
                'properties': {
                    'geocode': {'SAME': ['039000']},
                    'resources': [],
                }
            },
            'forwarding_decision': 'forwarded',
            'forwarded': True,
        }

        (
            _audio_filename,
            _text_filename,
            _message_text,
            _audio_bytes,
            text_payload,
            _segment_payload,
        ) = gen.build_files(alert, payload, 'ZCZC-CIV-RMT-039000+0100-0790000-OHIOSTEM-', ['039000'])

        assert text_payload.get('voiceover_provider') != 'ipaws_embedded'
