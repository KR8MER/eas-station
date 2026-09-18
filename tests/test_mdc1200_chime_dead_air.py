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

"""Regression tests for missing dead-air around the pre/post MDC1200 burst.

User report: "still not getting the second of dead air before the MDC1200
preceding the header is sent... [and] the 1 second of dead air after the
mdc1200 after the EOM."

Both EASAudioGenerator.build_files() and .build_manual_components() play an
optional pre/post "chime" -- which can be an MDC1200 selective-calling burst
when pre_alert_chime/post_alert_chime is set to 'mdc1200' -- immediately
before the first SAME header burst and immediately after the EOM sequence.
The 1-second gap between that chime/MDC1200 burst and the header/EOM it
brackets was already present, but the *outer* gap (before the pre-burst,
after the post-burst) was missing: the composite started the MDC1200 packet
at sample 0, and ended immediately after the post-MDC1200 packet with no
trailing silence at all.
"""

import tempfile
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any, Dict

from unittest.mock import MagicMock

from app_utils.eas import EASAudioGenerator, load_eas_config

SAMPLE_RATE = 8000
HEADER = 'ZCZC-CIV-RWT-039000+0100-0790000-OHIOSTEM-'
# Silence tolerance: near-zero rather than exactly zero, since the tone/FSK
# generators can leave a few LSBs of floating-point rounding noise.
_SILENCE_THRESHOLD = 50


def _build_generator(**chime_overrides) -> EASAudioGenerator:
    base = load_eas_config()
    cfg: Dict[str, Any] = dict(base)
    cfg['enabled'] = True
    cfg['output_dir'] = tempfile.mkdtemp()
    cfg['sample_rate'] = SAMPLE_RATE
    cfg['attention_tone_seconds'] = 0.5
    cfg['pre_alert_chime'] = 'mdc1200'
    cfg['post_alert_chime'] = 'mdc1200'
    cfg.update(chime_overrides)
    logger = MagicMock()
    return EASAudioGenerator(cfg, logger)


def _build_alert() -> SimpleNamespace:
    now = datetime.now(timezone.utc)
    return SimpleNamespace(
        id=None,
        identifier='MDC1200-DEADAIR-TEST-001',
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


def _is_silent(samples) -> bool:
    return all(abs(s) < _SILENCE_THRESHOLD for s in samples)


class TestBuildManualComponentsMdc1200DeadAir:
    def test_one_second_of_silence_precedes_the_pre_mdc1200_burst(self):
        gen = _build_generator()
        alert = _build_alert()

        components = gen.build_manual_components(alert, HEADER)
        composite = components['composite_samples']

        lead_in = composite[: int(SAMPLE_RATE * 1.0)]
        assert _is_silent(lead_in), (
            "The composite must open with 1 second of silence before the "
            "pre-chime/MDC1200 burst, not the burst itself at sample 0."
        )
        # And the burst itself must follow immediately after -- confirms the
        # silence is a leading gap, not just an empty/no-op chime.
        just_after = composite[int(SAMPLE_RATE * 1.0): int(SAMPLE_RATE * 1.05)]
        assert not _is_silent(just_after), (
            "The pre-chime/MDC1200 burst must start right after the 1-second "
            "lead-in silence."
        )

    def test_one_second_of_silence_follows_the_post_mdc1200_burst(self):
        gen = _build_generator()
        alert = _build_alert()

        components = gen.build_manual_components(alert, HEADER)
        composite = components['composite_samples']

        tail = composite[-int(SAMPLE_RATE * 1.0):]
        assert _is_silent(tail), (
            "The composite must end with 1 second of silence after the "
            "post-chime/MDC1200 burst, not stop dead at the end of the burst."
        )

    def test_no_dead_air_regression_when_chime_disabled(self):
        """Baseline: with no chime configured, neither gap is inserted --
        matches TestNoEmbeddedLeadInSilence in test_rwt_announcements.py."""
        gen = _build_generator(pre_alert_chime='none', post_alert_chime='none')
        alert = _build_alert()

        components = gen.build_manual_components(alert, HEADER)
        composite = components['composite_samples']

        first_window = composite[: int(SAMPLE_RATE * 0.05)]
        assert not _is_silent(first_window), (
            "With chimes disabled, the composite must still open with the "
            "header's own energy immediately -- this fix must not add a "
            "gap that was never there when there is no chime to bracket."
        )


class TestBuildFilesMdc1200DeadAir:
    def _build_payload(self) -> Dict[str, Any]:
        now = datetime.now(timezone.utc)
        return {
            'identifier': 'MDC1200-DEADAIR-TEST-001',
            'event': 'Required Weekly Test',
            'status': 'Actual',
            'message_type': 'Alert',
            'sent': now,
            'expires': now + timedelta(hours=1),
            'raw_json': {'properties': {'geocode': {'SAME': ['039000']}}},
        }

    def test_wav_duration_grows_by_roughly_two_seconds_versus_no_chime(self):
        """Indirect but robust: enabling pre+post MDC1200 chimes must add
        the chime/MDC1200 burst durations *plus* the two 1-second dead-air
        gaps this fix restores -- not just the bursts alone."""
        import io
        import wave

        alert = _build_alert()
        payload = self._build_payload()

        gen_none = _build_generator(pre_alert_chime='none', post_alert_chime='none')
        gen_none.config['tts_provider'] = ''
        _, _, _, wav_none, _, _ = gen_none.build_files(alert, payload, HEADER, ['039000'])

        gen_mdc = _build_generator()
        gen_mdc.config['tts_provider'] = ''
        _, _, _, wav_mdc, _, _ = gen_mdc.build_files(alert, payload, HEADER, ['039000'])

        def _duration(wav_bytes: bytes) -> float:
            with wave.open(io.BytesIO(wav_bytes)) as wf:
                return wf.getnframes() / wf.getframerate()

        delta = _duration(wav_mdc) - _duration(wav_none)
        # MDC1200 packets are ~147 ms each (pre + post), plus the pre-existing
        # inner 1 s gaps (already there before this fix) plus the two new
        # outer 1 s gaps this fix adds -- comfortably over 2 s combined, and
        # nowhere near the ~0.3 s it would be if the outer gaps were missing.
        assert delta > 2.0, (
            f"Expected MDC1200 chimes to add >2s (bursts + all dead-air "
            f"gaps) versus no chime, got {delta:.3f}s -- the outer dead-air "
            f"gaps around the MDC1200 bursts appear to be missing again."
        )
