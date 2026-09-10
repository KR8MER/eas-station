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

"""Guard requirements.txt / requirements-sdr.txt against re-diverging on numba.

update.sh's own install order stops every eas-station service, then updates
the main venv (requirements.txt) before the SDR venv (requirements-sdr.txt).
On 2026-09-10 requirements.txt's numba pin was raised to >=0.67.0 (needed
for numpy>=2.5.2 -- every numba<0.65 release caps numpy at <2.4) but
requirements-sdr.txt was never updated to match, still capped at <0.64.0.
The main venv install succeeded; the SDR venv install then hit
pip's ResolutionImpossible on numpy>=2.5.2 vs numba<0.64.0's numpy<2.4
requirement and update.sh exited without ever reaching its "restart
services" step -- taking the whole site down until the mismatch was found
and fixed by hand.

This is a plain text-parsing test (no network, no pip resolve) so it runs
fast in CI and fails loudly the next time these two files drift instead of
waiting for a live deploy to discover it.
"""

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _numba_specifier(requirements_path: Path) -> str:
    text = requirements_path.read_text(encoding="utf-8")
    match = re.search(r"^numba([<>=!~,.\d\s]+)", text, re.MULTILINE)
    assert match, f"No numba pin found in {requirements_path.name}"
    return match.group(1).split("#")[0].strip()


def test_sdr_numba_pin_matches_main_requirements():
    """The two files must pin numba identically.

    numba's own numpy compatibility ceiling moves with each numba release
    (every numba<0.65 caps numpy<2.4; 0.66-0.67 allow numpy<2.5/<2.6), so a
    numba pin in requirements-sdr.txt that lags behind requirements.txt's
    can silently reintroduce a numpy/numba ResolutionImpossible the moment
    either file's numpy floor is raised again.
    """
    main_numba = _numba_specifier(REPO_ROOT / "requirements.txt")
    sdr_numba = _numba_specifier(REPO_ROOT / "requirements-sdr.txt")
    assert main_numba == sdr_numba, (
        f"requirements.txt pins numba{main_numba} but requirements-sdr.txt "
        f"pins numba{sdr_numba} -- these must match or a future numpy bump "
        f"in either file can make requirements-sdr.txt's install "
        f"unresolvable (see 2026-09-10 outage). Update the SDR pin to match."
    )


def test_sdr_numpy_floor_is_not_below_main_requirements():
    """requirements-sdr.txt's numpy floor should never be looser (lower)
    than requirements.txt's -- both venvs load code that expects numpy's
    current behavior, and a looser SDR floor is how this exact class of
    mismatch (SDR venv resolving an unintended older/newer numpy than the
    main venv) goes unnoticed until an update actually runs.
    """
    main_text = (REPO_ROOT / "requirements.txt").read_text(encoding="utf-8")
    sdr_text = (REPO_ROOT / "requirements-sdr.txt").read_text(encoding="utf-8")

    main_match = re.search(r"^numpy==([\d.]+)", main_text, re.MULTILINE)
    sdr_match = re.search(r"^numpy>=([\d.]+)", sdr_text, re.MULTILINE)
    assert main_match, "requirements.txt should pin numpy with =="
    assert sdr_match, "requirements-sdr.txt should pin a numpy>= floor"

    def _version_tuple(v: str):
        return tuple(int(p) for p in v.split("."))

    assert _version_tuple(sdr_match.group(1)) >= _version_tuple(main_match.group(1)), (
        f"requirements-sdr.txt's numpy>={sdr_match.group(1)} floor is below "
        f"requirements.txt's numpy=={main_match.group(1)} pin."
    )
