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

"""The one logger every module in this package writes through.

Pre-split this was a single ``logging.getLogger(__name__)`` in a 1,946-line
module, and all 92 call sites resolved to the record name
``webapp.admin.certbot``. Giving each new module its own ``__name__`` logger
would have renamed those records to ``webapp.admin.certbot.routes_obtain`` and
friends, quietly breaking any log filter or journald grep keyed on the old
name. ``__package__`` is the pre-split value, so the records are unchanged.

``register_certbot_routes`` does *not* rebind this — it only writes one
"routes registered" line through the logger it is handed — so a by-value
``from .log import logger`` is safe here. (Phase 3a's audio_ingest package
needed a fan-out instead precisely because its ``register`` did rebind.)
"""

import logging


# ``__package__`` is ``webapp.admin.certbot`` — the value ``__name__`` had
# in the single-file module. Using this module's ``__name__`` would rename
# every record to ``webapp.admin.certbot.log``.
logger = logging.getLogger(__package__)
