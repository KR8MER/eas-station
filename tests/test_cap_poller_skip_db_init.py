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

"""Regression test for poller/cap_poller.py's SKIP_DB_INIT guard.

``cap_poller.py`` does ``from app import (db, CAPAlert, ...)`` to reuse the
web app's SQLAlchemy models instead of maintaining a second copy. That
import executes app.py's entire module body (first import wins) -- which is
also where the web app starts every one of its background workers
(heartbeat ping, backup/retention/auto-purge schedulers, fail2ban sync, RWT
scheduler, GPIO input listener, system metrics sampler, traffic recorder).
Without ``SKIP_DB_INIT`` set *before* that import, cap_poller.py --continuous
(a long-running systemd service) ends up running a second, independent copy
of all of those alongside its own polling loop -- confirmed live via a
py-spy stack dump showing a "HeartbeatWorker" thread inside the poller
process, sending duplicate pings (and, since the poller is never restarted
by a `systemctl restart eas-station-web`, potentially running stale
pre-deploy bytecode for that duplicate for hours after a real fix ships).

This test doesn't import cap_poller.py itself (it has heavy, real
side-effects even in the fixed state -- DB/Redis connections, thread pool
creation) -- it's a structural check that the setdefault call exists and
appears *before* the ``from app import`` line that triggers app.py's
execution, so a future edit can't silently reorder them back into the bug.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CAP_POLLER_PATH = ROOT / "poller" / "cap_poller.py"


def test_skip_db_init_is_set_before_importing_app():
    content = CAP_POLLER_PATH.read_text()

    setdefault_pos = content.find("os.environ.setdefault('SKIP_DB_INIT', '1')")
    import_pos = content.find("from app import (")

    assert setdefault_pos != -1, (
        "cap_poller.py must set SKIP_DB_INIT before importing app.py's "
        "models, or every background worker app.py normally starts for the "
        "web server (heartbeat, backup/retention/purge schedulers, "
        "fail2ban sync, ...) starts a second time inside the poller process."
    )
    assert import_pos != -1, "cap_poller.py no longer imports models from app.py"
    assert setdefault_pos < import_pos, (
        "SKIP_DB_INIT must be set BEFORE `from app import (...)` -- app.py's "
        "background-worker startup runs at import time, so setting the flag "
        "after the import is too late to suppress it."
    )
