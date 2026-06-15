"""Tests for VTEC parsing utilities in app_utils/vtec.py.

These cover the four NWSI 10-1703-conformance fixes:

  1. vtec_year is anchored on begin time (NEW issuance year) so an EXT that
     pushes the end time across a calendar-year boundary does not break the
     (office, phenomenon, significance, etn, year) chain key (§2.1.6).
  2. When a segment carries paired UPG/NEW or CAN/NEW P-VTEC strings, the
     primary identity is the second (new) event, not the first (ending) event
     (§3.1, Table 2).
  3. The significance regex matches only W/A/Y/S/F/O/N (Appendix A).
  4. COR is in VTEC_SKIP_ACTIONS, not VTEC_BROADCAST_ACTIONS (§2.1.2).
"""

from __future__ import annotations

import pytest

from datetime import datetime, timezone

from app_utils.vtec import (
    VTEC_BROADCAST_ACTIONS,
    VTEC_SIGNIFICANCE,
    VTEC_SKIP_ACTIONS,
    VTEC_TERMINAL_ACTIONS,
    extract_vtec_identity,
    is_cancellation,
    parse_vtec_display,
    terminal_chain_updates,
)


def _raw(*vtec_strings: str) -> dict:
    """Build a minimal raw_json with the given VTEC strings."""
    return {
        'properties': {
            'parameters': {
                'VTEC': list(vtec_strings),
            }
        }
    }


# ---------------------------------------------------------------------------
# 1. Year anchored on begin time
# ---------------------------------------------------------------------------

class TestYearAnchoring:
    def test_year_uses_begin_time_not_end(self):
        # NEW issued late Dec 2025, ending early Jan 2026.  Per §2.1.6 the ETN
        # (and therefore the chain year) is anchored to the year the NEW was
        # issued — 2025, not 2026.
        ident = extract_vtec_identity(
            _raw('/O.NEW.KIWX.WS.W.0001.251231T2100Z-260102T1200Z/')
        )
        assert ident is not None
        assert ident['vtec_year'] == 2025

    def test_year_falls_back_to_end_when_begin_is_zero(self):
        # All-zeros begin = "event already underway" sentinel (§1.4.d).  We
        # have no choice but to use the end time for year derivation.
        ident = extract_vtec_identity(
            _raw('/O.CON.KIWX.WS.W.0001.000000T0000Z-260102T1200Z/')
        )
        assert ident is not None
        assert ident['vtec_year'] == 2026

    def test_chain_key_stable_across_year_boundary_extension(self):
        # NEW Dec 30 2025 → Dec 31 2025; later EXT extends to Jan 5 2026.
        # Both must produce the same chain key (year=2025) so the poller's
        # _mark_vtec_chain_superseded query can find them.
        new_ident = extract_vtec_identity(
            _raw('/O.NEW.KIWX.WS.W.0042.251230T0000Z-251231T2300Z/')
        )
        ext_ident = extract_vtec_identity(
            _raw('/O.EXT.KIWX.WS.W.0042.251230T0000Z-260105T1200Z/')
        )
        assert new_ident is not None and ext_ident is not None
        new_key = (
            new_ident['vtec_office'], new_ident['vtec_phenomenon'],
            new_ident['vtec_significance'], new_ident['vtec_etn'],
            new_ident['vtec_year'],
        )
        ext_key = (
            ext_ident['vtec_office'], ext_ident['vtec_phenomenon'],
            ext_ident['vtec_significance'], ext_ident['vtec_etn'],
            ext_ident['vtec_year'],
        )
        assert new_key == ext_key


# ---------------------------------------------------------------------------
# 2. Paired UPG/CAN segments — second string is primary
# ---------------------------------------------------------------------------

