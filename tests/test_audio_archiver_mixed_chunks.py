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

"""An EAS injection into a stereo SDR source must not lose the archive segment.

SDR sources publish ``(frames, 2)`` chunks; the EAS stream injector
publishes mono 1-D chunks into the same queue. ``_flush_segment`` used to
``np.concatenate`` them directly, which raised "all the input arrays must
have same number of dimensions" in the flush thread and dropped the
segment every time an alert played.
"""

import os
import sys
import time
import wave
from unittest.mock import MagicMock

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app_core.audio.archiver import (  # noqa: E402
    AudioArchiver,
    AudioArchiverConfig,
    _match_chunk_shapes,
)


def test_stereo_segment_with_injected_mono_chunk_is_written(tmp_path):
    config = AudioArchiverConfig(output_dir=str(tmp_path), format="wav", silence_threshold=0.0)
    archiver = AudioArchiver(
        source_name="sdr-test", config=config, broadcast_queue=MagicMock(),
        sample_rate=48000, channels=2,
    )
    live = np.full((480, 2), 0.25, dtype=np.float32)
    eas = np.full(2400, 0.5, dtype=np.float32)  # injector: 50 ms mono

    archiver._flush_segment([live, eas, live], segment_start=time.time())

    files = list(tmp_path.rglob("*.wav"))
    assert len(files) == 1
    with wave.open(str(files[0])) as wf:
        assert wf.getnchannels() == 2
        assert wf.getnframes() == 480 + 2400 + 480


def test_upmixed_mono_chunk_is_duplicated_into_every_channel():
    out = _match_chunk_shapes([np.zeros((4, 2)), np.array([1.0, 2.0])])
    assert out[1].tolist() == [[1.0, 1.0], [2.0, 2.0]]


def test_uniform_segments_pass_through_untouched():
    mono = [np.zeros(10), np.ones(10)]
    stereo = [np.zeros((5, 2)), np.ones((5, 2))]
    assert _match_chunk_shapes(mono) is mono
    assert _match_chunk_shapes(stereo) is stereo
