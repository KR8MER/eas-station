"""Tests for audio detail location presentation helpers."""

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from webapp.admin.audio.detail import _build_location_details


def test_build_location_details_includes_state_and_fips_codes():
    header = "ZCZC-EAS-RWT-039137-039051+0030-1234567-KR8MER-"
    lookup = {
        '039137': 'Putnam County',
        '039051': 'Hancock County',
    }
    state_index = {
        '39': {'abbr': 'OH', 'name': 'Ohio'},
    }

    entries = _build_location_details(header, lookup=lookup, state_index=state_index)

    assert [entry['code'] for entry in entries] == ['039137', '039051']
    assert entries[0]['state_abbr'] == 'OH'
    assert entries[0]['state_fips'] == '39'
    assert entries[0]['scope'] == 'County FIPS 137'
    assert entries[0]['portion'] == 'Entire area'
