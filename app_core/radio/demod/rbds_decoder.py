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

"""RBDS group decoding and field-confirmation state machine."""

import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple


from .rbds_constants import (
    RBDS_LANGUAGE_CODES,
    RT_PLUS_AID,
    RT_PLUS_CONTENT_TYPES,
    pi_to_call_sign,
)
from .types import (
    RBDSData,
)

logger = logging.getLogger(__name__)

# Sentinel for "no pending candidate" in the two-sighting confirmation
# gate.  Cannot use None because None/False/0 are all legitimate pending
# field values (e.g. a TA=False candidate).
_CONFIRM_UNSET = object()


class RBDSDecoder:
    """
    RBDS/RDS decoder for FM radio.

    Decodes Program Service name, Radio Text, and other metadata from the
    57kHz RBDS subcarrier in FM broadcasts.
    """

    def __init__(self):
        self.pi_code = None
        self.call_sign = None
        self.ps_name = [' '] * 8  # 8 characters
        self.radio_text = [' '] * 64
        # Length of the decoded Radio Text before any 0x0D terminator.
        # The RDS spec says a carriage-return ends the displayed text and
        # anything beyond it is padding that must not be shown.
        self._radio_text_len = 64
        # Index where the most-recent CR landed (0x0D arrived in a previous
        # group at this position).  Tracked so that if a later broadcast of
        # the same segment overwrites that exact index with a non-CR
        # character, the terminator can be released and the visible RT
        # allowed to grow back out.  ``None`` when no CR is in effect.
        self._radio_text_cr_index: Optional[int] = None
        self.pty = None
        self.pty_name = None
        self._pty_name_buf = [' '] * 8
        self._pty_name_ab = 0
        self.tp = None
        self.ta = None
        self.ms = None
        # Decoder Identification: 4 bits accumulated one-per-PS-segment
        self.di_stereo = None
        self.di_artificial_head = None
        self.di_compressed = None
        self.di_dynamic_pty = None
        self.clock_time_utc = None
        self.clock_time_local = None
        self._radio_text_ab = 0
        self._rt_saw_cr_this_group = False
        # Group 0A AF state
        self._af_buffer: List[float] = []
        self._af_method_a_count: Optional[int] = None
        # Method B / LF-MF follow-on indicator (code 250).  Doesn't tell
        # us anything about LF/MF AFs without further decoding, but the
        # presence of the marker is itself useful information.
        self._af_follow_on_indicator: bool = False
        # Method B mode flag and the tuning frequency captured from the
        # regional-variant marker pair (af1 == af2).  Method A and
        # Method B AFs both populate _af_buffer; this just exposes which
        # encoding the station used so receivers can correlate the list
        # against an actual tuning frequency.
        self._af_method_b: bool = False
        self._af_tuning_frequency: Optional[float] = None
        # Slow-labelling raw capture: every Group 1A variant byte we
        # observe, keyed by variant code (0-7).  Specific decoders for
        # variants 0/4/5 still produce semantic fields; this dict gives
        # the UI the raw 16-bit Block-D contents for *all* variants so
        # nothing the station broadcasts is silently dropped.
        self._slow_labelling_raw: Dict[int, int] = {}
        # Group 1A/1B PIN and slow labeling state
        self.pin_day: Optional[int] = None
        self.pin_hour: Optional[int] = None
        self.pin_minute: Optional[int] = None
        self.ecc: Optional[int] = None
        self.language_code: Optional[int] = None
        self.language_name: Optional[str] = None
        self.linkage_set_number: Optional[int] = None
        self.linkage_actuator: Optional[bool] = None
        self.linkage_soft_coupling: Optional[bool] = None
        # Group 1A variant-1: TMC identification provider code (12 bits).
        self.paging_tmc_id: Optional[int] = None
        # Group 1A variant-2: paging operator code (12 bits).
        self.paging_operator_code: Optional[int] = None
        # Group 1A variant-7: EWS slow-labelling channel identifier (12 bits).
        self.ews_channel_identifier: Optional[int] = None
        # Group 3A ODA state
        self._oda_app_map: Dict[int, int] = {}
        self.oda_apps: List[int] = []
        # RT+ (AID 0xCD46) state.  Populated when 3A registers RT+ on a
        # specific group type; the decoder then routes those groups to
        # _handle_rt_plus.
        self._rt_plus_item_running: Optional[bool] = None
        self._rt_plus_item_toggle: Optional[int] = None
        self._rt_plus_tags: Optional[List[dict]] = None
        # Per-AID raw ODA payload buffer.  For every registered AID that
        # we don't have a specific decoder for, we keep the most recent
        # (b_low5, c, d) bytes, a count of received groups, and a unix
        # timestamp.  Lets the UI display "0xC563: 12 groups, last
        # B-low=0x1A C=0x1234 D=0x5678" so unknown ODA traffic isn't
        # silently discarded — useful when stations broadcast custom
        # AIDs (eRT, custom paging, vendor data) we can't yet parse.
        self._oda_payloads: Dict[int, dict] = {}
        # Per-(group_type+version) traffic histogram populated in
        # process_group.  RBDSWorker.get_stats() merges this with its
        # own block-level counters into a single RBDSDecoderStats.
        self._group_type_counts: Dict[str, int] = {}
        # Group 5A/5B TDC state
        self._tdc_channels: Dict[int, List[int]] = {}
        # Group 7A / 13A paging buffers — each capped to the most recent
        # 16 messages.  Format is operator-defined so we only keep raw
        # bytes plus the segmentation hints.
        self._paging_messages: List[dict] = []
        self._enhanced_paging_messages: List[dict] = []
        # Group 6A/6B In-house state
        self.in_house_data: List[int] = []
        # Group 8A TMC state
        self.tmc_present: Optional[bool] = None
        # Group 9A EWS state
        self.ews_channel: Optional[int] = None
        self.ews_message_c: Optional[int] = None
        self.ews_message_d: Optional[int] = None
        # Group 14A/14B EON state
        self._eon_map: Dict[int, dict] = {}
        # Group 15B fast switching state
        self.fast_tp: Optional[bool] = None
        self.fast_ta: Optional[bool] = None
        self.fast_ms: Optional[bool] = None
        self.fast_di_bits: Optional[int] = None
        # Dynamic-PS cycle assembly. Stations that rotate multiple
        # 8-char PS strings send them one after another in complete
        # cycles of 4 segments (addresses 0..3). To avoid displaying
        # Frankenstein blends of two strings, accumulate segments into
        # a staging buffer and only copy to the visible ps_name once a
        # full self-consistent cycle has been observed. If a segment
        # contradicts a previously-seen address in the current cycle,
        # the station has begun a new PS and we discard the stale
        # staging data and start over with the new content.
        self._ps_pending = [' '] * 8
        self._ps_pending_mask = 0
        # Candidate PS (last *fully observed* cycle) and how many times
        # it has repeated. A candidate only promotes to ps_name after
        # being observed twice in a row, which prevents Frankenstein
        # blends (one segment from string A + one from string B
        # interleaving across four unique addresses would otherwise
        # look like a valid cycle).
        self._ps_candidate = None  # type: Optional[str]
        self._ps_candidate_count = 0
        # Two-sighting confirmation gate for single-shot fields (PI, PTY,
        # TP, TA, MS, DI bits, fast-switching flags, ODA registrations).
        # A new value must be observed in two consecutive groups before
        # it replaces the accepted state, so one corrupted block that
        # slips past the CRC — or gets "repaired" into the wrong codeword
        # by burst FEC — can never flip a published field on its own.
        # These fields repeat continuously on-air (PI/PTY/TP arrive in
        # every group, TA/MS in every Group 0), so the added latency is
        # one group spacing (~90 ms to ~1 s).  Keys are attribute names
        # plus a few synthetic slot keys, so the dict stays bounded.
        self._confirm_pending: Dict[str, object] = {}
        # AF frequencies staged on first sighting; promoted to _af_buffer
        # on the second.  A corrupted Block C that decodes to a plausible
        # AF code would otherwise pollute the published AF list until the
        # next retune.  Insertion-ordered dict so noise can be evicted
        # oldest-first when the staging area fills.
        self._af_pending: Dict[float, bool] = {}
        # EON networks staged on first sighting of a new cross-referenced
        # PI (Group 14 Block C is a prime garbage-injection vector).
        # Dict rather than a single slot because stations interleave EON
        # groups across several real networks.
        self._eon_pending: Dict[int, bool] = {}
        # Field-churn counters surfaced through RBDSDecoderStats.  See
        # the dataclass comment for semantics.
        self.pi_change_count = 0
        self.pty_change_count = 0
        self.ta_toggle_count = 0
        self.glitches_rejected = 0

    def _confirm_value(self, key: str, current: object, new_value: object) -> bool:
        """Two-consecutive-sighting voting gate.

        Returns True when ``new_value`` differs from ``current`` AND has
        now been observed twice in a row, i.e. the caller should accept
        it.  A single observation only stages the value; if the next
        observation for the same key disagrees with the staged candidate
        the candidate is discarded (and counted in glitches_rejected),
        so an isolated false read can never be published.
        """
        if new_value == current:
            # Observation agrees with accepted state; any contrary
            # staged candidate was a one-off false read.
            if self._confirm_pending.pop(key, _CONFIRM_UNSET) is not _CONFIRM_UNSET:
                self.glitches_rejected += 1
            return False
        pending = self._confirm_pending.get(key, _CONFIRM_UNSET)
        if pending is not _CONFIRM_UNSET and pending == new_value:
            del self._confirm_pending[key]
            return True
        if pending is not _CONFIRM_UNSET:
            # Staged candidate contradicted by a different new value
            # before it could confirm.
            self.glitches_rejected += 1
        self._confirm_pending[key] = new_value
        return False

    def _confirmed_set(self, attr: str, new_value: object) -> bool:
        """Apply ``new_value`` to ``self.<attr>`` through the voting gate.

        Returns True only when the attribute actually changed (second
        consecutive sighting of a differing value).
        """
        if self._confirm_value(attr, getattr(self, attr), new_value):
            setattr(self, attr, new_value)
            return True
        return False

    def _stage_eon_pi(self, eon_pi: int) -> bool:
        """Second-sighting gate for new EON network entries.

        Group 14 Block C carries the cross-referenced PI directly, so a
        corrupted-but-CRC-passing block injects a phantom network into
        the EON table that persists until retune.  A new PI must be seen
        in two Group 14 broadcasts before an entry is created.  Returns
        True when the caller may create the entry now.
        """
        if eon_pi in self._eon_pending:
            del self._eon_pending[eon_pi]
            # Hard cap on tracked networks: EON addresses "other networks
            # of the same broadcaster" — real deployments carry a handful,
            # the protocol practically tops out well below this.
            return len(self._eon_map) < 32
        if len(self._eon_pending) >= 16:
            self._eon_pending.pop(next(iter(self._eon_pending)))
        self._eon_pending[eon_pi] = True
        return False

    def process_group(self, group_data: Tuple[int, int, int, int]) -> Optional[bool]:
        """
        Process a decoded RBDS group.

        Args:
            group_data: Tuple of four 16-bit RBDS blocks (A, B, C, D)

        Returns:
            True if metadata changed, otherwise False/None
        """
        a, b, c, d = group_data
        changed = False

        group_type = (b >> 12) & 0xF
        version_b = bool((b >> 11) & 0x1)
        logger.debug(
            "RBDS group: A=%04X B=%04X C=%04X D=%04X (type=%d%s)",
            a, b, c, d, group_type, "B" if version_b else "A"
        )

        # Tally this group into the per-type histogram so the UI can show
        # what mix of services this station broadcasts (e.g. "no 2A => no
        # Radio Text" is much clearer than just an empty RT panel).
        gt_key = f"{group_type}{'B' if version_b else 'A'}"
        self._group_type_counts[gt_key] = self._group_type_counts.get(gt_key, 0) + 1

        pi_code = f"{a:04X}"
        prev_pi = self.pi_code
        if self._confirmed_set('pi_code', pi_code):
            new_call = pi_to_call_sign(a)
            if new_call != self.call_sign:
                self.call_sign = new_call
            if prev_pi is not None:
                self.pi_change_count += 1
            changed = True

        pty = (b >> 5) & 0x1F
        prev_pty = self.pty
        if self._confirmed_set('pty', pty):
            # A PTY change invalidates any previously-decoded PTYN for the
            # old program type.
            self.pty_name = None
            self._pty_name_buf = [' '] * 8
            if prev_pty is not None:
                self.pty_change_count += 1
            changed = True

        tp = bool((b >> 10) & 0x1)
        if self._confirmed_set('tp', tp):
            changed = True

        # Bits 4-0 of Block B are group-type-dependent. TA (bit 4) and MS
        # (bit 3) are only defined for Group 0A/0B; in other groups those
        # bits carry unrelated payload (e.g. the RT A/B flag in Group 2,
        # MJD time bits in Group 4A), so extracting them unconditionally
        # would corrupt the flags each time a non-Group-0 group arrived.
        if group_type == 0:
            ta = bool((b >> 4) & 0x1)
            prev_ta = self.ta
            if self._confirmed_set('ta', ta):
                if prev_ta is not None:
                    self.ta_toggle_count += 1
                changed = True

            ms = bool((b >> 3) & 0x1)
            if self._confirmed_set('ms', ms):
                changed = True

            di_bit = bool((b >> 2) & 0x1)
            address = b & 0x3
            if self._update_di(address, di_bit):
                changed = True

            # Group 0A Block C: Alternative Frequencies (Method A).
            # Codes 1-204     -> direct VHF FM frequency 87.6 + 0.1*code MHz
            # Codes 205-223   -> filler / not used
            # Codes 224-249   -> AF list count (224 = "no AF", 225 = 1 AF, ... 249 = 25)
            # Code 250        -> LF/MF follow-on indicator (Method B)
            # Codes 251-255   -> reserved
            # Either byte of Block C may carry a count or follow-on code
            # paired with a direct code; surface both so the UI can mark
            # the AF list "complete" once enough direct codes have arrived.
            if not version_b:
                af1 = (c >> 8) & 0xFF
                af2 = c & 0xFF

                # Method B detection: a pair where both bytes are equal
                # direct codes is the "regional variant exists at this
                # frequency" / tuning-frequency marker (NRSC-4-B Annex C).
                # The presence of this marker tags the station as Method
                # B; the actual AF codes still arrive as direct values in
                # the regular pairs and populate af_list naturally, so we
                # only need to remember the tuning frequency for display.
                if af1 == af2 and 1 <= af1 <= 204:
                    tuning_mhz = round(87.6 + 0.1 * af1, 1)
                    if (not self._af_method_b
                            or self._af_tuning_frequency != tuning_mhz):
                        self._af_method_b = True
                        self._af_tuning_frequency = tuning_mhz
                        changed = True

                new_freqs = []
                for code in (af1, af2):
                    if 1 <= code <= 204:
                        new_freqs.append(round(87.6 + 0.1 * code, 1))
                    elif 224 <= code <= 249:
                        announced = code - 224  # number of AFs the station says follow
                        if self._af_method_a_count != announced:
                            self._af_method_a_count = announced
                            changed = True
                    elif code == 250:
                        if not self._af_follow_on_indicator:
                            self._af_follow_on_indicator = True
                            changed = True
                if new_freqs:
                    prev_len = len(self._af_buffer)
                    # Dedupe within the group (dict preserves order) so a
                    # Method-B marker pair (af1 == af2) still needs a
                    # second *group* to confirm, not just a second byte
                    # from the same possibly-corrupt block.
                    for f in dict.fromkeys(new_freqs):
                        # RBDS spec caps an AF list at 25 entries (Method A
                        # codes 224..249 encode counts 0..25).  Without a
                        # cap, a bad-CRC-but-presumed-valid block stream on
                        # a noisy signal can append distinct "frequencies"
                        # forever, slowly leaking memory and inflating
                        # serialised payloads sent to the dashboard.
                        if len(self._af_buffer) >= 25:
                            break
                        if f in self._af_buffer:
                            continue
                        # Second-sighting requirement: an AF only joins the
                        # published list once it has appeared in two
                        # separate groups.  AF lists cycle continuously on
                        # Group 0A, so real entries confirm within a few
                        # seconds; a corrupted-but-CRC-passing block that
                        # decodes to a plausible AF code stays staged and
                        # is eventually evicted instead of polluting the
                        # list until the next retune.
                        if f in self._af_pending:
                            del self._af_pending[f]
                            self._af_buffer.append(f)
                        else:
                            if len(self._af_pending) >= 32:
                                # Evict the oldest staged candidate —
                                # anything real will be re-staged by the
                                # station's ongoing AF cycle.
                                self._af_pending.pop(next(iter(self._af_pending)))
                            self._af_pending[f] = True
                    if len(self._af_buffer) != prev_len:
                        changed = True

            chars = d
            if self._update_ps_name(address, chars):
                changed = True
        elif group_type == 1 and not version_b:
            pin_day = (c >> 11) & 0x1F
            pin_hour = (c >> 6) & 0x1F
            pin_minute = c & 0x3F
            if pin_day > 0 and (self.pin_day != pin_day or self.pin_hour != pin_hour
                                 or self.pin_minute != pin_minute):
                self.pin_day, self.pin_hour, self.pin_minute = pin_day, pin_hour, pin_minute
                changed = True
            variant = (b >> 2) & 0x7
            if self._apply_group1_variant(variant, d):
                changed = True
        elif group_type == 1 and version_b:
            variant = (b >> 2) & 0x7
            if self._apply_group1_variant(variant, d):
                changed = True
        elif group_type == 2:
            text_segment = b & 0xF
            ab_flag = (b >> 4) & 0x1
            if ab_flag != self._radio_text_ab:
                self._radio_text_ab = ab_flag
                self.radio_text = [' '] * 64
                self._radio_text_len = 64
                self._radio_text_cr_index = None
                changed = True
            # Within this single group, any chars arriving after a 0x0D are
            # the padding that fills the final segment. Track it so
            # _update_radio_text can reject those without mistaking them
            # for the station extending its RT in a later broadcast.
            self._rt_saw_cr_this_group = False

            # RDS characters are 8-bit (Annex E of EN 50067 / Annex F of
            # NRSC-4). Masking to 0x7F strips the high bit and silently
            # corrupts anything in the upper half of the RDS character
            # table; use a full byte to stay consistent with PS decoding.
            if not version_b:
                blocks = (c, d)
                for offset, block in enumerate(blocks):
                    chars = [
                        (block >> 8) & 0xFF,
                        block & 0xFF,
                    ]
                    for i, code in enumerate(chars):
                        idx = text_segment * 4 + offset * 2 + i
                        if idx < len(self.radio_text):
                            if self._update_radio_text(idx, code):
                                changed = True
            else:
                chars = [(d >> 8) & 0xFF, d & 0xFF]
                for i, code in enumerate(chars):
                    idx = text_segment * 2 + i
                    if idx < len(self.radio_text):
                        if self._update_radio_text(idx, code):
                            changed = True
        elif group_type == 3 and not version_b:
            oda_group_type = (b >> 1) & 0xF
            oda_version = b & 0x1
            aid = c
            if aid != 0:
                key = (oda_group_type, oda_version)
                # ODA registrations go through the two-sighting gate too:
                # 3A groups repeat each assignment continuously, and a
                # corrupted Block C here would otherwise register a
                # garbage AID that then accumulates payload state forever.
                confirm_key = f"oda_slot_{oda_group_type}_{oda_version}"
                old_aid = self._oda_app_map.get(key)
                if self._confirm_value(confirm_key, old_aid, aid):
                    self._oda_app_map[key] = aid
                    # Evict the superseded AID (unless another slot still
                    # carries it) so oda_apps/_oda_payloads track only
                    # currently-registered applications.  Without this,
                    # slot churn fills the cap with stale AIDs and a
                    # *current* AID can no longer be listed or have its
                    # payload traffic tracked.
                    if (old_aid is not None and old_aid != aid
                            and old_aid not in self._oda_app_map.values()):
                        if old_aid in self.oda_apps:
                            self.oda_apps.remove(old_aid)
                        self._oda_payloads.pop(old_aid, None)
                    # With eviction above, oda_apps is bounded by the 32
                    # possible (group_type, version) slots; the explicit
                    # cap stays as belt-and-suspenders.
                    if aid not in self.oda_apps and len(self.oda_apps) < 32:
                        self.oda_apps.append(aid)
                    changed = True
        elif group_type == 4 and not version_b:
            # Group 4A: Clock Time and Date.
            # Block B bits 1-0 + Block C bits 15-1  -> MJD (17 bits)
            # Block C bit 0                         -> hour MSB
            # Block D bits 15-12                    -> hour LSBs (4 bits)
            # Block D bits 11-6                     -> minute (6 bits)
            # Block D bit 5                         -> local offset sign (0=+)
            # Block D bits 4-0                      -> local offset in half-hours
            mjd = ((b & 0x3) << 15) | ((c >> 1) & 0x7FFF)
            hour = ((c & 0x1) << 4) | ((d >> 12) & 0xF)
            minute = (d >> 6) & 0x3F
            offset_sign = -1 if (d >> 5) & 0x1 else 1
            offset_half_hours = d & 0x1F
            if self._update_clock_time(mjd, hour, minute, offset_sign, offset_half_hours):
                changed = True
        elif group_type == 5 and not version_b:
            raw = [(c >> 8) & 0xFF, c & 0xFF, (d >> 8) & 0xFF, d & 0xFF]
            self._accumulate_tdc(b & 0x1F, raw)
            changed = True
        elif group_type == 5 and version_b:
            self._accumulate_tdc(b & 0x1F, [(d >> 8) & 0xFF, d & 0xFF])
            changed = True
        elif group_type == 6 and not version_b:
            raw = [b & 0x1F, c, d]
            self.in_house_data = self.in_house_data[-15:] + raw
            changed = True
        elif group_type == 6 and version_b:
            raw = [b & 0x1F, d]
            self.in_house_data = self.in_house_data[-16:] + raw
            changed = True
        elif group_type == 7 and not version_b:
            # Group 7A: Radio Paging.  NRSC-4-B / IEC 62106 §5 leaves the
            # payload format to the paging operator (different operators
            # use PSWF / PSC / RDS-Paging-1).  We capture the raw bytes
            # plus the segmentation hints from Block B so downstream
            # systems can decode whichever paging dialect their local
            # broadcaster is using; the buffer is capped so a chatty
            # paging stream can't grow unbounded.
            paging_msg = {
                'a_b_flag': bool((b >> 4) & 0x1),
                'paging_segment': b & 0xF,
                'block_c': c,
                'block_d': d,
                'unix_ts': time.time(),
            }
            self._paging_messages.append(paging_msg)
            self._paging_messages = self._paging_messages[-16:]
            changed = True
            logger.debug("RBDS Group 7A (Paging): B=%04X C=%04X D=%04X", b, c, d)
        elif group_type == 13 and not version_b:
            # Group 13A: Enhanced Radio Paging.  Same situation as 7A —
            # the payload format is operator-defined, so we just keep
            # the raw bytes and let an external decoder handle them.
            erp_msg = {
                'block_b_low': b & 0x1F,
                'block_c': c,
                'block_d': d,
                'unix_ts': time.time(),
            }
            self._enhanced_paging_messages.append(erp_msg)
            self._enhanced_paging_messages = self._enhanced_paging_messages[-16:]
            changed = True
            logger.debug("RBDS Group 13A (ERP): B=%04X C=%04X D=%04X", b, c, d)
        elif group_type == 8 and not version_b:
            if not self.tmc_present:
                self.tmc_present = True
                changed = True
            logger.debug("RBDS Group 8A (TMC): B=%04X C=%04X D=%04X", b, c, d)
        elif group_type == 9 and not version_b:
            ews_channel = b & 0x1F
            if (self.ews_channel != ews_channel
                    or self.ews_message_c != c
                    or self.ews_message_d != d):
                self.ews_channel = ews_channel
                self.ews_message_c = c
                self.ews_message_d = d
                changed = True
                logger.info(
                    "RBDS EWS: channel=%d msg_c=0x%04X msg_d=0x%04X",
                    ews_channel, c, d
                )
        elif group_type == 10 and not version_b:
            # Group 10A: Program Type Name (8 chars in two 4-char segments).
            ab_flag = (b >> 4) & 0x1
            if ab_flag != self._pty_name_ab:
                self._pty_name_ab = ab_flag
                self._pty_name_buf = [' '] * 8
            segment = b & 0x1
            block_chars = [
                (c >> 8) & 0xFF, c & 0xFF,
                (d >> 8) & 0xFF, d & 0xFF,
            ]
            for i, code in enumerate(block_chars):
                idx = segment * 4 + i
                if idx < len(self._pty_name_buf):
                    char = chr(code) if 32 <= code < 127 else ' '
                    if self._pty_name_buf[idx] != char:
                        self._pty_name_buf[idx] = char
                        name = ''.join(self._pty_name_buf).strip()
                        if self.pty_name != name:
                            self.pty_name = name
                            changed = True
        elif group_type == 10 and version_b:
            segment = b & 0x1
            ab_flag = (b >> 4) & 0x1
            if ab_flag != self._pty_name_ab:
                self._pty_name_ab = ab_flag
                self._pty_name_buf = [' '] * 8
            block_chars = [(d >> 8) & 0xFF, d & 0xFF]
            for i, code in enumerate(block_chars):
                idx = segment * 2 + i
                if idx < len(self._pty_name_buf):
                    char = chr(code) if 32 <= code < 127 else ' '
                    if self._pty_name_buf[idx] != char:
                        self._pty_name_buf[idx] = char
                        name = ''.join(self._pty_name_buf).strip()
                        if self.pty_name != name:
                            self.pty_name = name
                            changed = True
        elif group_type == 14 and not version_b:
            variant = b & 0xF
            eon_tp = bool((b >> 4) & 0x1)
            eon_pi = c
            if eon_pi not in self._eon_map and self._stage_eon_pi(eon_pi):
                self._eon_map[eon_pi] = {
                    'pi': f"{eon_pi:04X}", 'tp': eon_tp, 'ps': ' ' * 8, 'af': []
                }
            # eon is None while a new PI is still staged (or the table is
            # at cap) — skip the variant payload for a network we haven't
            # admitted yet, but still fall through to the ODA dispatch
            # below in case the station registered an ODA on this slot.
            eon = self._eon_map.get(eon_pi)
            if eon is not None:
                eon['tp'] = eon_tp
                if variant <= 3:
                    ps_chars = [(d >> 8) & 0xFF, d & 0xFF]
                    ps_list = list(eon['ps'])
                    for i, code in enumerate(ps_chars):
                        idx = variant * 2 + i
                        if idx < 8:
                            ps_list[idx] = chr(code) if 32 <= code < 127 else ' '
                    eon['ps'] = ''.join(ps_list)
                elif variant == 4:
                    # Block D in EON variant 4 carries TWO 8-bit AF codes:
                    # high byte = mapped frequency for the cross-referenced
                    # programme, low byte = matched frequency for the tuned
                    # programme.  Earlier code dropped the low byte, halving
                    # EON AF coverage; capture both as direct codes 1..204.
                    for shift in (8, 0):
                        af_code = (d >> shift) & 0xFF
                        if 1 <= af_code <= 204:
                            af_mhz = round(87.6 + 0.1 * af_code, 1)
                            # Cap per-EON AF list at the RBDS spec maximum of
                            # 25 entries.  Same memory-leak rationale as the
                            # main station ``_af_buffer`` above: corrupt-but-
                            # CRC-passing blocks on a noisy signal otherwise
                            # grow this list unboundedly.
                            if af_mhz not in eon['af'] and len(eon['af']) < 25:
                                eon['af'].append(af_mhz)
                elif variant == 12:
                    eon['linkage'] = d
                elif variant == 13:
                    eon['pty'] = (d >> 11) & 0x1F
                    eon['ta'] = bool((d >> 0) & 0x1)
                elif variant == 14:
                    eon['pin_day'] = (d >> 11) & 0x1F
                    eon['pin_hour'] = (d >> 6) & 0x1F
                    eon['pin_minute'] = d & 0x3F
                changed = True
        elif group_type == 14 and version_b:
            eon_tp = bool((b >> 4) & 0x1)
            eon_ta = bool((b >> 3) & 0x1)
            eon_pi = c
            if eon_pi not in self._eon_map and self._stage_eon_pi(eon_pi):
                self._eon_map[eon_pi] = {
                    'pi': f"{eon_pi:04X}", 'tp': eon_tp, 'ta': eon_ta,
                    'ps': ' ' * 8, 'af': []
                }
            if eon_pi in self._eon_map:
                self._eon_map[eon_pi]['tp'] = eon_tp
                self._eon_map[eon_pi]['ta'] = eon_ta
                changed = True
        elif group_type == 15 and version_b:
            fast_ta = bool((b >> 4) & 0x1)
            fast_ms = bool((b >> 3) & 0x1)
            fast_di = bool((b >> 2) & 0x1)
            address = b & 0x3
            # Same two-sighting gate as the main flags.  15B exists for
            # fast switching, but stations that use it send it in bursts,
            # so confirmation still lands within one burst while a lone
            # corrupted 15B can no longer flap the fast flags.
            if self._confirmed_set('fast_tp', tp):
                changed = True
            if self._confirmed_set('fast_ta', fast_ta):
                changed = True
            if self._confirmed_set('fast_ms', fast_ms):
                changed = True
            # Accumulate the dedicated fast_di_bits nibble (bit per PS
            # segment address) through the same gate, so the UI's 15B
            # panel reflects what arrived on the fast channel.
            current_fast_di = (
                None if self.fast_di_bits is None
                else bool((self.fast_di_bits >> address) & 0x1)
            )
            if self._confirm_value(f'fast_di_{address}', current_fast_di, fast_di):
                bits = self.fast_di_bits or 0
                if fast_di:
                    bits |= (1 << address)
                else:
                    bits &= ~(1 << address)
                self.fast_di_bits = bits
                changed = True
            # 15B carries the same decoder-identification bits as Group 0
            # (EN 50067 §3.1.5.2), so they legitimately update the main DI
            # fields too — also behind the confirmation gate.
            if self._update_di(address, fast_di):
                changed = True
            if self._update_ps_name(address, d):
                changed = True

        # ODA payload dispatch.  The Group 3A handler (above) records which
        # (group_type, version) slots a station has assigned to ODA AIDs;
        # decode any payload group that matches a known AID.  RT+
        # (0xCD46) gets a real decoder; every other AID has its raw
        # payload captured into _oda_payloads so the UI can show that
        # something is being broadcast on the slot even when we can't
        # interpret it.
        oda_key = (group_type, 1 if version_b else 0)
        oda_aid = self._oda_app_map.get(oda_key)
        if oda_aid is not None:
            if oda_aid == RT_PLUS_AID:
                if self._handle_rt_plus(b, c, d):
                    changed = True
            elif oda_aid in self._oda_payloads or len(self._oda_payloads) < 32:
                # Capture the lower 5 bits of B (the payload nibble — the
                # rest of B is group-type / TP / PTY which we already
                # decoded) plus all of C and D.  Bump count and stamp
                # last-seen so the UI can show traffic activity per AID.
                # Capped at 32 AIDs (the number of registrable slots) so
                # this dict can't grow without bound across spurious
                # re-registrations on a long-running noisy receiver.
                entry = self._oda_payloads.setdefault(oda_aid, {
                    'aid': oda_aid,
                    'aid_hex': f"0x{oda_aid:04X}",
                    'group': f"{group_type}{'B' if version_b else 'A'}",
                    'count': 0,
                    'last_b_low': 0,
                    'last_c': 0,
                    'last_d': 0,
                    'last_seen_unix': 0.0,
                })
                entry['count'] += 1
                entry['last_b_low'] = b & 0x1F
                entry['last_c'] = c
                entry['last_d'] = d
                entry['last_seen_unix'] = time.time()
                changed = True

        return changed

    def _handle_rt_plus(self, b: int, c: int, d: int) -> bool:
        """Decode an RT+ payload group (AID 0xCD46) per RDS Forum R03/040.1.

        RT+ piggybacks on whatever group type the station registers via 3A
        (most US music stations use 11A).  Each group carries two
        (content_type, start, length) tag pointers into the current Radio
        Text buffer plus item-running / item-toggle bits announcing
        when a new programme item is on air.

        Block layout (16 bits each, MSB first):
            B[4]    : item toggle bit
            B[3]    : item running bit
            B[2:0]  : content type 1 high 3 bits
            C[15:13]: content type 1 low 3 bits  (6-bit total)
            C[12:7] : start marker 1 (0..63)
            C[6:1]  : length marker 1 (length-1, 0..63)
            C[0]    : content type 2 high 1 bit
            D[15:11]: content type 2 low 5 bits  (6-bit total)
            D[10:5] : start marker 2 (0..63)
            D[4:0]  : length marker 2 (length-1, 0..31)

        Returns True if any RT+ field changed.
        """
        item_toggle = (b >> 4) & 0x1
        item_running = bool((b >> 3) & 0x1)
        content_type_1 = ((b & 0x7) << 3) | ((c >> 13) & 0x7)
        start_1 = (c >> 7) & 0x3F
        length_1 = (c >> 1) & 0x3F
        content_type_2 = ((c & 0x1) << 5) | ((d >> 11) & 0x1F)
        start_2 = (d >> 5) & 0x3F
        length_2 = d & 0x1F

        rt_string = ''.join(self.radio_text[:self._radio_text_len])

        new_tags: List[dict] = []
        for ctype, start, length_field in (
            (content_type_1, start_1, length_1),
            (content_type_2, start_2, length_2),
        ):
            # Content type 0 ("DUMMY") signals "no tag in this slot" — used
            # when only one of the two tag pairs is meaningful for the
            # current programme item.  Skip it entirely.
            if ctype == 0:
                continue
            end = start + length_field + 1  # length field is length-minus-1
            if end > len(rt_string) or start >= len(rt_string):
                # Tag points outside the buffered RT.  This usually means
                # we have not yet received all the RT segments the station
                # is referencing; skip and wait for the next RT+ group
                # rather than emit a truncated artist/title.
                continue
            text = rt_string[start:end].strip()
            if not text:
                continue
            new_tags.append({
                'content_type': ctype,
                'content_type_name': RT_PLUS_CONTENT_TYPES.get(
                    ctype, f'TYPE_{ctype}'
                ),
                'text': text,
                'start': start,
                'length': length_field + 1,
            })

        changed = False
        if self._rt_plus_item_running != item_running:
            self._rt_plus_item_running = item_running
            changed = True
        if self._rt_plus_item_toggle != item_toggle:
            # Toggle flip => new programme item.  Replace tags even if
            # decode came back empty so the UI clears the prior song.
            self._rt_plus_item_toggle = item_toggle
            self._rt_plus_tags = new_tags or None
            changed = True
        elif new_tags and new_tags != self._rt_plus_tags:
            # Same item but text refined (RT extended, or station retransmits
            # with corrected content) — promote the newer tag list.
            self._rt_plus_tags = new_tags
            changed = True
        return changed

    def get_current_data(self) -> RBDSData:
        """Get the currently decoded RBDS data."""
        rt_chars = self.radio_text[:self._radio_text_len]

        # Derived PI breakdown — Annex D layout: 4 bits country code,
        # 4 bits area/coverage, 8 bits programme reference.  Surface raw
        # values; the UI is responsible for any region-specific naming.
        pi_country = pi_area = pi_program = None
        if self.pi_code:
            try:
                pi_int = int(self.pi_code, 16)
                pi_country = (pi_int >> 12) & 0xF
                pi_area = (pi_int >> 8) & 0xF
                pi_program = pi_int & 0xFF
            except ValueError:
                pass

        # Reconstruct the ODA assignment table: each entry says which
        # group/version slot a given AID lives on, with the AID rendered
        # in hex for direct comparison against vendor docs.
        oda_assignments: Optional[List[dict]] = None
        if self._oda_app_map:
            oda_assignments = []
            for (gt, ver), aid in sorted(self._oda_app_map.items()):
                entry = {
                    'group': f"{gt}{'B' if ver else 'A'}",
                    'group_type': gt,
                    'version_b': bool(ver),
                    'aid': aid,
                    'aid_hex': f"0x{aid:04X}",
                }
                if aid == RT_PLUS_AID:
                    entry['name'] = 'RT+'
                oda_assignments.append(entry)

        return RBDSData(
            pi_code=self.pi_code,
            pi_country_code=pi_country,
            pi_area_code=pi_area,
            pi_program_ref=pi_program,
            call_sign=self.call_sign,
            ps_name=''.join(self.ps_name).strip(),
            pty_name=self.pty_name,
            radio_text=''.join(rt_chars).strip(),
            radio_text_ab=self._radio_text_ab,
            pty=self.pty,
            tp=self.tp,
            ta=self.ta,
            ms=self.ms,
            di_stereo=self.di_stereo,
            di_artificial_head=self.di_artificial_head,
            di_compressed=self.di_compressed,
            di_dynamic_pty=self.di_dynamic_pty,
            clock_time_utc=self.clock_time_utc,
            clock_time_local=self.clock_time_local,
            af_list=sorted(self._af_buffer) if self._af_buffer else None,
            af_method_a_count=self._af_method_a_count,
            af_follow_on_indicator=(
                True if self._af_follow_on_indicator else None
            ),
            af_method_b=(True if self._af_method_b else None),
            af_tuning_frequency=self._af_tuning_frequency,
            pin_day=self.pin_day,
            pin_hour=self.pin_hour,
            pin_minute=self.pin_minute,
            ecc=self.ecc,
            language_code=self.language_code,
            language_name=self.language_name,
            linkage_set_number=self.linkage_set_number,
            linkage_actuator=self.linkage_actuator,
            linkage_soft_coupling=self.linkage_soft_coupling,
            paging_tmc_id=self.paging_tmc_id,
            paging_operator_code=self.paging_operator_code,
            ews_channel_identifier=self.ews_channel_identifier,
            slow_labelling_raw=(
                dict(self._slow_labelling_raw)
                if self._slow_labelling_raw else None
            ),
            oda_apps=list(self.oda_apps) if self.oda_apps else None,
            oda_assignments=oda_assignments,
            oda_payloads=(
                [dict(v) for v in self._oda_payloads.values()]
                if self._oda_payloads else None
            ),
            paging_messages=(
                [dict(m) for m in self._paging_messages]
                if self._paging_messages else None
            ),
            enhanced_paging_messages=(
                [dict(m) for m in self._enhanced_paging_messages]
                if self._enhanced_paging_messages else None
            ),
            tdc_data=bytes(self._tdc_channels.get(0, [])) if self._tdc_channels else None,
            tdc_channels=(
                {ch: bytes(buf) for ch, buf in self._tdc_channels.items() if buf}
                if self._tdc_channels else None
            ),
            in_house_data=list(self.in_house_data) if self.in_house_data else None,
            tmc_present=self.tmc_present,
            ews_channel=self.ews_channel,
            ews_message_c=self.ews_message_c,
            ews_message_d=self.ews_message_d,
            eon_list=list(self._eon_map.values()) if self._eon_map else None,
            fast_tp=self.fast_tp,
            fast_ta=self.fast_ta,
            fast_ms=self.fast_ms,
            fast_di_bits=self.fast_di_bits,
            rt_plus_item_running=self._rt_plus_item_running,
            rt_plus_item_toggle=self._rt_plus_item_toggle,
            rt_plus_tags=(
                [dict(t) for t in self._rt_plus_tags]
                if self._rt_plus_tags else None
            ),
        )

    def _apply_group1_variant(self, variant: int, d: int) -> bool:
        """Process a Group 1A/1B slow-labelling variant payload.

        Variants 0/4/5 produce semantic fields (language code, ECC,
        linkage); for completeness every variant — including 1/2/3/6/7
        which the spec leaves loosely defined or assigns to paging /
        TMC ID / EWS slow-labelling pointer — has its raw 16-bit Block-D
        contents captured into _slow_labelling_raw, keyed by variant
        number, so the UI can show "variant N said XXXX" even for codes
        no decoder understands.

        Returns True if any field changed.
        """
        # Always store the raw byte first.  Even when a specific decoder
        # below picks fields out of d we keep the raw word so the UI can
        # show low-level diagnostics next to the interpreted value.
        changed_raw = (
            self._slow_labelling_raw.get(variant) != d
        )
        if changed_raw:
            self._slow_labelling_raw[variant] = d

        changed_decoded = False
        if variant == 0:
            # Per the existing implementation: variant 0 has historically
            # been used for the legacy language code on some installations
            # (RBDS pre-2005 supplements).  Keep the behaviour but only
            # consider it a "language" update when the byte is in range.
            lang = d & 0xFF
            if lang != 0 and self.language_code != lang:
                self.language_code = lang
                self.language_name = RBDS_LANGUAGE_CODES.get(lang)
                changed_decoded = True
        elif variant == 1:
            # Variant 1 is reserved/local in NRSC-4-B; some EU stations
            # use it for "TMC identification" carrying a 12-bit TMC
            # provider code in d[11:0].  Capture it as a structured value.
            tmc_id = d & 0x0FFF
            if self.paging_tmc_id != tmc_id:
                self.paging_tmc_id = tmc_id
                changed_decoded = True
        elif variant == 2:
            # Variant 2: Paging Identification (operator code in d[11:0]
            # plus 4 bits of operator-defined subfield in d[15:12]).
            paging_op = d & 0x0FFF
            if self.paging_operator_code != paging_op:
                self.paging_operator_code = paging_op
                changed_decoded = True
        elif variant == 3:
            # Variant 3: legacy language-code assignment used by some
            # EU broadcasters in place of variant 0.  Treat identically.
            lang = d & 0xFF
            if lang != 0 and self.language_code != lang:
                self.language_code = lang
                self.language_name = RBDS_LANGUAGE_CODES.get(lang)
                changed_decoded = True
        elif variant == 4:
            ecc_val = d & 0xFF
            if ecc_val != 0 and self.ecc != ecc_val:
                self.ecc = ecc_val
                changed_decoded = True
        elif variant == 5:
            lsn = d & 0x0FFF
            la = bool((d >> 15) & 0x1)
            sc = bool((d >> 14) & 0x1)
            if self.linkage_set_number != lsn:
                self.linkage_set_number = lsn
                self.linkage_actuator = la
                self.linkage_soft_coupling = sc
                changed_decoded = True
        elif variant == 6:
            # Variant 6: broadcaster-use 16 bits.  No standard interpretation,
            # but we expose it raw in the slow-labelling table above; nothing
            # extra to compute.
            pass
        elif variant == 7:
            # Variant 7: EWS channel identifier slow-labelling pointer.
            # Carries a 12-bit EWS service identifier in d[11:0] that
            # tells receivers which EWS provider feeds Group 9A.  Useful
            # diagnostic alongside the actual EWS messages.
            ews_id = d & 0x0FFF
            if self.ews_channel_identifier != ews_id:
                self.ews_channel_identifier = ews_id
                changed_decoded = True
        return changed_raw or changed_decoded

    def _accumulate_tdc(self, channel: int, raw: list) -> None:
        """Append TDC bytes to a channel buffer, capped at 256 bytes."""
        if channel not in self._tdc_channels:
            self._tdc_channels[channel] = []
        self._tdc_channels[channel].extend(raw)
        self._tdc_channels[channel] = self._tdc_channels[channel][-256:]

    def _update_ps_name(self, address: int, chars: int) -> bool:
        """Stage PS segments into a pending buffer, display once a full
        4-segment cycle has been observed as self-consistent.

        Stations that broadcast *dynamic PS* rotate through multiple
        8-char strings ("KISS-FM ", station slogan, song title, ...) by
        sending each one as a complete cycle of four segments (address
        0..3). If we committed each segment the moment it arrived, the
        displayed PS would blend bytes from two different strings
        whenever segments from different rotation slots interleaved —
        "93.9 FM " and "Kiss-FM " can end up rendered as "93si-FM ".

        Approach: keep a pending 8-char buffer and a 4-bit 'segments
        seen' mask. When a new segment arrives at an address that was
        already set in the current cycle:
          - If its content matches what we already staged → keep going.
          - Otherwise → the station started broadcasting a new PS;
            discard staging and restart with just this segment.
        When all four segments of a single cycle have been seen
        consistently, copy pending to the visible ps_name.
        """
        idx = address * 2
        chars_pair = [
            chr((chars >> 8) & 0xFF) if 32 <= ((chars >> 8) & 0xFF) < 127 else ' ',
            chr(chars & 0xFF) if 32 <= (chars & 0xFF) < 127 else ' ',
        ]
        bit = 1 << address
        if self._ps_pending_mask & bit:
            # Already staged this segment in the current cycle — is it
            # still the same string?
            if (self._ps_pending[idx] != chars_pair[0] or
                    self._ps_pending[idx + 1] != chars_pair[1]):
                # Station has started broadcasting a different PS.
                # Discard staging and restart with just this segment.
                self._ps_pending = [' '] * 8
                self._ps_pending_mask = 0
        self._ps_pending[idx] = chars_pair[0]
        self._ps_pending[idx + 1] = chars_pair[1]
        self._ps_pending_mask |= bit

        if self._ps_pending_mask != 0xF:
            return False
        # A full cycle has been observed. Don't promote yet — require a
        # second identical cycle to commit, which filters out blended
        # mixes of two different rotation strings (the four segments
        # from A and B can interleave without conflict because each
        # address appears only once per cycle, so "no conflict" alone
        # isn't enough evidence that the 8 chars all came from the
        # same PS string).
        candidate = ''.join(self._ps_pending)
        if candidate == self._ps_candidate:
            self._ps_candidate_count += 1
        else:
            self._ps_candidate = candidate
            self._ps_candidate_count = 1
        # Start a fresh pending cycle for the next 4 segments.
        self._ps_pending = [' '] * 8
        self._ps_pending_mask = 0
        if self._ps_candidate_count < 2:
            return False
        # Two consecutive identical cycles — promote to the visible PS.
        updated = False
        for i, ch in enumerate(candidate):
            if self.ps_name[i] != ch:
                self.ps_name[i] = ch
                updated = True
        return updated

    def _update_radio_text(self, index: int, code: int) -> bool:
        if index >= len(self.radio_text):
            return False
        # RDS spec: 0x0D (carriage return) terminates the Radio Text.
        # Everything that follows 0x0D *within the same group* is padding.
        if code == 0x0D:
            self._rt_saw_cr_this_group = True
            self._radio_text_cr_index = index
            if self._radio_text_len > index:
                self._radio_text_len = index
                return True
            return False
        # Post-CR characters in this same group are padding → drop.
        if self._rt_saw_cr_this_group and index >= self._radio_text_len:
            return False
        # If a *previous* group placed a CR at this exact index and the
        # station is now broadcasting a non-CR byte at the same slot, the
        # CR is no longer in effect — release the terminator so later
        # segments can extend the displayed RT.  Bare padding past the old
        # terminator (a different index) is still rejected below, so a
        # CRC-lucky garbage byte in some unrelated segment can't drag junk
        # into the display.
        if (
            not self._rt_saw_cr_this_group
            and self._radio_text_cr_index is not None
            and index == self._radio_text_cr_index
        ):
            self._radio_text_cr_index = None
            self._radio_text_len = len(self.radio_text)
        char = chr(code) if 32 <= code < 127 else ' '
        # Characters past the current terminator are padding by default.
        # An earlier pass extended the length on any non-space byte, but
        # that let a single CRC-lucky garbage byte drag trailing junk
        # into the displayed RT ("93.9 KISS-FM ... )["). Always drop
        # past-terminator writes — when the station changes RT it should
        # toggle the A/B flag (which clears everything) or re-send a
        # later CR (which moves the terminator accordingly). This is
        # conservative but matches how car receivers behave.
        if index >= self._radio_text_len:
            return False
        if self.radio_text[index] != char:
            self.radio_text[index] = char
            return True
        return False

    def _update_di(self, address: int, di_bit: bool) -> bool:
        """Apply one DI (Decoder Identification) bit. The four bits are
        delivered across the four PS segments (address 0-3) and together
        describe the audio programme properties.

            address 0 -> d3: dynamic PTY indicator
            address 1 -> d2: compressed audio
            address 2 -> d1: artificial head / binaural
            address 3 -> d0: stereo / mono
        """
        attr = {
            0: "di_dynamic_pty",
            1: "di_compressed",
            2: "di_artificial_head",
            3: "di_stereo",
        }.get(address)
        if attr is None:
            return False
        # Routed through the two-sighting gate: each DI bit repeats once
        # per PS cycle (~1 s), so confirmation costs one extra cycle and
        # stops a single corrupt Group 0 from flapping e.g. stereo/mono.
        return self._confirmed_set(attr, di_bit)

    def _update_clock_time(
        self,
        mjd: int,
        hour: int,
        minute: int,
        offset_sign: int,
        offset_half_hours: int,
    ) -> bool:
        """Decode a Group 4A clock-time / date payload into ISO-8601
        UTC and local timestamps. MJD is the Modified Julian Date; hour
        and minute are UTC; offset is the local-time offset in signed
        half-hours. Returns True if either stored timestamp changed."""
        # Reject obviously malformed broadcasts (some stations pad with
        # zeros or never set MJD). MJD 40587 == 1970-01-01.
        if mjd < 40587 or hour > 23 or minute > 59 or offset_half_hours > 47:
            return False
        # MJD -> Gregorian date (Jean Meeus, Astronomical Algorithms ch. 7).
        jd = mjd + 2400001  # integer Julian Day Number at 00:00 UT
        a_ = jd + 32044
        b_ = (4 * a_ + 3) // 146097
        c_ = a_ - (146097 * b_) // 4
        d_ = (4 * c_ + 3) // 1461
        e_ = c_ - (1461 * d_) // 4
        m_ = (5 * e_ + 2) // 153
        day = e_ - (153 * m_ + 2) // 5 + 1
        month = m_ + 3 - 12 * (m_ // 10)
        year = 100 * b_ + d_ - 4800 + m_ // 10
        try:
            utc_dt = datetime(year, month, day, hour, minute, tzinfo=timezone.utc)
        except ValueError:
            return False
        local_dt = utc_dt + timedelta(minutes=30 * offset_sign * offset_half_hours)
        utc_iso = utc_dt.isoformat()
        local_iso = local_dt.replace(tzinfo=None).isoformat()
        changed = False
        if self.clock_time_utc != utc_iso:
            self.clock_time_utc = utc_iso
            changed = True
        if self.clock_time_local != local_iso:
            self.clock_time_local = local_iso
            changed = True
        return changed

