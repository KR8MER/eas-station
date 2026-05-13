"""
EAS Station - Emergency Alert System
Copyright (c) 2025-2026 Timothy Kramer (KR8MER)

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

import pathlib
import sys
import time

import numpy as np

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app_core.radio.demodulation import (  # noqa: E402
    DemodulatorConfig,
    FMDemodulator,
    RBDSDecoder,
    RBDSWorker,
    pi_to_call_sign,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_demodulator(sample_rate: int = 200_000) -> FMDemodulator:
    config = DemodulatorConfig(
        modulation_type="FM",
        sample_rate=sample_rate,
        audio_sample_rate=48_000,
        enable_rbds=True,
    )
    return FMDemodulator(config)


def _make_worker(sample_rate: int = 250_000) -> RBDSWorker:
    return RBDSWorker(sample_rate=sample_rate, intermediate_rate=25_000)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_rbds_differential_bpsk_decoding():
    """Inline differential BPSK decoding in the worker produces correct bits.

    The current implementation handles differential decoding inside
    _process_rbds via numpy operations.  We verify the arithmetic directly:
    given a sequence of raw BPSK symbol values, sign-detection followed by
    differential XOR must produce the expected transition sequence.
    """
    # Raw BPSK symbols: + means "1", - means "0" in the raw decision
    samples = np.array([0.25, 0.3, -0.2, -0.18, 0.5, -0.4], dtype=np.float32)
    raw_bits = (np.real(samples) > 0).astype(np.int8)  # [1, 1, 0, 0, 1, 0]

    prev_sym = 0  # same initialisation used by RBDSWorker
    all_symbols = np.concatenate(([prev_sym], raw_bits))
    diff = (np.diff(all_symbols.astype(np.int32)) % 2).astype(np.int8)

    expected = [1, 0, 1, 0, 1, 1]
    assert list(diff) == expected, f"Differential bits {list(diff)} != expected {expected}"


def test_rbds_detects_off_frequency_interferer_automatically():
    sr = 250_000
    worker = RBDSWorker(sample_rate=sr, intermediate_rate=25_000)
    try:
        worker._measured_pilot_freq = 19000.0
        n = 1 << 16
        t = np.arange(n, dtype=np.float64) / sr
        # Strong spur at +150 Hz from pilot×3 (57150 Hz).
        multiplex = (
            0.02 * np.sin(2 * np.pi * 19000.0 * t)
            + 0.08 * np.sin(2 * np.pi * 57150.0 * t)
            + 0.01 * np.sin(2 * np.pi * 57000.0 * t)
        ).astype(np.float32)
        offset = worker._detect_off_frequency_interferer_hz(multiplex)
        assert offset is not None
        assert abs(abs(offset) - 150.0) < 8.0
    finally:
        worker.stop()


def test_rbds_interferer_detector_no_op_without_spur():
    """Without a real off-frequency spur the auto-detector must stay silent."""
    sr = 250_000
    worker = RBDSWorker(sample_rate=sr, intermediate_rate=25_000)
    try:
        worker._measured_pilot_freq = 19000.0
        n = 1 << 16
        t = np.arange(n, dtype=np.float64) / sr
        # Only pilot and a clean RBDS subcarrier at pilot×3 — no spur.
        multiplex = (
            0.10 * np.sin(2 * np.pi * 19000.0 * t)
            + 0.05 * np.sin(2 * np.pi * 57000.0 * t)
        ).astype(np.float32)
        offset = worker._detect_off_frequency_interferer_hz(multiplex)
        assert offset is None
    finally:
        worker.stop()


def test_rbds_interference_notch_survives_offset_toggle():
    """Regression: notch must not crash when offset toggles None→value→None.

    Previously the early-return branch in ``_apply_interference_notch``
    reset ``zi_real``/``zi_imag`` to ``None`` whenever no interferer was
    detected, but the rebuild branch on the next "detected" call only
    re-initialised the filter when the b/a cache was empty or the centre
    frequency had drifted by >10 Hz.  That left ``zi=None`` flowing into
    ``scipy.signal.lfilter``, which then returned only ``y`` (not a
    ``(y, zf)`` tuple).  The unpacking ``real_out, self._..._zi_real =``
    on the next line crashed with::

        ValueError: too many values to unpack (expected 2)

    The crash was swallowed by the worker's try/except so RBDS appeared
    to keep running but the notch silently broke every time the
    detector toggled, which is exactly what happens on noisy/marginal
    captures (the very case the notch exists to handle).
    """
    sr = 250_000
    worker = RBDSWorker(sample_rate=sr, intermediate_rate=25_000)
    try:
        # Build a representative complex-baseband chunk (length matches a
        # production SDR read at 250 kHz).
        n = 1 << 15
        t = np.arange(n, dtype=np.float64) / sr
        chunk = (np.cos(2 * np.pi * 800.0 * t)
                 + 1j * np.sin(2 * np.pi * 800.0 * t)).astype(np.complex64)

        # 1) First call: a real interferer offset → builds b/a/zi state.
        out1 = worker._apply_interference_notch(chunk, sr, 800.0)
        assert out1.shape == chunk.shape
        zi_real_after_first = worker._rbds_interference_notch_zi_real
        assert zi_real_after_first is not None

        # 2) Detector goes quiet for a chunk → notch wipes zi to None.
        out2 = worker._apply_interference_notch(chunk, sr, None)
        assert out2 is chunk
        assert worker._rbds_interference_notch_zi_real is None
        assert worker._rbds_interference_notch_zi_imag is None
        # Crucially, b/a/freq cache is still populated…
        assert worker._rbds_interference_notch_b is not None
        assert worker._rbds_interference_notch_freq_hz is not None

        # 3) Detector flips back to the same offset.  This is where the
        # bug used to fire: the rebuild branch would short-circuit because
        # the cached freq matches, leaving zi=None, and lfilter then
        # returned only ``y`` and broke the unpacking.
        out3 = worker._apply_interference_notch(chunk, sr, 800.0)
        assert out3.shape == chunk.shape
        # Filter state must be restored — not None — so subsequent calls
        # keep filtering correctly.
        assert worker._rbds_interference_notch_zi_real is not None
        assert worker._rbds_interference_notch_zi_imag is not None
    finally:
        worker.stop()


def test_rbds_differential_bpsk_zero_crossing():
    """Values at 0.0 are decoded as raw bit 0; transitions are still correct."""
    samples = np.array([0.0, -0.01, 0.02], dtype=np.float32)
    raw_bits = (np.real(samples) > 0).astype(np.int8)  # [0, 0, 1]

    prev_sym = 0
    all_symbols = np.concatenate(([prev_sym], raw_bits))
    diff = (np.diff(all_symbols.astype(np.int32)) % 2).astype(np.int8)

    # 0→0 = no transition (0), 0→0 = no transition (0), 0→1 = transition (1)
    assert diff[0] == 0
    assert diff[1] == 0
    assert diff[2] == 1


def test_rbds_pilot_reference_uses_absolute_offset():
    """_generate_pilot_reference must honour the supplied sample_offset.

    This is the core of the phase-continuity fix: when chunks are dropped
    from the RBDS queue the worker must still generate the correct carrier
    phase for each chunk.  Previously the method used an internal counter
    that only advanced on *processed* chunks, causing large phase errors
    when chunks were skipped.
    """
    worker = _make_worker(sample_rate=250_000)

    n = 1000
    offset_a = 0
    offset_b = 250_000  # 1 second later (same as the real stream advancing 1 s)

    phases_a = worker._generate_pilot_reference(n, offset_a)
    phases_b = worker._generate_pilot_reference(n, offset_b)

    # phases_a should start at exactly 0 * 2π * 19000 / 250000 = 0
    assert abs(phases_a[0]) < 1e-9, f"phases_a[0] should be 0, got {phases_a[0]}"

    # phases_b should start at 2π * 19000 * (250000 / 250000) = 2π * 19000
    expected_start_b = 2.0 * np.pi * 19000.0 * (offset_b / 250_000)
    assert abs(phases_b[0] - expected_start_b) < 1e-6, (
        f"phases_b[0]={phases_b[0]:.6f} but expected {expected_start_b:.6f}"
    )


def test_rbds_pilot_reference_independent_of_call_order():
    """Each call to _generate_pilot_reference is stateless w.r.t. the offset.

    Calling it with offset 500 should give the same result whether or not
    we previously called it with offset 0 (old code would not because it
    relied on a mutable internal counter).
    """
    worker_cold = _make_worker()
    worker_warm = _make_worker()

    n = 256
    # warm worker: process a chunk at offset 0 first
    worker_warm._generate_pilot_reference(n, sample_offset=0)

    # Both workers should produce identical output for the same offset/n
    phases_cold = worker_cold._generate_pilot_reference(n, sample_offset=500)
    phases_warm = worker_warm._generate_pilot_reference(n, sample_offset=500)

    np.testing.assert_array_equal(phases_cold, phases_warm)


def test_rbds_submit_samples_accepts_offset():
    """submit_samples must accept a sample_offset positional argument."""
    worker = _make_worker()
    multiplex = np.zeros(512, dtype=np.float32)
    # Should not raise
    worker.submit_samples(multiplex, sample_offset=0)
    worker.submit_samples(multiplex, sample_offset=512)
    worker.stop()


def test_rbds_estimate_pilot_frequency_recovers_clock_offset():
    """_estimate_pilot_frequency must recover a sub-Hz pilot offset.

    Models a typical RTL-SDR with ~50 ppm clock error: the pilot, ostensibly
    19 000 Hz at the transmitter, is recovered at 18 999.05 Hz.  The
    estimator must measure that within 0.2 Hz so the 57 kHz mix can land the
    RBDS subcarrier at exactly DC.
    """
    sr = 250_000
    worker = _make_worker(sample_rate=sr)

    n = 1 << 16  # 65 536 samples ≈ 262 ms @ 250 kHz
    t = np.arange(n) / sr

    # Synthesise a realistic FM multiplex: pilot + audio + RBDS subcarrier + noise.
    pilot_hz = 18999.05  # 50 ppm low (typical uncorrected RTL-SDR)
    rng = np.random.default_rng(0)
    multiplex = (
        0.10 * np.sin(2 * np.pi * pilot_hz * t)
        + 0.50 * np.sin(2 * np.pi * 1000.0 * t)            # audio component
        + 0.05 * np.sin(2 * np.pi * (3 * pilot_hz) * t)    # RBDS subcarrier
        + 0.05 * rng.standard_normal(n)
    ).astype(np.float32)

    measured = worker._estimate_pilot_frequency(multiplex)
    assert measured is not None, "estimator should return a frequency for a station with a pilot"
    assert abs(measured - pilot_hz) < 0.2, (
        f"measured={measured} Hz but expected {pilot_hz} Hz (±0.2 Hz)"
    )
    worker.stop()


def test_rbds_estimate_pilot_frequency_rejects_mono_station():
    """Without a pilot the estimator must return None, not a noise peak."""
    sr = 250_000
    worker = _make_worker(sample_rate=sr)

    n = 1 << 16
    t = np.arange(n) / sr
    rng = np.random.default_rng(1)
    # Just audio + noise — no 19 kHz pilot.
    multiplex = (
        0.50 * np.sin(2 * np.pi * 1000.0 * t)
        + 0.05 * rng.standard_normal(n)
    ).astype(np.float32)

    measured = worker._estimate_pilot_frequency(multiplex)
    assert measured is None, f"expected None for mono station, got {measured}"
    worker.stop()


def test_rbds_pilot_reference_uses_measured_frequency():
    """Once a pilot has been measured, _generate_pilot_reference must use it.

    This is the whole point of the SDR-clock-drift fix: the carrier reference
    must follow the *recovered* pilot, not the nominal 19 000.0 Hz, so the
    57 kHz RBDS subcarrier mixes down to exactly DC.
    """
    sr = 250_000
    worker = _make_worker(sample_rate=sr)

    # Simulate a successful measurement (e.g. SDR clock 50 ppm low).
    measured = 18999.05
    worker._measured_pilot_freq = measured

    n = 1000
    sample_offset = 250_000  # 1 s into the stream
    phases = worker._generate_pilot_reference(n, sample_offset)

    # First sample's phase should reflect the measured frequency, not 19 kHz.
    expected = 2.0 * np.pi * measured * (sample_offset / sr)
    nominal = 2.0 * np.pi * 19000.0 * (sample_offset / sr)
    assert abs(phases[0] - expected) < 1e-6
    # And it should be measurably different from what 19 000 Hz would give.
    assert abs(phases[0] - nominal) > 1e-3
    worker.stop()


def test_rbds_post_mix_lowpass_rejects_stereo_sideband_artifact():
    """The post-mix lowpass must reject the 4 kHz stereo subcarrier artifact.

    Background: after mixing the FM multiplex with a 57 kHz local oscillator
    to bring the RBDS subcarrier to baseband, the upper edge of the FM stereo
    DSB sideband (which spans 23-53 kHz around the 38 kHz carrier) lands at
    ~4 kHz in the RBDS baseband.  Stereo modulation depth is roughly 10× the
    RBDS depth, so any of that energy that survives the lowpass overwhelms
    the BPSK and prevents Costas/M&M lock — observed in the field as 80%+
    raw BLER and constant sync drops despite a perfect RF signal.

    The fix sets the post-mix lowpass cutoff to 2.4 kHz (the matched-filter
    bandwidth for 1187.5-baud biphase BPSK, where the spectrum has its first
    null at 2375 Hz).  This test verifies that rejection at 4 kHz is at least
    40 dB stronger than the worst-case 7.5 kHz design it replaced, which is
    well into the stopband and far below the RBDS signal level.
    """
    sr = 250_000
    worker = _make_worker(sample_rate=sr)
    h = worker._rbds_lowpass

    def _gain_db(freq_hz: float) -> float:
        n = np.arange(len(h), dtype=np.float64)
        mid = (len(h) - 1) / 2.0
        gain = float(np.abs(np.sum(h * np.exp(-1j * 2.0 * np.pi * freq_hz * (n - mid) / sr))))
        return 20.0 * np.log10(max(gain, 1e-12))

    # Passband: at 1187.5 Hz (peak of the RBDS biphase main lobe) the filter
    # must be essentially unity gain so the BPSK is delivered unattenuated.
    rbds_main_lobe_db = _gain_db(1187.5)
    assert rbds_main_lobe_db > -1.0, (
        f"RBDS main lobe at 1187.5 Hz should be ~0 dB, got {rbds_main_lobe_db:.1f} dB"
    )

    # Stopband: at 4 kHz (where the stereo upper-sideband artifact lands)
    # the filter must attenuate by at least 40 dB.  The previous 7500 Hz /
    # 301-tap design left this artifact in the passband entirely (~0 dB).
    stereo_artifact_db = _gain_db(4000.0)
    assert stereo_artifact_db < -40.0, (
        f"4 kHz stereo bleed-through must be at least -40 dB, "
        f"got {stereo_artifact_db:.1f} dB"
    )

    # The pilot harmonic at 19 kHz, if any leakage survives the bandpass,
    # would mix to 38 kHz - far outside any reasonable cutoff.  Sanity check
    # that we still attenuate well at higher frequencies.
    far_stop_db = _gain_db(10000.0)
    assert far_stop_db < -40.0, f"10 kHz stopband should be < -40 dB, got {far_stop_db:.1f} dB"

    worker.stop()


def test_rbds_apply_reset_clears_measured_pilot():
    """A worker reset (e.g. retune) must clear the measured pilot frequency.

    Otherwise the new station would be demodulated against the previous
    station's SDR clock measurement.  Although the SDR clock itself doesn't
    change, this also re-baselines the measurement from a fresh capture so
    we never carry forward a stale or low-quality estimate.
    """
    worker = _make_worker()
    worker._measured_pilot_freq = 18999.5

    worker._apply_reset()

    assert worker._measured_pilot_freq is None
    worker.stop()


def _run_presync_sequence(worker: RBDSWorker, hit_map: dict[int, int]) -> None:
    """Drive _decode_rbds_groups with valid RBDS blocks at specific bit positions.

    hit_map maps bit_index → RBDS offset syndrome (383=A, 14=B, 303=C, 663=D,
    748=C').  A CRC-valid 26-bit block whose syndrome equals the given value is
    embedded in the bit buffer so that the shift register carries that syndrome
    when the last bit of the block is shifted in at *bit_index*.

    Dataword 0x0000 is used because it produces no spurious intermediate
    syndrome matches in a zero-filled buffer (unlike other values whose
    partial-shift register state happens to coincide with an RBDS offset
    syndrome mid-block).

    This replaces the previous monkey-patching approach for compatibility with
    the JIT-accelerated presync path (_presync_scan_numba bypasses the Python
    _calc_syndrome method and computes syndromes natively).
    """
    _syndrome_to_offset = _RBDS_SYNDROME_TO_OFFSET
    buf = [0] * 220
    for bit_end, syn in hit_map.items():
        offset_idx = _syndrome_to_offset[syn]
        block_bits = _bits_for_valid_block(worker, 0x0000, offset_idx)
        bit_start = bit_end - 25  # 26-bit block with last bit at bit_end
        for k, b in enumerate(block_bits):
            if 0 <= bit_start + k < len(buf):
                buf[bit_start + k] = b
    worker._rbds_bit_buffer = buf
    worker._decode_rbds_groups()


def test_rbds_presync_requires_three_spaced_hits_before_lock():
    """RBDS lock should only occur after 3 correctly spaced presync detections."""
    worker = _make_worker()
    # A -> B -> C detections with exact 26-bit spacing.
    # Positions chosen to start near the beginning of the buffer so the
    # 26-bit shift register contains mostly the block bits with minimal
    # zero-prefix influence: block A ends at 25, B at 51, C at 77.
    _run_presync_sequence(worker, {25: 383, 51: 14, 77: 303})
    assert worker._rbds_synced is True


def test_rbds_presync_two_hits_do_not_lock():
    """Two spaced detections are insufficient; avoid false sync in noise."""
    worker = _make_worker()
    # Only A -> B (single spacing confirmation) should not lock.
    _run_presync_sequence(worker, {25: 383, 51: 14})
    assert worker._rbds_synced is False


# ---------------------------------------------------------------------------
# Tentative-sync (post-lock quality gate) tests
#
# When the presync state machine declares a lock we enter a tentative-sync
# state.  In that state we suppress process_group() publishing and the
# sync_acquired_unix / groups_decoded stat updates until the next 50-block
# sync-quality window confirms enough fully-decoded RBDS groups.  This stops
# fake-sync events (random syndrome collisions during noise) from injecting
# corrupt PI / group-type / RT / PS / CT into the UI.
# ---------------------------------------------------------------------------


# Offset words for blocks A, B, C, D, C' per EN 50067.  Used to build
# CRC-valid 26-bit blocks for synced-mode tests.
_RBDS_OFFSETS = [252, 408, 360, 436, 848]

# Maps the standard RBDS offset syndrome value to its block-offset table index
# (0=A, 1=B, 2=C, 3=D, 4=C').  Used by presync test helpers that construct
# real bit streams from a hit_map of {bit_position: syndrome_value}.
_RBDS_SYNDROME_TO_OFFSET = {383: 0, 14: 1, 303: 2, 663: 3, 748: 4}


def _bits_for_valid_block(worker: RBDSWorker, dataword: int, block_number: int) -> list[int]:
    """Build the 26 MSB-first bits of a CRC-valid RBDS block."""
    crc = worker._calc_syndrome(dataword, 16)
    checkword = crc ^ _RBDS_OFFSETS[block_number]
    block_value = (dataword << 10) | checkword
    return [(block_value >> i) & 1 for i in range(25, -1, -1)]


def _force_synced_tentative(worker: RBDSWorker, *, block_number: int = 0) -> None:
    """Drive the worker into synced+tentative state without running presync.

    Calls _decode_rbds_groups once with an empty buffer to trigger the lazy
    state-machine init, then flips the flags directly.  This mirrors the
    state the worker is in immediately after RBDS TENTATIVELY SYNCED fires.
    """
    worker._rbds_bit_buffer = []
    worker._decode_rbds_groups()
    worker._rbds_synced = True
    worker._rbds_sync_tentative = True
    worker._rbds_tentative_good_groups = 0
    worker._rbds_block_number = block_number
    worker._rbds_block_bit_counter = 0
    worker._rbds_blocks_counter = 0
    worker._rbds_wrong_blocks_counter = 0
    worker._rbds_group_assembly_started = False
    worker._rbds_inverted_polarity = False
    worker._rbds_reg = 0
    worker._rbds_group_good_blocks_counter = 0
    worker._rbds_consecutive_crc_failures = 0


def test_rbds_lock_starts_in_tentative_state():
    """After the presync gate fires, sync should be tentative, not confirmed.

    sync_acquired_unix must remain None until the 50-block confirmation window
    succeeds — the UI's "synced for N seconds" indicator should not start
    counting on what may turn out to be a fake lock.
    """
    worker = _make_worker()
    _run_presync_sequence(worker, {100: 383, 126: 14, 152: 303})

    assert worker._rbds_synced is True
    assert worker._rbds_sync_tentative is True
    assert worker._rbds_tentative_good_groups == 0
    assert worker._stats.sync_acquired_unix is None
    worker.stop()


def test_rbds_lock_resets_per_sync_stats_but_keeps_sync_lost_count():
    """Per-sync stats must reset on every new lock; sync_lost_count must persist.

    Regression test for the displayed BLER drifting upward over a session: the
    RBDSDecoderStats docstring promises blocks_total / blocks_uncorrected /
    blocks_fec_* / groups_decoded / group_type_counts reset on every sync
    acquisition, leaving only sync_lost_count cumulative.  Before this fix
    those counters accumulated across every marginal lock since boot, so a
    receiver that had bounced sync 78 times kept showing 65% net BLER even
    after the live signal cleaned up.
    """
    worker = _make_worker()
    # Pre-load stats with the kind of accumulated history a long-running
    # session would have:  thousands of blocks, mostly uncorrected, plus a
    # handful of operator-visible sync drops.
    worker._stats.blocks_total = 12876
    worker._stats.blocks_ok = 3173
    worker._stats.blocks_fec_single = 538
    worker._stats.blocks_fec_burst = 734
    worker._stats.blocks_uncorrected = 8431
    worker._stats.groups_decoded = 96
    worker._stats.sync_lost_count = 78
    worker._stats.group_type_counts = {"0A": 43, "2A": 47, "12A": 6}

    # Drive presync with a buffer that ends *exactly* at the third syndrome
    # hit, so the sync transition is the last thing the loop does before
    # returning.  This isolates "the reset that happens on sync acquisition"
    # from any post-sync block processing the helper would otherwise add.
    # Blocks A/B/C end at bits 25/51/77 respectively (26-bit spacing).
    # Dataword 0x0000 produces no spurious intermediate syndrome matches in
    # the zero-filled prefix, so only the three intended hits are seen.
    _hit_map = {25: 383, 51: 14, 77: 303}
    _buf = [0] * 78  # ends exactly at last block
    for _bit_end, _syn in _hit_map.items():
        _offset_idx = _RBDS_SYNDROME_TO_OFFSET[_syn]
        _block_bits = _bits_for_valid_block(worker, 0x0000, _offset_idx)
        for _k, _b in enumerate(_block_bits):
            _idx = _bit_end - 25 + _k
            if 0 <= _idx < len(_buf):
                _buf[_idx] = _b
    worker._rbds_bit_buffer = _buf
    worker._decode_rbds_groups()

    assert worker._rbds_synced is True
    assert worker._rbds_sync_tentative is True
    # Per-sync counters wiped — BLER now reflects the new lock window only.
    assert worker._stats.blocks_total == 0
    assert worker._stats.blocks_ok == 0
    assert worker._stats.blocks_fec_single == 0
    assert worker._stats.blocks_fec_burst == 0
    assert worker._stats.blocks_uncorrected == 0
    assert worker._stats.groups_decoded == 0
    assert worker._stats.group_type_counts == {}
    # Cumulative drop counter survives so the operator-visible "drops since
    # boot" indicator is unaffected.
    assert worker._stats.sync_lost_count == 78
    # And sync_acquired_unix is still None — a tentative lock is not yet a
    # confirmed lock, regardless of the stats reset.
    assert worker._stats.sync_acquired_unix is None
    # The burst-FEC suppression streak from the prior lock must also be
    # cleared so the corrector is available on the very first blocks of
    # this fresh lock.
    assert worker._rbds_consecutive_crc_failures == 0
    worker.stop()


def test_rbds_tentative_sync_confirms_with_enough_good_groups():
    """≥ _RBDS_TENTATIVE_GOOD_GROUPS fully-decoded groups in 50 blocks → CONFIRMED."""
    worker = _make_worker()
    _force_synced_tentative(worker, block_number=0)

    # Capture process_group calls so we can verify gating below.
    published: list[tuple[int, int, int, int]] = []
    worker._rbds_decoder.process_group = lambda group: published.append(tuple(group))  # type: ignore[assignment]

    # Drive exactly 50 valid blocks through synced-mode decoding.
    # 50 blocks = 12 complete groups (A,B,C,D × 12) + 2 leftover blocks (A,B
    # of the 13th group, which is not yet "complete" so doesn't count).
    bits: list[int] = []
    for i in range(50):
        block_no = i % 4
        # Distinct datawords keep the test from accidentally relying on any
        # zero-special-casing in the decoder.
        bits.extend(_bits_for_valid_block(worker, 0xABCD + i, block_no))
    worker._rbds_bit_buffer = bits
    worker._decode_rbds_groups()

    assert worker._rbds_synced is True
    assert worker._rbds_sync_tentative is False, "sync should have been confirmed"
    assert worker._stats.sync_acquired_unix is not None
    # While tentative, process_group must not have been called once: every
    # one of the 12 complete groups was suppressed.
    assert published == [], (
        "process_group must not be called while sync is tentative; got "
        f"{len(published)} publishes"
    )
    # And groups_decoded must not have been bumped during tentative either.
    assert worker._stats.groups_decoded == 0
    worker.stop()


def test_rbds_tentative_sync_rejected_when_too_few_groups():
    """50-block window with too few good groups → drop sync silently.

    Crucially this drop must NOT bump sync_lost_count — that counter is
    reserved for *real* sync drops the operator should see, and a tentative
    rejection means the lock never reached the UI in the first place.
    """
    worker = _make_worker()
    worker._stats.sync_lost_count = 7  # pre-existing operator-visible drops
    _force_synced_tentative(worker, block_number=0)

    # Drive 50 blocks where every CRC fails (we use a wrong offset on every
    # block).  None of them complete a group, so tentative_good_groups stays 0.
    bits: list[int] = []
    bad_offset_block_number = 1  # send block-A bits with block-B offset → CRC fails
    for _ in range(50):
        bits.extend(_bits_for_valid_block(worker, 0xDEAD, bad_offset_block_number))
    worker._rbds_bit_buffer = bits
    worker._decode_rbds_groups()

    assert worker._rbds_synced is False, "tentative sync should have been rejected"
    assert worker._rbds_sync_tentative is False
    assert worker._stats.sync_acquired_unix is None
    # sync_lost_count must NOT have been incremented for a tentative rejection.
    assert worker._stats.sync_lost_count == 7
    worker.stop()


def test_rbds_tentative_sync_does_not_publish_groups_mid_window():
    """While tentative, completed groups must not reach RBDSDecoder.process_group.

    This is the primary user-visible benefit of the gate: even if a fake-lock
    happens to assemble a "valid" group (random bits coincidentally pass CRC),
    the bogus PI / group-type / RT / PS / CT it carries never reaches the UI.
    """
    worker = _make_worker()
    _force_synced_tentative(worker, block_number=0)

    published: list[tuple[int, int, int, int]] = []
    worker._rbds_decoder.process_group = lambda group: published.append(tuple(group))  # type: ignore[assignment]

    # Drive exactly 4 valid blocks (one complete group), well below the
    # 50-block confirmation boundary.  The group is fully assembled and
    # counted toward the tentative threshold but must not publish.
    bits: list[int] = []
    for block_no in range(4):
        bits.extend(_bits_for_valid_block(worker, 0xCAFE, block_no))
    worker._rbds_bit_buffer = bits
    worker._decode_rbds_groups()

    assert worker._rbds_sync_tentative is True
    assert worker._rbds_tentative_good_groups == 1
    assert published == []
    assert worker._stats.groups_decoded == 0
    worker.stop()


def test_rbds_sample_buffer_accumulates_by_chunk_and_flushes_once_per_window():
    """Chunk-list buffering should retain samples until the window then flush/reset."""
    sr = 250_000
    worker = _make_worker(sample_rate=sr)
    try:
        # Keep this test focused on pre-window buffering behavior.
        worker._estimate_pilot_frequency = lambda mux: 19000.0  # type: ignore[assignment]
        worker._detect_off_frequency_interferer_hz = lambda mux: None  # type: ignore[assignment]
        worker._resample = lambda samples, in_rate, out_rate: samples  # type: ignore[assignment]
        worker._costas_loop = lambda samples: samples  # type: ignore[assignment]
        worker._mm_timing_pysdr = lambda samples: np.array([], dtype=np.complex64)  # type: ignore[assignment]
        worker._decode_rbds_groups = lambda: None  # type: ignore[assignment]

        # Unsynced window at 250 kHz is ~62.5k samples. Feed three smaller
        # chunks so the worker should buffer only (not flush) so far.
        chunk = np.zeros(2000, dtype=np.float32)
        worker._process_rbds(chunk, sample_offset=0)
        worker._process_rbds(chunk, sample_offset=len(chunk))
        worker._process_rbds(chunk, sample_offset=2 * len(chunk))

        assert worker._rbds_sample_buffer_samples == 3 * len(chunk)
        assert len(worker._rbds_sample_buffer_chunks) == 3

        # Force a flush on the next call and verify the buffers reset.
        worker.RBDS_UNSYNCED_WINDOW = 1
        worker._process_rbds(chunk, sample_offset=3 * len(chunk))

        assert worker._rbds_sample_buffer_samples == 0
        assert worker._rbds_sample_buffer_chunks == []
    finally:
        worker.stop()


# ---------------------------------------------------------------------------
# Periodic pilot re-measurement tests
#
# Cheap-SDR TCXOs drift 1–3 ppm with temperature swings, which translates to
# ~0.02–0.06 Hz/s at the 19 kHz pilot.  Tripling that for the 57 kHz mix
# leaves a residual that the Costas loop has to absorb on top of phase noise.
# Re-measuring every 30 s and EMA-blending the result keeps the carrier
# reference accurate without yanking it around on a single noisy FFT.
# ---------------------------------------------------------------------------


def test_rbds_pilot_remeasure_blends_small_drift():
    """A small post-interval re-measurement should EMA-blend into the reference."""
    sr = 250_000
    worker = _make_worker(sample_rate=sr)
    worker._measured_pilot_freq = 19000.500
    # Park the counter just below the threshold so a single chunk pushes it over.
    interval_samples = int(worker._PILOT_REMEASURE_INTERVAL_SEC * sr)
    chunk = np.zeros(sr, dtype=np.float32)  # 1 s of samples
    worker._pilot_samples_since_remeasure = interval_samples - len(chunk) + 1

    # Stub the FFT-based estimator to return a plausible 0.2 Hz drift.
    worker._estimate_pilot_frequency = lambda mux: 19000.700  # type: ignore[assignment]

    worker._process_rbds(chunk, sample_offset=0)

    # EMA: new = 0.7 * 19000.500 + 0.3 * 19000.700 = 19000.560
    expected = (
        (1.0 - worker._PILOT_REMEASURE_EMA_ALPHA) * 19000.500
        + worker._PILOT_REMEASURE_EMA_ALPHA * 19000.700
    )
    assert abs(worker._measured_pilot_freq - expected) < 1e-6
    # Counter must be reset so the next remeasure waits another full interval.
    assert worker._pilot_samples_since_remeasure == 0
    worker.stop()


def test_rbds_pilot_remeasure_rejects_implausible_jump():
    """An implausibly large jump (>_PILOT_REMEASURE_MAX_DRIFT_HZ) must be ignored."""
    sr = 250_000
    worker = _make_worker(sample_rate=sr)
    worker._measured_pilot_freq = 19000.500
    interval_samples = int(worker._PILOT_REMEASURE_INTERVAL_SEC * sr)
    chunk = np.zeros(sr, dtype=np.float32)
    worker._pilot_samples_since_remeasure = interval_samples - len(chunk) + 1

    # 5 Hz jump would mean the SDR clock changed by >250 ppm in 30 s — not
    # physically plausible.  Treat as artifact (e.g. brief de-sense, tuner
    # transient) and keep the previous reference.
    worker._estimate_pilot_frequency = lambda mux: 19005.500  # type: ignore[assignment]

    worker._process_rbds(chunk, sample_offset=0)

    assert worker._measured_pilot_freq == 19000.500
    # Counter still resets so we don't re-test the same bad chunk forever.
    assert worker._pilot_samples_since_remeasure == 0
    worker.stop()


def test_rbds_pilot_remeasure_skips_when_estimator_returns_none():
    """SNR-fail (None) returns from the estimator must leave the reference alone."""
    sr = 250_000
    worker = _make_worker(sample_rate=sr)
    worker._measured_pilot_freq = 19000.500
    interval_samples = int(worker._PILOT_REMEASURE_INTERVAL_SEC * sr)
    chunk = np.zeros(sr, dtype=np.float32)
    worker._pilot_samples_since_remeasure = interval_samples - len(chunk) + 1

    worker._estimate_pilot_frequency = lambda mux: None  # type: ignore[assignment]

    worker._process_rbds(chunk, sample_offset=0)

    assert worker._measured_pilot_freq == 19000.500
    worker.stop()


def test_rbds_pilot_remeasure_does_not_fire_before_interval():
    """Below the sample threshold, the estimator must not be invoked at all."""
    sr = 250_000
    worker = _make_worker(sample_rate=sr)
    worker._measured_pilot_freq = 19000.500
    chunk = np.zeros(1000, dtype=np.float32)  # tiny chunk, well below threshold
    worker._pilot_samples_since_remeasure = 0

    invocations = {"count": 0}

    def counting_estimator(mux: np.ndarray) -> float:
        invocations["count"] += 1
        return 19010.0  # would be rejected anyway, but should not be called

    worker._estimate_pilot_frequency = counting_estimator  # type: ignore[assignment]

    worker._process_rbds(chunk, sample_offset=0)

    assert invocations["count"] == 0
    assert worker._measured_pilot_freq == 19000.500
    # Counter advanced by the chunk length.
    assert worker._pilot_samples_since_remeasure == len(chunk)
    worker.stop()


# ---------------------------------------------------------------------------
# Early-decimation tests (sample-rate-aware front end).
#
# The worker's filter chain (54-60 kHz bandpass, 57 kHz mix, 2.4 kHz post-mix
# lowpass, downstream decim to 25 kHz) is sized for ~250 kHz inputs — the
# rate at which both PySDR (https://pysdr.org/content/rds.html) and
# RdsSurveyor2 (core/signals/mpx.ts: hardcoded `sampleRate = 250000`) run
# their RDS demodulators.  At higher SDR rates (1 MHz, 2.4 MHz, etc.) the
# capped 101-tap bandpass becomes essentially all-pass and the 501-tap
# 2.4 kHz lowpass leaves the 4 kHz stereo artifact in the passband.
# FMDemodulator must therefore decimate the multiplex from the user's actual
# SDR rate down to _rbds_intermediate_rate (always 130-280 kHz) BEFORE
# submitting it to the RBDSWorker, with a proper anti-alias filter ahead of
# the downsampler.  These tests verify that pipeline at multiple sample
# rates the user might realistically configure.
# ---------------------------------------------------------------------------


def test_fmdemodulator_creates_worker_at_post_decim_rate_for_1mhz_rtlsdr():
    """At 1 MHz (typical RTL-SDR), the worker must run at 250 kHz, not 1 MHz.

    This is the critical bug RdsSurveyor2 / PySDR both flag implicitly with
    their hardcoded 250 kHz: the worker's filters only work at that rate.
    """
    demod = _make_demodulator(sample_rate=1_000_000)
    assert demod._rbds_worker is not None
    assert demod._rbds_decim == 4
    assert demod._rbds_intermediate_rate == 250_000
    # The worker's _sample_rate (used to design every filter) MUST be the
    # post-decimation rate, not config.sample_rate.
    assert demod._rbds_worker._sample_rate == 250_000
    # And an anti-alias filter must have been built.
    assert demod._rbds_aa_filter is not None
    demod.stop()
    time.sleep(0.05)


def test_fmdemodulator_creates_worker_at_post_decim_rate_for_2_4mhz_rtlsdr():
    """At 2.4 MHz (max RTL-SDR), worker also runs near 250 kHz, decim ~9."""
    demod = _make_demodulator(sample_rate=2_400_000)
    assert demod._rbds_worker is not None
    assert demod._rbds_decim >= 8 and demod._rbds_decim <= 10
    # Post-decim rate stays in the band where the worker's filters are sized.
    assert 200_000 <= demod._rbds_intermediate_rate <= 300_000
    assert demod._rbds_worker._sample_rate == demod._rbds_intermediate_rate
    assert demod._rbds_aa_filter is not None
    demod.stop()
    time.sleep(0.05)


def test_fmdemodulator_no_decim_when_already_at_target_rate():
    """At 250 kHz input (e.g. user pre-decimated, Airspy R2 audio), no extra decim."""
    demod = _make_demodulator(sample_rate=250_000)
    assert demod._rbds_decim == 1
    assert demod._rbds_intermediate_rate == 250_000
    assert demod._rbds_worker is not None
    assert demod._rbds_worker._sample_rate == 250_000
    # No decim → no AA filter needed (multiplex passes through).
    assert demod._rbds_aa_filter is None
    demod.stop()
    time.sleep(0.05)


def test_fmdemodulator_anti_alias_filter_protects_post_decim_nyquist():
    """The AA filter must reject content above post-decim Nyquist by ≥40 dB.

    Without this, downstream filters operating at the worker's intermediate
    rate would see aliases of the FM stereo subcarrier (38 kHz) and pilot
    harmonics folded into the RBDS band, which is precisely the failure
    mode the user is observing.
    """
    sr = 1_000_000
    demod = _make_demodulator(sample_rate=sr)
    assert demod._rbds_aa_filter is not None
    h = demod._rbds_aa_filter
    post_decim_rate = demod._rbds_intermediate_rate
    nyquist = post_decim_rate / 2.0

    def _gain_db(freq_hz: float) -> float:
        n = np.arange(len(h), dtype=np.float64)
        mid = (len(h) - 1) / 2.0
        gain = float(
            np.abs(np.sum(h * np.exp(-1j * 2.0 * np.pi * freq_hz * (n - mid) / sr)))
        )
        return 20.0 * np.log10(max(gain, 1e-12))

    # Passband: the 57 kHz RBDS subcarrier must come through with negligible
    # attenuation, otherwise the worker's 54-60 kHz bandpass has nothing to
    # latch onto.
    rbds_db = _gain_db(57000.0)
    assert rbds_db > -1.0, f"57 kHz RBDS subcarrier attenuated {rbds_db:.1f} dB"

    # Stopband: with decimation by N, an input tone at f aliases in the
    # post-decim spectrum to (f mod post_decim_rate).  Worst case for the
    # RBDS band is an input tone at (post_decim_rate - 57 kHz) which folds
    # exactly onto the 57 kHz subcarrier after decimation.  For 1 MHz / 4 →
    # 250 kHz post-decim, that tone is at 250000 - 57000 = 193 kHz, well
    # below SDR Nyquist (500 kHz) and squarely in our AA filter's stopband.
    fold_freq = post_decim_rate - 57000.0
    assert fold_freq < sr / 2.0, "test frequency must be below SDR Nyquist"
    fold_db = _gain_db(fold_freq)
    assert fold_db < -40.0, (
        f"AA filter must reject {fold_freq/1000:.1f} kHz (folds onto 57 kHz "
        f"RBDS after [::{demod._rbds_decim}]) by ≥40 dB; got {fold_db:.1f} dB"
    )
    # And the next fold zone (input tones near post_decim_rate * k + 57 kHz)
    # must also be rejected, otherwise stereo subcarrier energy at 38 kHz
    # could fold from the (post_decim_rate, 2*post_decim_rate) zone into
    # the worker's 0-125 kHz band.
    next_fold = post_decim_rate + 57000.0
    if next_fold < sr / 2.0:
        next_fold_db = _gain_db(next_fold)
        assert next_fold_db < -40.0, (
            f"AA filter rejection at {next_fold/1000:.1f} kHz: "
            f"{next_fold_db:.1f} dB (need < -40 dB)"
        )
    demod.stop()
    time.sleep(0.05)


def test_fmdemodulator_decimates_multiplex_before_submitting():
    """submit_samples must receive multiplex at the worker's intermediate rate.

    The submitted chunk count and sample-offset must be in the worker's
    domain (post-decimation), not in the raw SDR domain — otherwise the
    worker's pilot-locked 57 kHz reference (which uses sample_offset /
    self._sample_rate) drifts immediately.
    """
    sr = 1_000_000
    demod = _make_demodulator(sample_rate=sr)

    # Capture every submit_samples call into a list.
    calls: list[tuple[int, int]] = []

    def fake_submit(multiplex: np.ndarray, sample_offset: int) -> None:
        calls.append((len(multiplex), sample_offset))

    assert demod._rbds_worker is not None
    demod._rbds_worker.submit_samples = fake_submit  # type: ignore[assignment]

    # 8192 IQ samples at 1 MHz → 8191 multiplex on first call (no prepend),
    # then divided by decim=4 yields ~2047 samples submitted to the worker.
    chunk = np.exp(
        1j * 2.0 * np.pi * 0.001 * np.arange(8192)
    ).astype(np.complex64)
    demod.process(chunk)
    demod.process(chunk)

    assert len(calls) == 2
    decim = demod._rbds_decim
    assert decim == 4

    # First call: 8191 multiplex / 4 ≈ 2047 (or 2048, depending on lfilter
    # state initialisation).  Sanity-check it's near 8191/4 and starts at
    # offset 0.
    n0, off0 = calls[0]
    assert abs(n0 - (8191 // decim)) <= 1
    assert off0 == 0

    # Second call: offset must equal the count submitted in the first call.
    n1, off1 = calls[1]
    assert off1 == n0
    # And the second call should submit ~8192 / 4 = 2048 samples.
    assert abs(n1 - (8192 // decim)) <= 1

    demod.stop()
    time.sleep(0.05)


def test_fmdemodulator_works_across_realistic_sdr_rates():
    """Smoke-test construction at every realistic RTL-SDR rate.

    The user can configure any rate the SDR supports (RTL-SDR allows
    225-300 kHz and 900 kHz - 3.2 MHz; common picks: 1.024, 1.92, 2.048,
    2.4 MHz).  None of these should crash the demodulator or leave
    _rbds_intermediate_rate outside the 200-300 kHz comfort band that the
    worker's filters were designed for.
    """
    for sdr_rate in (250_000, 960_000, 1_024_000, 1_000_000, 1_400_000,
                     1_920_000, 2_048_000, 2_400_000, 2_500_000):
        demod = _make_demodulator(sample_rate=sdr_rate)
        try:
            assert demod._rbds_worker is not None, f"rate {sdr_rate}"
            worker_rate = demod._rbds_worker._sample_rate
            # 130 kHz is the floor enforced by the loop in __init__; the
            # upper bound ~350 kHz is what the existing audio-path
            # _intermediate_rate produces for awkward integer divisions
            # like 960k / 3.  Anything above ~350 kHz means the worker's
            # capped 101-tap bandpass starts to lose selectivity.
            assert 130_000 <= worker_rate <= 350_000, (
                f"sdr_rate={sdr_rate} produced worker_rate={worker_rate}, "
                "outside the 130-350 kHz comfort band"
            )
            # And submit_samples must accept zero-length input without crashing
            # (regression guard for the lfilter_zi initialization path).
            demod._rbds_worker.submit_samples(np.array([], dtype=np.float32), 0)
        finally:
            demod.stop()
            time.sleep(0.02)


# ---------------------------------------------------------------------------
# RBDSDecoder.process_group tests
#
# Block B layout per EN 50067 / NRSC-4:
#   bits 15..12 = group type (0..15)
#   bit    11   = version (0=A, 1=B)
#   bit    10   = TP
#   bits  9..5  = PTY (5 bits)
#   bits  4..0  = group-type-dependent payload
# ---------------------------------------------------------------------------


def _pack_block_b(group_type: int, version_b: bool, tp: bool, pty: int, low_bits: int) -> int:
    return (
        ((group_type & 0xF) << 12)
        | ((1 if version_b else 0) << 11)
        | ((1 if tp else 0) << 10)
        | ((pty & 0x1F) << 5)
        | (low_bits & 0x1F)
    )


def test_group_0a_decodes_ta_ms_and_ps():
    """Group 0A carries TA (bit 4), MS (bit 3) and a PS segment."""
    decoder = RBDSDecoder()
    pi = 0x4FB5

    # segment 0, TA=1, MS=1, DI=0 → low 5 bits = 0b11000 = 0x18
    b = _pack_block_b(group_type=0, version_b=False, tp=True, pty=5, low_bits=0x18)
    decoder.process_group((pi, b, 0x0000, (ord("E") << 8) | ord("A")))

    # The flags read from any Group 0 land immediately.
    data = decoder.get_current_data()
    assert data.pi_code == "4FB5"
    assert data.pty == 5
    assert data.tp is True
    assert data.ta is True
    assert data.ms is True

    # PS only commits after a full self-consistent cycle has been
    # confirmed twice (see test_ps_name_requires_two_identical_cycles),
    # so after a single segment the visible PS is still blank.
    assert data.ps_name == ""


def test_group_2_does_not_clobber_ta_ms():
    """Regression: TA and MS must only be read from Group 0A/0B.

    Bits 4-0 of Block B are group-type-dependent. Previously the decoder
    extracted TA from bit 4 and MS from bit 3 unconditionally, so any
    Group 2 (RadioText) message overwrote the real TA/MS with the RT A/B
    flag and a text-segment bit.
    """
    decoder = RBDSDecoder()
    pi = 0x4FB5

    # First seed the decoder with a Group 0A carrying TA=0, MS=0
    b0 = _pack_block_b(group_type=0, version_b=False, tp=False, pty=0, low_bits=0b00000)
    decoder.process_group((pi, b0, 0x0000, 0x2020))  # "  " PS chars
    assert decoder.ta is False
    assert decoder.ms is False

    # Now send a Group 2A with AB flag = 1 (bit 4) and an odd segment
    # address that sets bit 3. With the bug present this would flip TA
    # and MS to True.
    b2 = _pack_block_b(group_type=2, version_b=False, tp=False, pty=0, low_bits=0b11000)
    decoder.process_group((pi, b2, 0x4865, 0x6C6C))  # "Hell"

    assert decoder.ta is False, "TA must not be set by Group 2 A/B flag"
    assert decoder.ms is False, "MS must not be set by Group 2 segment bits"


def test_group_2a_decodes_radiotext_segment():
    """Group 2A delivers 4 RT characters per segment (2 from C, 2 from D)."""
    decoder = RBDSDecoder()
    pi = 0x4FB5

    # segment 0, AB flag = 0
    b = _pack_block_b(group_type=2, version_b=False, tp=False, pty=0, low_bits=0x00)
    decoder.process_group((pi, b, (ord("H") << 8) | ord("e"), (ord("l") << 8) | ord("l")))

    # segment 1
    b = _pack_block_b(group_type=2, version_b=False, tp=False, pty=0, low_bits=0x01)
    decoder.process_group((pi, b, (ord("o") << 8) | ord(" "), (ord("R") << 8) | ord("T")))

    data = decoder.get_current_data()
    assert data.radio_text.startswith("Hello RT")


def test_group_2a_preserves_high_bit_characters():
    """RT mask must be 0xFF, not 0x7F.

    With the old 7-bit mask, an RDS character like 0xE9 ('é' in Annex E)
    was silently rewritten to 0x69 ('i'), producing a plausible but
    wrong ASCII character. After the fix, the high bit survives the
    mask; since the printable-ASCII filter in _update_radio_text still
    rejects codes >= 127, the slot shows as space rather than a lying
    ASCII character.
    """
    decoder = RBDSDecoder()
    pi = 0x4FB5

    b = _pack_block_b(group_type=2, version_b=False, tp=False, pty=0, low_bits=0x00)
    # Block C: two RDS-Annex-E chars (0xE9 0xE8 → 'é' 'è' in Latin locales).
    # Block D: plain ASCII so we can anchor the segment.
    decoder.process_group((pi, b, (0xE9 << 8) | 0xE8, (ord("a") << 8) | ord("b")))

    data = decoder.get_current_data()
    # Positions 0 and 1 should not be the wrong-ASCII fallback that the
    # 0x7F mask produced (0xE9 & 0x7F = 0x69 = 'i', 0xE8 & 0x7F = 0x68 = 'h').
    assert decoder.radio_text[0] != "i"
    assert decoder.radio_text[1] != "h"
    # Positions 2 and 3 from block D remain plain ASCII.
    assert decoder.radio_text[2] == "a"
    assert decoder.radio_text[3] == "b"
    # Stripping trims leading spaces, so the visible RT starts with "ab".
    assert data.radio_text.startswith("ab")


def test_pi_to_call_sign_four_letter_w():
    # Real-world example from production: PI 0x5862 is station WBKS.
    assert pi_to_call_sign(0x5862) == "WBKS"


def test_pi_to_call_sign_four_letter_k():
    # K-prefix algorithmic decode: 0x1000 -> KAAA, 0x54A7 -> KZZZ.
    assert pi_to_call_sign(0x1000) == "KAAA"
    assert pi_to_call_sign(0x54A7) == "KZZZ"


def test_pi_to_call_sign_w_boundary():
    # W-prefix boundary: 0x54A8 -> WAAA, 0x994F -> WZZZ.
    assert pi_to_call_sign(0x54A8) == "WAAA"
    assert pi_to_call_sign(0x994F) == "WZZZ"


def test_pi_to_call_sign_three_letter_legacy():
    # NRSC-4 Annex D.3 assigns explicit PI codes to legacy 3-letter calls.
    assert pi_to_call_sign(0x99A5) == "KDKA"
    assert pi_to_call_sign(0x9990) == "KYW"
    assert pi_to_call_sign(0x9950) == "WBZ"


def test_pi_to_call_sign_out_of_range():
    # European RDS codes and reserved ranges should not produce bogus calls.
    assert pi_to_call_sign(0x0FFF) is None  # below K range
    assert pi_to_call_sign(0x9A00) is None  # above W range + legacy table
    assert pi_to_call_sign(0xD340) is None  # typical European PI


def test_decoder_populates_call_sign_from_pi():
    decoder = RBDSDecoder()
    b = _pack_block_b(group_type=0, version_b=False, tp=False, pty=0, low_bits=0)
    decoder.process_group((0x5862, b, 0x0000, 0x2020))
    assert decoder.get_current_data().call_sign == "WBKS"


def test_decoder_clock_time_from_group_4a():
    """Group 4A: MJD 59935 = 2022-12-22, hour 17, minute 30, offset -5h
    (local offset = -10 half-hours = -5h)."""
    decoder = RBDSDecoder()
    # Block B low 5 bits = top 2 bits of MJD + group-type-fixed zeros
    mjd = 59935
    hour = 17
    minute = 30
    offset_half_hours = 10  # 5h
    offset_sign_bit = 1  # negative

    # Block B bits 1-0 = MJD bits 16..15
    b_low = (mjd >> 15) & 0x3
    b = _pack_block_b(group_type=4, version_b=False, tp=False, pty=0, low_bits=b_low)
    # Block C: MJD bits 14..0 shifted up by 1, plus hour MSB in bit 0
    c = ((mjd & 0x7FFF) << 1) | ((hour >> 4) & 0x1)
    # Block D: hour low 4 bits in 15..12, minute in 11..6, sign in bit 5, offset in 4..0
    d = ((hour & 0xF) << 12) | ((minute & 0x3F) << 6) | (offset_sign_bit << 5) | offset_half_hours

    decoder.process_group((0x5862, b, c, d))
    data = decoder.get_current_data()
    assert data.clock_time_utc is not None
    assert data.clock_time_utc.startswith("2022-12-22T17:30"), data.clock_time_utc
    # Local should be 17:30 - 5:00 = 12:30 on the same date.
    assert data.clock_time_local.startswith("2022-12-22T12:30"), data.clock_time_local


def test_decoder_pty_name_from_group_10a():
    decoder = RBDSDecoder()
    # First seed PTY so PTY-change logic doesn't reset on every group
    b0 = _pack_block_b(group_type=0, version_b=False, tp=False, pty=9, low_bits=0)
    decoder.process_group((0x5862, b0, 0x0000, 0x2020))

    # Group 10A segment 0 ("NEWS" - just an example)
    b = _pack_block_b(group_type=10, version_b=False, tp=False, pty=9, low_bits=0x00)
    decoder.process_group((0x5862, b, (ord("N") << 8) | ord("E"), (ord("W") << 8) | ord("S")))
    # Segment 1 (" CH 1")
    b = _pack_block_b(group_type=10, version_b=False, tp=False, pty=9, low_bits=0x01)
    decoder.process_group((0x5862, b, (ord(" ") << 8) | ord("C"), (ord("H") << 8) | ord("1")))

    assert decoder.get_current_data().pty_name == "NEWS CH1"


def test_decoder_di_bits_from_group_0():
    decoder = RBDSDecoder()

    # Address 3 -> stereo bit (d0). DI bit = 1 on segment 3.
    for addr, di in [(0, True), (1, False), (2, False), (3, True)]:
        low = (di << 2) | addr  # bit 2 = DI, bits 1..0 = address
        b = _pack_block_b(group_type=0, version_b=False, tp=False, pty=0, low_bits=low)
        decoder.process_group((0x5862, b, 0x0000, 0x2020))

    data = decoder.get_current_data()
    assert data.di_dynamic_pty is True    # address 0
    assert data.di_compressed is False    # address 1
    assert data.di_artificial_head is False  # address 2
    assert data.di_stereo is True         # address 3


def _send_ps_cycle(decoder, text: str, pi: int = 0x5862) -> None:
    """Send a complete PS cycle (all 4 segments of an 8-char PS)."""
    assert len(text) == 8
    for seg in range(4):
        b = _pack_block_b(group_type=0, version_b=False, tp=False, pty=0, low_bits=seg)
        c1, c2 = text[seg * 2], text[seg * 2 + 1]
        decoder.process_group((pi, b, 0x0000, (ord(c1) << 8) | ord(c2)))


def test_ps_name_requires_two_identical_cycles():
    """PS commits only after two consecutive identical full cycles.

    This debounces the 'Frankenstein blend' failure mode where four
    segments from two different rotating PS strings interleave across
    four distinct addresses (no per-segment conflict to catch) and
    spell out 8 chars that were never broadcast together.
    """
    decoder = RBDSDecoder()
    _send_ps_cycle(decoder, "KISS-FM ")
    assert "".join(decoder.ps_name) == " " * 8, "first cycle must not commit"
    _send_ps_cycle(decoder, "KISS-FM ")
    assert "".join(decoder.ps_name) == "KISS-FM "


def test_ps_name_follows_dynamic_ps_rotation():
    """Rotating PS transitions cleanly once each new string repeats."""
    decoder = RBDSDecoder()
    for _ in range(2):
        _send_ps_cycle(decoder, "KISS-FM ")
    assert "".join(decoder.ps_name) == "KISS-FM "

    # One rotation to a different string doesn't update yet — candidate
    # needs confirmation.
    _send_ps_cycle(decoder, "93-9 FM ")
    assert "".join(decoder.ps_name) == "KISS-FM "
    # The station's next cycle of '93-9 FM ' confirms it.
    _send_ps_cycle(decoder, "93-9 FM ")
    assert "".join(decoder.ps_name) == "93-9 FM "


def test_ps_name_rejects_single_blended_cycle():
    """A single cycle built from segments of two different PS strings
    must not commit — the four-address blend could decode any plausible
    8 chars and would corrupt the display.
    """
    decoder = RBDSDecoder()
    for _ in range(2):
        _send_ps_cycle(decoder, "KISS-FM ")
    assert "".join(decoder.ps_name) == "KISS-FM "

    # One cycle's worth of segments, each drawn from a different PS.
    # "K", "I" from 'KISS-FM ', "-", "9" from '93-9 FM ', " ", "F"
    # from '93-9 FM ', "M", " " from 'KISS-FM '.
    for seg, pair in enumerate([("K", "I"), ("-", "9"), (" ", "F"), ("M", " ")]):
        b = _pack_block_b(group_type=0, version_b=False, tp=False, pty=0, low_bits=seg)
        decoder.process_group((0x5862, b, 0x0000, (ord(pair[0]) << 8) | ord(pair[1])))
    assert "".join(decoder.ps_name) == "KISS-FM ", \
        f"blended cycle committed: {decoder.ps_name}"


def test_radio_text_grows_when_station_extends_without_cr():
    """Some stations change their RT without re-sending 0x0D or toggling
    the A/B flag; the decoder must let the visible length grow back out
    when non-space characters arrive past the current terminator.
    """
    decoder = RBDSDecoder()
    b0 = _pack_block_b(group_type=2, version_b=False, tp=False, pty=0, low_bits=0x00)
    # Initial RT: "Hi!\r"  → terminator at 3
    decoder.process_group((0x5862, b0, (ord("H") << 8) | ord("i"), (ord("!") << 8) | 0x0D))
    assert decoder.get_current_data().radio_text == "Hi!"

    # Station re-broadcasts segment 0 with a space in place of the CR,
    # then fills segment 1 with "Worl" — the RT should grow back out.
    decoder.process_group((0x5862, b0, (ord("H") << 8) | ord("i"), (ord("!") << 8) | ord(" ")))
    b1 = _pack_block_b(group_type=2, version_b=False, tp=False, pty=0, low_bits=0x01)
    decoder.process_group((0x5862, b1, (ord("W") << 8) | ord("o"), (ord("r") << 8) | ord("l")))
    assert decoder.get_current_data().radio_text == "Hi! Worl"


def test_radio_text_drops_padding_past_terminator():
    """Spaces (padding) arriving in a later segment past a terminator
    must not extend the RT — only real non-space content should.
    """
    decoder = RBDSDecoder()
    b0 = _pack_block_b(group_type=2, version_b=False, tp=False, pty=0, low_bits=0x00)
    decoder.process_group((0x5862, b0, (ord("H") << 8) | ord("i"), (ord("!") << 8) | 0x0D))
    b1 = _pack_block_b(group_type=2, version_b=False, tp=False, pty=0, low_bits=0x01)
    decoder.process_group((0x5862, b1, (ord(" ") << 8) | ord(" "), (ord(" ") << 8) | ord(" ")))
    assert decoder.get_current_data().radio_text == "Hi!"


def test_radio_text_trims_at_carriage_return():
    """Per RDS spec, 0x0D ends the Radio Text; anything past it must not be shown.

    Without this handling, stations that terminate RT short of 64 chars and
    pad the rest with spaces or junk would leak padding into the display.
    """
    decoder = RBDSDecoder()

    # Segment 0: "Hell"
    b = _pack_block_b(group_type=2, version_b=False, tp=False, pty=0, low_bits=0x00)
    decoder.process_group((0x5862, b, (ord("H") << 8) | ord("e"), (ord("l") << 8) | ord("l")))
    # Segment 1: "o!\r<junk>"  -- '!' then CR terminator, then padding
    b = _pack_block_b(group_type=2, version_b=False, tp=False, pty=0, low_bits=0x01)
    decoder.process_group((0x5862, b, (ord("o") << 8) | ord("!"), (0x0D << 8) | ord("X")))

    assert decoder.get_current_data().radio_text == "Hello!"


def test_group_2a_ab_flag_clears_buffer():
    """Toggling the RT A/B flag must clear the radio-text buffer."""
    decoder = RBDSDecoder()
    pi = 0x4FB5

    # First pass: AB=0, segment 0, "Hell"
    b = _pack_block_b(group_type=2, version_b=False, tp=False, pty=0, low_bits=0x00)
    decoder.process_group((pi, b, (ord("H") << 8) | ord("e"), (ord("l") << 8) | ord("l")))
    assert decoder.radio_text[0] == "H"

    # Flip AB flag: buffer must reset regardless of segment number
    b = _pack_block_b(group_type=2, version_b=False, tp=False, pty=0, low_bits=0x10)
    decoder.process_group((pi, b, (ord("N") << 8) | ord("e"), (ord("w") << 8) | ord(" ")))
    assert decoder.radio_text[0] == "N"
    assert decoder.radio_text[1] == "e"
    # Position 4+ must still be space: earlier "Hell" was cleared.
    assert all(c == " " for c in decoder.radio_text[4:])


def test_fmdemodulator_tracks_sample_index():
    """FMDemodulator._sample_index must advance by the multiplex length each call.

    On the very first call there is no previous IQ sample to prepend, so the
    FM discriminator yields len(iq) - 1 multiplex samples.  On every subsequent
    call the demodulator prepends the last IQ sample, yielding exactly len(iq)
    multiplex samples.  The _sample_index must reflect this accurately so that
    the RBDS worker receives the correct absolute stream offset.
    """
    demod = _make_demodulator(sample_rate=200_000)
    assert demod._sample_index == 0

    chunk = np.exp(1j * 2 * np.pi * 0.01 * np.arange(1024)).astype(np.complex64)

    demod.process(chunk)
    # First call: no previous sample prepended → fm_discriminator produces 1023 samples
    first_call_multiplex_len = len(chunk) - 1
    assert demod._sample_index == first_call_multiplex_len

    demod.process(chunk)
    # Second call: previous sample prepended → fm_discriminator produces 1024 samples
    assert demod._sample_index == first_call_multiplex_len + len(chunk)

    demod.stop()
    time.sleep(0.05)


# ---------------------------------------------------------------------------
# New group decoder tests (full RBDS specification)
# ---------------------------------------------------------------------------

def _pack_group1a_b(tp: bool, pty: int, variant: int) -> int:
    return (
        (1 << 12)
        | (0 << 11)
        | ((1 if tp else 0) << 10)
        | ((pty & 0x1F) << 5)
        | ((variant & 0x7) << 2)
    )


def test_group_0a_decodes_af_list():
    """Group 0A Block C with two direct AF codes → af_list contains two frequencies."""
    decoder = RBDSDecoder()
    # AF codes: 1 = 87.7 MHz, 2 = 87.8 MHz
    af_c = (1 << 8) | 2
    b = _pack_block_b(group_type=0, version_b=False, tp=False, pty=0, low_bits=0)
    decoder.process_group((0x5862, b, af_c, 0x2020))
    data = decoder.get_current_data()
    assert data.af_list is not None
    assert 87.7 in data.af_list
    assert 87.8 in data.af_list


def test_group_0a_af_list_capped_at_spec_maximum():
    """``_af_buffer`` must stop growing at 25 entries (RBDS spec maximum).

    Without a cap, a noisy signal where bad-but-CRC-passing 0A groups keep
    delivering distinct AF codes would grow this list (and the JSON payload
    sent to the dashboard) without bound — a slow memory leak.  The RBDS
    spec limits an AF list to 25 entries (Method A count codes 224..249
    encode 0..25), so anything beyond that is by definition spurious.
    """
    decoder = RBDSDecoder()
    b = _pack_block_b(group_type=0, version_b=False, tp=False, pty=0, low_bits=0)
    # Push 60 unique AF codes (1..120, two per group). Without the cap this
    # would leave 60 entries in af_list; with the cap it stops at 25.
    for code1 in range(1, 121, 2):
        code2 = code1 + 1
        af_c = (code1 << 8) | code2
        decoder.process_group((0x5862, b, af_c, 0x2020))
    data = decoder.get_current_data()
    assert data.af_list is not None
    assert len(data.af_list) == 25


def test_group_1a_decodes_language_code():
    """Group 1A, variant 0, Block D bits 7-0 = 0x09 → language_code=9, language_name='English'."""
    decoder = RBDSDecoder()
    b = _pack_group1a_b(tp=False, pty=0, variant=0)
    decoder.process_group((0x5862, b, 0x0000, 0x0009))
    data = decoder.get_current_data()
    assert data.language_code == 9
    assert data.language_name == "English"


def test_group_1a_decodes_ecc():
    """Group 1A, variant 4, Block D bits 7-0 = 0xA0 → ecc=0xA0."""
    decoder = RBDSDecoder()
    b = _pack_group1a_b(tp=False, pty=0, variant=4)
    decoder.process_group((0x5862, b, 0x0000, 0x00A0))
    data = decoder.get_current_data()
    assert data.ecc == 0xA0


def test_group_1a_decodes_pin():
    """Group 1A Block C day=15, hour=13, minute=30 → pin_day=15, pin_hour=13, pin_minute=30."""
    decoder = RBDSDecoder()
    # Block C: bits 15-11=day, bits 10-6=hour, bits 5-0=minute
    pin_c = (15 << 11) | (13 << 6) | 30
    b = _pack_group1a_b(tp=False, pty=0, variant=0)
    decoder.process_group((0x5862, b, pin_c, 0x0000))
    data = decoder.get_current_data()
    assert data.pin_day == 15
    assert data.pin_hour == 13
    assert data.pin_minute == 30


def test_group_1a_decodes_linkage():
    """Group 1A, variant 5, LA=1, SC=0, LSN=0x042 → linkage_actuator=True, linkage_set_number=0x042."""
    decoder = RBDSDecoder()
    b = _pack_group1a_b(tp=False, pty=0, variant=5)
    # Block D: bit 15=LA=1, bit 14=SC=0, bits 11-0=LSN=0x042
    d = (1 << 15) | (0 << 14) | 0x042
    decoder.process_group((0x5862, b, 0x0000, d))
    data = decoder.get_current_data()
    assert data.linkage_actuator is True
    assert data.linkage_soft_coupling is False
    assert data.linkage_set_number == 0x042


def test_group_3a_registers_oda_app():
    """Group 3A, AID=0x4BD7 (RDS-TMC) → oda_apps contains 0x4BD7."""
    decoder = RBDSDecoder()
    # Block B: group_type=3, version_b=False, ODA group type bits in low 5
    b = _pack_block_b(group_type=3, version_b=False, tp=False, pty=0, low_bits=0x10)
    decoder.process_group((0x5862, b, 0x4BD7, 0x0000))
    data = decoder.get_current_data()
    assert data.oda_apps is not None
    assert 0x4BD7 in data.oda_apps


def test_group_5a_accumulates_tdc():
    """Group 5A, two groups with channel 0 → tdc_data has 8 bytes."""
    decoder = RBDSDecoder()
    b = _pack_block_b(group_type=5, version_b=False, tp=False, pty=0, low_bits=0x00)
    decoder.process_group((0x5862, b, 0x0102, 0x0304))
    decoder.process_group((0x5862, b, 0x0506, 0x0708))
    data = decoder.get_current_data()
    assert data.tdc_data is not None
    assert len(data.tdc_data) == 8


def test_group_8a_sets_tmc_present():
    """Group 8A → tmc_present=True."""
    decoder = RBDSDecoder()
    b = _pack_block_b(group_type=8, version_b=False, tp=False, pty=0, low_bits=0x00)
    decoder.process_group((0x5862, b, 0x0000, 0x0000))
    data = decoder.get_current_data()
    assert data.tmc_present is True


def test_group_9a_decodes_ews():
    """Group 9A, channel=5, C=0xABCD, D=0x1234 → ews_channel=5, ews_message_c=0xABCD, ews_message_d=0x1234."""
    decoder = RBDSDecoder()
    b = _pack_block_b(group_type=9, version_b=False, tp=False, pty=0, low_bits=0x05)
    decoder.process_group((0x5862, b, 0xABCD, 0x1234))
    data = decoder.get_current_data()
    assert data.ews_channel == 5
    assert data.ews_message_c == 0xABCD
    assert data.ews_message_d == 0x1234


def test_group_14a_decodes_eon_ps():
    """Four Group 14A groups, variants 0-3 → eon_list has one entry with correct PS name."""
    decoder = RBDSDecoder()
    eon_pi = 0x1234
    ps = "WXYZ-FM "
    for variant in range(4):
        low_bits = variant  # bits 3-0 = variant; bit 4 = eon_tp
        b = _pack_block_b(group_type=14, version_b=False, tp=False, pty=0, low_bits=low_bits)
        c1, c2 = ps[variant * 2], ps[variant * 2 + 1]
        decoder.process_group((0x5862, b, eon_pi, (ord(c1) << 8) | ord(c2)))
    data = decoder.get_current_data()
    assert data.eon_list is not None
    assert len(data.eon_list) == 1
    assert data.eon_list[0]['ps'].strip() == ps.strip()


def test_group_14b_updates_eon_ta():
    """Group 14B with TA=1 → eon entry has ta=True."""
    decoder = RBDSDecoder()
    eon_pi = 0xABCD
    # Block B bit 3 = eon_ta=1
    low_bits = (1 << 3)
    b = _pack_block_b(group_type=14, version_b=True, tp=False, pty=0, low_bits=low_bits)
    decoder.process_group((0x5862, b, eon_pi, 0x0000))
    data = decoder.get_current_data()
    assert data.eon_list is not None
    entry = next(e for e in data.eon_list if e['pi'] == f"{eon_pi:04X}")
    assert entry['ta'] is True


def test_group_15b_updates_fast_tp():
    """Group 15B with TP=1, TA=0 → fast_tp=True, fast_ta=False."""
    decoder = RBDSDecoder()
    # version_b=True, tp=True (bit 10 of B), bit 4 of low_bits = TA=0
    b = _pack_block_b(group_type=15, version_b=True, tp=True, pty=0, low_bits=0x00)
    decoder.process_group((0x5862, b, 0x0000, 0x2020))
    data = decoder.get_current_data()
    assert data.fast_tp is True
    assert data.fast_ta is False


def test_group_10b_decodes_pty_name():
    """Group 10B with 2 chars per segment → pty_name updated."""
    decoder = RBDSDecoder()
    # Seed PTY so PTY-change logic doesn't reset on every group
    b0 = _pack_block_b(group_type=0, version_b=False, tp=False, pty=5, low_bits=0)
    decoder.process_group((0x5862, b0, 0x0000, 0x2020))

    # Group 10B segment 0: "NE" in Block D
    b = _pack_block_b(group_type=10, version_b=True, tp=False, pty=5, low_bits=0x00)
    decoder.process_group((0x5862, b, 0x0000, (ord('N') << 8) | ord('E')))
    # Group 10B segment 1: "WS" in Block D
    b = _pack_block_b(group_type=10, version_b=True, tp=False, pty=5, low_bits=0x01)
    decoder.process_group((0x5862, b, 0x0000, (ord('W') << 8) | ord('S')))

    data = decoder.get_current_data()
    assert data.pty_name is not None
    assert "NE" in data.pty_name
    assert "WS" in data.pty_name


# ---------------------------------------------------------------------------
# Burst FEC regression tests
# ---------------------------------------------------------------------------

def _make_valid_block(worker: RBDSWorker, data: int, block_number: int) -> int:
    """Build a valid 26-bit RBDS block (data + CRC + offset word)."""
    offset_word = [252, 408, 360, 436, 848]
    crc = worker._calc_syndrome(data, 16)
    check = crc ^ offset_word[block_number]
    return (data << 10) | check


def _crc_ok(worker: RBDSWorker, block: int, block_number: int) -> bool:
    """Replicate the inner _crc_ok_for_block logic for test use."""
    offset_word = [252, 408, 360, 436, 848]
    dataword = (block >> 10) & 0xFFFF
    expected_crc = worker._calc_syndrome(dataword, 16)
    checkword = block & 0x3FF
    if block_number == 2:
        return (
            (checkword ^ offset_word[2]) == expected_crc
            or (checkword ^ offset_word[4]) == expected_crc
        )
    return (checkword ^ offset_word[block_number]) == expected_crc


def test_burst_table_contains_only_contiguous_masks():
    """Every mask in the burst correction table must be a contiguous run of bits.

    The Meggitt trapping decoder (NRSC-4-B §B.2.4) corrects contiguous burst
    errors only.  Including non-contiguous patterns (e.g. 0b101) inflates the
    table with entries that match random multi-bit noise, causing false-positive
    corrections that silently corrupt decoded PI codes and call letters.
    """
    worker = _make_worker()
    table = worker._burst_correction_table()

    for syndrome_val, mask in table.items():
        assert mask != 0, f"zero mask in burst table (syndrome={syndrome_val})"
        # A contiguous run has no internal zero bits: (mask >> trailing_zeros)
        # must be all-ones.
        trailing = (mask & -mask).bit_length() - 1
        shifted = mask >> trailing
        # All-ones check: shifted must be 2^k - 1 for some k ≥ 1
        popcount = bin(shifted).count('1')
        bit_len = shifted.bit_length()
        assert popcount == bit_len, (
            f"Non-contiguous mask 0b{mask:026b} found in burst table "
            f"(syndrome={syndrome_val}); burst FEC must only include "
            f"solid runs of bits to avoid false-positive corrections on noise."
        )

    worker.stop()


def test_burst_fec_corrects_contiguous_bursts_1_to_5():
    """Contiguous burst errors of 1-5 bits in a block A must be repaired."""
    worker = _make_worker()
    table = worker._burst_correction_table()
    offset_a = 252  # offset_word[0]

    for data in (0x4FB5, 0x1234, 0xABCD):
        valid_block = _make_valid_block(worker, data, 0)

        for burst_len in range(1, 6):
            for start in range(0, 26 - burst_len + 1, 4):  # sample positions
                burst_mask = ((1 << burst_len) - 1) << start
                corrupted = valid_block ^ burst_mask

                # Apply FEC: single-bit, then burst
                recovered_word = None
                for bit in range(26):
                    cand = corrupted ^ (1 << bit)
                    if _crc_ok(worker, cand, 0):
                        if recovered_word is None:
                            recovered_word = cand
                        else:
                            recovered_word = None
                            break

                if recovered_word is None:
                    codeword = corrupted ^ offset_a
                    syn = worker._calc_syndrome(codeword, 26)
                    if syn == 0:
                        recovered_word = corrupted
                    elif syn in table:
                        recovered_word = corrupted ^ table[syn]

                assert recovered_word is not None, (
                    f"Burst FEC failed to repair {burst_len}-bit burst at "
                    f"position {start} for data=0x{data:04X}"
                )
                recovered_data = (recovered_word >> 10) & 0xFFFF
                assert recovered_data == data, (
                    f"Burst FEC produced wrong data 0x{recovered_data:04X} "
                    f"(expected 0x{data:04X}) for {burst_len}-bit burst at "
                    f"position {start}"
                )

    worker.stop()


def test_burst_fec_no_false_positives_on_non_contiguous_errors():
    """Non-contiguous 2-bit errors must not produce extra false positives.

    Before the fix, the burst table included all sparse (non-contiguous)
    patterns such as 0b101, causing it to match random noise and return
    corrupted data as "corrected."  With contiguous-only patterns the only
    remaining false positives are inherent CRC collisions — where a
    non-contiguous 2-bit error pattern happens to share a syndrome with a
    true contiguous 1-bit burst.  The fix must not add any *extra* false
    positives beyond those inherent collisions.

    We enumerate every non-contiguous 2-bit error and verify that the only
    false-positive corrections come from syndromes that are legitimately in
    the (contiguous-only) burst table — never from patterns that were
    erroneously added by the old all-patterns algorithm.
    """
    worker = _make_worker()
    table = worker._burst_correction_table()
    offset_a = 252  # offset_word[0]

    data = 0x4FB5
    valid_block = _make_valid_block(worker, data, 0)

    # Count false positives and verify each one is an inherent CRC collision
    # (i.e., the 2-bit error's syndrome happens to match a contiguous entry).
    false_positives = 0
    non_inherent_fp = 0
    for bit_a in range(26):
        for bit_b in range(bit_a + 2, 26):  # gap ≥ 1 bit → non-contiguous
            error_mask = (1 << bit_a) | (1 << bit_b)
            corrupted = valid_block ^ error_mask

            # Apply FEC pipeline
            recovered_word = None
            for bit in range(26):
                cand = corrupted ^ (1 << bit)
                if _crc_ok(worker, cand, 0):
                    if recovered_word is None:
                        recovered_word = cand
                    else:
                        recovered_word = None
                        break

            if recovered_word is None:
                codeword = corrupted ^ offset_a
                syn = worker._calc_syndrome(codeword, 26)
                if syn == 0:
                    recovered_word = corrupted
                elif syn in table:
                    recovered_word = corrupted ^ table[syn]

            if recovered_word is not None:
                recovered_data = (recovered_word >> 10) & 0xFFFF
                if recovered_data != data:
                    false_positives += 1
                    # Classify: is this an inherent CRC collision?
                    # Inherent: the 2-bit error syndrome is also the syndrome
                    # of a contiguous burst in the table.  The fix only covers
                    # non-contiguous patterns being explicitly added.
                    raw_cw = valid_block ^ error_mask ^ offset_a
                    fp_syn = worker._calc_syndrome(raw_cw, 26)
                    if fp_syn not in table:
                        # FP triggered without matching table entry — impossible
                        # after fix (single-bit FEC found a wrong match, which
                        # would be a separate unrelated issue).
                        non_inherent_fp += 1

    # With the fix, all false positives are inherent CRC collisions only.
    assert non_inherent_fp == 0, (
        f"Found {non_inherent_fp} false-positive corrections NOT from inherent "
        f"CRC collisions; the burst table must contain only contiguous patterns."
    )
    # The total false positive count from inherent collisions must be low
    # (empirically 21 for the (26,16) RBDS code vs 300+ before the fix).
    assert false_positives <= 30, (
        f"Too many false-positive corrections ({false_positives}); "
        f"the burst FEC table likely contains non-contiguous patterns."
    )

    worker.stop()