class TestPairedVtecStrings:
    def test_upg_pair_uses_second_string_as_primary(self):
        # §3.1 / Table 2: a Winter Storm Watch upgraded to a Blizzard Warning
        # appears as UPG (old WS.A) followed by NEW (new BZ.W).  The alert's
        # primary identity is the new Blizzard Warning event.
        ident = extract_vtec_identity(_raw(
            '/O.UPG.KIWX.WS.A.0001.000000T0000Z-260102T1200Z/',
            '/O.NEW.KIWX.BZ.W.0007.260101T0600Z-260102T1200Z/',
        ))
        assert ident is not None
        assert ident['vtec_action'] == 'NEW'
        assert ident['vtec_phenomenon'] == 'BZ'
        assert ident['vtec_significance'] == 'W'
        assert ident['vtec_etn'] == 7

    def test_can_pair_uses_second_string_as_primary(self):
        # CAN/NEW: an Ice Storm Warning being downgraded/replaced by a
        # Winter Weather Advisory.  Primary is the new advisory.
        ident = extract_vtec_identity(_raw(
            '/O.CAN.KIWX.IS.W.0003.000000T0000Z-260102T1200Z/',
            '/O.NEW.KIWX.WW.Y.0011.260101T0600Z-260102T1200Z/',
        ))
        assert ident is not None
        assert ident['vtec_action'] == 'NEW'
        assert ident['vtec_phenomenon'] == 'WW'
        assert ident['vtec_significance'] == 'Y'

    def test_can_with_exa_follow_action(self):
        # CAN/EXA: replacement extends an already-existing event in another
        # segment to cover the cancelled area (Table 2 row 2).
        ident = extract_vtec_identity(_raw(
            '/O.CAN.KIWX.WS.W.0003.000000T0000Z-260102T1200Z/',
            '/O.EXA.KIWX.WW.Y.0011.260101T0600Z-260102T1200Z/',
        ))
        assert ident is not None
        assert ident['vtec_action'] == 'EXA'

    def test_solo_upg_without_follow_string_keeps_upg_identity(self):
        # If there is no second string we have to fall back to the UPG itself
        # rather than returning None — better to record something than nothing.
        ident = extract_vtec_identity(
            _raw('/O.UPG.KIWX.WS.A.0001.000000T0000Z-260102T1200Z/')
        )
        assert ident is not None
        assert ident['vtec_action'] == 'UPG'

    def test_unparseable_first_string_falls_through_to_second(self):
        ident = extract_vtec_identity(_raw(
            'GARBAGE',
            '/O.NEW.KIWX.SV.W.0123.260101T1800Z-260101T2000Z/',
        ))
        assert ident is not None
        assert ident['vtec_action'] == 'NEW'
        assert ident['vtec_etn'] == 123


# ---------------------------------------------------------------------------
# 3. Significance regex matches only Appendix A codes
# ---------------------------------------------------------------------------

class TestSignificanceRegex:
    @pytest.mark.parametrize('sig', list('WAYSFON'))
    def test_valid_significance_codes_parse(self, sig):
        ident = extract_vtec_identity(
            _raw(f'/O.NEW.KIWX.SV.{sig}.0001.260101T1800Z-260101T2000Z/')
        )
        assert ident is not None
        assert ident['vtec_significance'] == sig

    def test_stray_m_no_longer_matches(self):
        # 'M' is not in Appendix A.  A VTEC string carrying it must be
        # rejected as unparseable rather than silently accepted.
        ident = extract_vtec_identity(
            _raw('/O.NEW.KIWX.SV.M.0001.260101T1800Z-260101T2000Z/')
        )
        assert ident is None

    def test_lookup_table_only_lists_appendix_a_codes(self):
        assert set(VTEC_SIGNIFICANCE) == set('WAYSFON')


# ---------------------------------------------------------------------------
# 4. Action set membership — COR is non-broadcasting
# ---------------------------------------------------------------------------

