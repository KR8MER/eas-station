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

"""Blueprint object shared by every audio-ingest route module.

This lives in its own module so the route modules and the package
``__init__`` can both reach the Blueprint without importing each other.
"""

from flask import Blueprint

# Create Blueprint for audio ingest routes
#
# ``__package__`` rather than ``__name__``: before the split this line ran in
# ``webapp.admin.audio_ingest``, and a Blueprint's import_name is what Flask
# resolves its root path from. ``__package__`` is that same string here, so the
# Blueprint is byte-for-byte the object it was.
audio_ingest_bp = Blueprint('audio_ingest', __package__)
