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

"""Regression tests for the RWT pre/post announcement feature and the
absence of transmitter-stabilization silence in the generated audio.

User request: spoken station announcements bracketing the automated weekly
test ("This station is conducting a test of the Emergency Alert System" /
"This concludes this test...").

A 1-second relay lead-in/lead-out used to be baked into this composite audio
as literal silence samples whenever no pre/post chime was configured. That
was wrong: it froze the padding into every stored/archived/resent copy of
the audio (including what stream listeners heard and what FCC-compliance
exports contained) and made the duration impossible to change without
regenerating every alert's audio. The relay lead-in/lead-out is now a
program-level GPIO timing concern applied by every caller that drives the
airchain (BROADCAST_LEAD_IN_SECONDS / BROADCAST_LEAD_OUT_SECONDS in
app_utils/eas.py) -- this file now guards the opposite invariant: the
composite audio itself must contain NO such padding.

  1. With no chime and no announcement configured, the composite opens with
     the header's own energy immediately -- no silent lead-in baked in.
  2. A configured lead announcement plays first, unmodified in length,
     immediately followed by the (unchanged) rest of the composite.
  3. A configured trail announcement is appended immediately after the
     (unchanged) rest of the composite.
"""

import tempfile
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any, Dict
from unittest.mock import MagicMock

from app_core.models import RWTScheduleConfig
from app_utils.eas import EASAudioGenerator, load_eas_config

SAMPLE_RATE = 8000
RWT_HEADER = 'ZCZC-CIV-RWT-039000+0100-0790000-OHIOSTEM-'


def _build_generator() -> EASAudioGenerator:
    base = load_eas_config()
    cfg: Dict[str, Any] = dict(base)
    cfg['enabled'] = True
    cfg['output_dir'] = tempfile.mkdtemp()
    cfg['sample_rate'] = SAMPLE_RATE
    cfg['attention_tone_seconds'] = 0.5
    cfg['pre_alert_chime'] = 'none'
    cfg['post_alert_chime'] = 'none'
    logger = MagicMock()
    return EASAudioGenerator(cfg, logger)


def _build_alert() -> SimpleNamespace:
    now = datetime.now(timezone.utc)
    return SimpleNamespace(
        id=None,
        identifier='RWT-TEST-001',
        event='Required Weekly Test',
        headline='Required Weekly Test',
        description='This is a required weekly test.',
        instruction='No action is needed.',
        sent=now,
        expires=now + timedelta(hours=1),
        status='Test',
        message_type='Alert',
        severity='Unknown',
        urgency='Unknown',
        certainty='Unknown',
        raw_json=None,
    )


class TestNoEmbeddedLeadInSilence:
    def test_composite_opens_with_header_energy_not_silence(self):
        """No chime, no announcement: the header's own energy must start
        immediately -- no silent lead-in baked into the audio. The 1-second
        relay pre-roll is applied at the program level instead (see
        BROADCAST_LEAD_IN_SECONDS)."""
        gen = _build_generator()
        alert = _build_alert()

        components = gen.build_manual_components(alert, RWT_HEADER)
        composite = components['composite_samples']

        first_window = composite[: int(SAMPLE_RATE * 0.05)]
        assert any(s != 0 for s in first_window), (
            "Composite audio must not open with silence -- the relay "
            "lead-in belongs to the caller's GPIO timing, not the audio."
        )

    def test_silence_before_header_is_no_longer_a_parameter(self):
        """The parameter that used to control embedded lead-in silence
        duration was removed along with the silence itself."""
        import inspect
        from app_utils.eas import EASAudioGenerator
        sig = inspect.signature(EASAudioGenerator.build_manual_components)
        assert 'silence_before_header' not in sig.parameters


class TestAnnouncementBracketing:
    def _announcement_samples(self, seconds: float) -> list:
        n = int(seconds * SAMPLE_RATE)
        # Simple non-zero, non-silent placeholder "speech" -- a constant tone
        # is enough to prove positional placement; loudness matching is
        # already covered by test_narration_loudness_normalization.py.
        return [4000 if i % 4 < 2 else -4000 for i in range(n)]

    def test_lead_announcement_precedes_the_rest_of_the_composite_unmodified(self):
        gen = _build_generator()
        alert = _build_alert()

        baseline = gen.build_manual_components(alert, RWT_HEADER)
        lead_raw = self._announcement_samples(0.3)

        with_lead = gen.build_manual_components(
            alert, RWT_HEADER, lead_announcement_samples=lead_raw,
        )

        baseline_composite = baseline['composite_samples']
        composite = with_lead['composite_samples']
        lead_norm = with_lead['lead_announcement_samples']

        assert len(lead_norm) == len(lead_raw)
        assert len(composite) == len(lead_norm) + len(baseline_composite)
        assert composite[: len(lead_norm)] == lead_norm
        assert composite[len(lead_norm):] == baseline_composite

    def test_trail_announcement_follows_the_rest_of_the_composite_unmodified(self):
        gen = _build_generator()
        alert = _build_alert()

        baseline = gen.build_manual_components(alert, RWT_HEADER)
        trail_raw = self._announcement_samples(0.4)

        with_trail = gen.build_manual_components(
            alert, RWT_HEADER, trail_announcement_samples=trail_raw,
        )

        baseline_composite = baseline['composite_samples']
        composite = with_trail['composite_samples']
        trail_norm = with_trail['trail_announcement_samples']

        assert len(trail_norm) == len(trail_raw)
        assert len(composite) == len(baseline_composite) + len(trail_norm)
        assert composite[: len(baseline_composite)] == baseline_composite
        assert composite[len(baseline_composite):] == trail_norm

    def test_both_announcements_together(self):
        gen = _build_generator()
        alert = _build_alert()

        baseline = gen.build_manual_components(alert, RWT_HEADER)
        lead_raw = self._announcement_samples(0.2)
        trail_raw = self._announcement_samples(0.25)

        result = gen.build_manual_components(
            alert, RWT_HEADER,
            lead_announcement_samples=lead_raw,
            trail_announcement_samples=trail_raw,
        )

        baseline_composite = baseline['composite_samples']
        composite = result['composite_samples']
        lead_norm = result['lead_announcement_samples']
        trail_norm = result['trail_announcement_samples']

        expected_len = len(lead_norm) + len(baseline_composite) + len(trail_norm)
        assert len(composite) == expected_len
        assert composite[: len(lead_norm)] == lead_norm
        assert composite[len(lead_norm): len(lead_norm) + len(baseline_composite)] == baseline_composite
        assert composite[len(lead_norm) + len(baseline_composite):] == trail_norm


class TestRWTScheduleConfigAnnouncementFields:
    def test_to_dict_defaults(self):
        config = RWTScheduleConfig(
            days_of_week=[], same_codes=[],
        )
        payload = config.to_dict()
        assert payload['pre_announcement_enabled'] is False
        assert payload['pre_announcement_text'] == ''
        assert payload['post_announcement_enabled'] is False
        assert payload['post_announcement_text'] == ''

    def test_to_dict_reflects_configured_announcements(self):
        config = RWTScheduleConfig(
            days_of_week=[], same_codes=[],
            pre_announcement_enabled=True,
            pre_announcement_text='This station is conducting a test of the Emergency Alert System.',
            post_announcement_enabled=True,
            post_announcement_text='This concludes this test of the Emergency Alert System.',
        )
        payload = config.to_dict()
        assert payload['pre_announcement_enabled'] is True
        assert 'conducting a test' in payload['pre_announcement_text']
        assert payload['post_announcement_enabled'] is True
        assert 'concludes this test' in payload['post_announcement_text']