class TestActionSets:
    def test_cor_is_skip_not_broadcast(self):
        assert 'COR' in VTEC_SKIP_ACTIONS
        assert 'COR' not in VTEC_BROADCAST_ACTIONS

    def test_broadcast_actions_unchanged_otherwise(self):
        assert VTEC_BROADCAST_ACTIONS == frozenset({
            'NEW', 'EXT', 'EXA', 'EXB', 'UPG',
        })

    def test_skip_actions_contains_continuing_and_routine(self):
        assert {'CON', 'ROU', 'COR'}.issubset(VTEC_SKIP_ACTIONS)

    def test_terminal_actions_unchanged(self):
        assert VTEC_TERMINAL_ACTIONS == frozenset({'CAN', 'EXP'})

    def test_action_sets_are_disjoint(self):
        # No action should be in more than one gating set.
        assert not (VTEC_BROADCAST_ACTIONS & VTEC_SKIP_ACTIONS)
        assert not (VTEC_BROADCAST_ACTIONS & VTEC_TERMINAL_ACTIONS)
        assert not (VTEC_SKIP_ACTIONS & VTEC_TERMINAL_ACTIONS)


# ---------------------------------------------------------------------------
# parse_vtec_display — same year-anchoring rule
# ---------------------------------------------------------------------------

class TestParseVtecDisplay:
    def test_display_year_uses_begin_time(self):
        out = parse_vtec_display(
            '/O.NEW.KIWX.WS.W.0001.251231T2100Z-260102T1200Z/'
        )
        assert out['year'] == 2025
        assert out['action'] == 'NEW'
        assert out['action_label'] == 'New Event'

    def test_display_falls_back_to_end_when_begin_is_zero(self):
        out = parse_vtec_display(
            '/O.CON.KIWX.WS.W.0001.000000T0000Z-260102T1200Z/'
        )
        assert out['year'] == 2026
        assert out['begin'] is None  # zero sentinel decoded as None

    def test_display_unparseable_returns_raw_only(self):
        out = parse_vtec_display('not a vtec string')
        assert out == {'raw': 'not a vtec string'}


# ---------------------------------------------------------------------------
# Cancellation detection (early-lift vs. natural expiry)
# ---------------------------------------------------------------------------

class TestIsCancellation:
    def test_vtec_can_action_is_cancellation(self):
        assert is_cancellation(None, 'CAN') is True

    def test_can_action_lowercase_and_padded(self):
        assert is_cancellation(None, '  can ') is True

    def test_cap_msgtype_cancel_is_cancellation(self):
        # A cancellation can arrive via the CAP envelope even when no VTEC
        # string is present (e.g. some IPAWS products).
        assert is_cancellation('Cancel', None) is True

    def test_cap_msgtype_cancel_case_insensitive(self):
        assert is_cancellation('cancel', 'NEW') is True

    def test_expired_action_is_not_cancellation(self):
        # EXP is a terminal action but it is a natural expiry, not an early lift.
        assert is_cancellation('Update', 'EXP') is False

    def test_plain_alert_is_not_cancellation(self):
        assert is_cancellation('Alert', 'NEW') is False

    def test_empty_inputs_are_not_cancellation(self):
        assert is_cancellation(None, None) is False
        assert is_cancellation('', '') is False


class TestTerminalChainUpdates:
    NOW = datetime(2026, 6, 14, 17, 35, tzinfo=timezone.utc)

    def test_cancel_marks_cancelled_and_preserves_expiry(self):
        updates = terminal_chain_updates('CAN', 42, self.NOW)
        assert updates['superseded_by_id'] == 42
        assert updates['status'] == 'Cancelled'
        assert updates['cancelled_at'] == self.NOW
        # The original expires must NOT be collapsed — the UI needs it to show
        # the event was lifted early.
        assert 'expires' not in updates

    def test_expired_collapses_expiry_to_now(self):
        updates = terminal_chain_updates('EXP', 7, self.NOW)
        assert updates['superseded_by_id'] == 7
        assert updates['status'] == 'Expired'
        assert updates['expires'] == self.NOW
        assert 'cancelled_at' not in updates

    def test_non_terminal_action_only_links_chain(self):
        # CON/EXT/etc. just supersede prior products without closing the event.
        updates = terminal_chain_updates('CON', 99, self.NOW)
        assert updates == {'superseded_by_id': 99}

    def test_cancel_is_case_insensitive(self):
        updates = terminal_chain_updates('can', 1, self.NOW)
        assert updates['status'] == 'Cancelled'
