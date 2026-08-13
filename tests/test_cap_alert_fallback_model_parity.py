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

"""Guard against poller/cap_poller.py's fallback CAPAlert model drifting
from the canonical one in app_core/_models_alerts.py.

Bug this was written for: poller/cap_poller.py tries `from app import ...`
first and only defines its own standalone (non-Flask) CAPAlert model in the
except-block as a fallback for when that import fails. That fallback model
was last updated before the vtec_office/vtec_phenomenon/vtec_significance/
vtec_etn/vtec_year/vtec_action/superseded_by_id/cancelled_at columns were
added to the canonical model. When an unrelated Numba disk-cache race
intermittently broke the primary import (see the comment above
_dll_drain_bits_numba in app_utils/eas_demod.py), the poller silently fell
back to this stale model. Two call sites do unconditional attribute access
on those columns (``existing.vtec_office`` in _update_existing_alert,
``new_alert.vtec_action`` in _insert_new_alert) — on the fallback model
those attributes don't exist as instrumented columns at all, so the access
raised a bare AttributeError and "Error saving CAP alert" for every NWS
product carrying a VTEC string, for as long as that poller process ran.

Both call sites were also hardened with getattr(..., None) as defense in
depth, but this test is what actually prevents the next schema change from
reintroducing a silent gap: it fails the build the moment a column is added
to one model and not the other, instead of waiting for it to surface as
production alert-ingestion failures.

Static source parsing (no import, no app context needed) so this runs
regardless of whether `from app import ...` happens to succeed in this
environment — the whole point is to check the fallback definition even when
it's never actually exercised at test time.
"""

import re
from pathlib import Path

CANONICAL_MODEL_PATH = Path(__file__).resolve().parent.parent / 'app_core' / '_models_alerts.py'
POLLER_PATH = Path(__file__).resolve().parent.parent / 'poller' / 'cap_poller.py'


def _canonical_cap_alert_columns() -> set:
    source = CANONICAL_MODEL_PATH.read_text(encoding='utf-8')
    start = source.index('class CAPAlert(')
    rest = source[start:]
    next_class = re.search(r'\nclass \w+\(', rest[10:])
    block = rest[:next_class.start() + 10] if next_class else rest
    return set(re.findall(r'^\s+(\w+)\s*=\s*db\.Column', block, re.M))


def _fallback_cap_alert_columns() -> set:
    source = POLLER_PATH.read_text(encoding='utf-8')
    start = source.index('class CAPAlert(Base):')
    rest = source[start:]
    # Next sibling class at the same (4-space) indent level inside the
    # except-block ends this class's body.
    next_class = re.search(r'\n    class \w+\(Base\):', rest[10:])
    block = rest[:next_class.start() + 10] if next_class else rest
    return set(re.findall(r'^\s+(\w+)\s*=\s*Column\(', block, re.M))


def test_fallback_cap_alert_has_every_canonical_column():
    canonical = _canonical_cap_alert_columns()
    fallback = _fallback_cap_alert_columns()

    # Sanity check the extraction itself found a realistic column set —
    # guards against the regex silently matching nothing after a refactor.
    assert len(canonical) > 20, "Canonical column extraction found too few columns"
    assert len(fallback) > 20, "Fallback column extraction found too few columns"

    missing = canonical - fallback
    assert not missing, (
        f"poller/cap_poller.py's fallback CAPAlert model is missing columns "
        f"present on the canonical model: {sorted(missing)}. This is exactly "
        f"the gap that broke VTEC alert ingestion in production -- add these "
        f"columns to the fallback class in poller/cap_poller.py."
    )


def test_vtec_and_supersession_columns_present_on_fallback():
    """Explicit check for the exact columns the original bug was missing,
    independent of whether the canonical model ever changes."""
    fallback = _fallback_cap_alert_columns()
    required = {
        'vtec_office', 'vtec_phenomenon', 'vtec_significance',
        'vtec_etn', 'vtec_year', 'vtec_action',
        'superseded_by_id', 'cancelled_at',
    }
    missing = required - fallback
    assert not missing, f"Fallback CAPAlert model missing: {sorted(missing)}"
