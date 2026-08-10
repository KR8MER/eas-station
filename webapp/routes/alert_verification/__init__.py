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

"""Routes powering the alert verification and analytics dashboard.

This package was a single 1,668-line ``webapp/routes/alert_verification.py``,
of which 687 lines were one ``register(app, logger)`` with eight helpers and
seven handlers nested inside it. ``webapp/__init__.py`` still calls
``alert_verification.register``.

Layout::

    errors                the self-test error type
    progress              on-disk progress and result stores
    decode_serialization  a decode result across the thread boundary
    audio_buffer          PCM extraction and caching
    eas_detection         locating every EAS burst in a file
    composite_audio       stitching segments into one playable file
    temp_audio            decode an upload, then persist the result
    samples               the bundled sample recordings
    helpers               the capture-free helpers from register
    routes_*              the endpoints, each with its own register()

**How the closure was preserved.** ``symtable`` says which of ``register``'s
locals each nested definition captures. The four that capture nothing
(``_load_configured_fips``, ``_result_to_dict``, ``_resolve_window_days``,
``_serialize_csv_rows``) were dedented to module scope in ``helpers``, which
is semantically identical. The rest capture ``route_logger``, ``repo_root`` or
``app``, so each topic module keeps its own ``register(app, logger)`` that
rebuilds exactly those locals and nests its handlers inside — the same closure
the single-file module built.

**Four names are deliberately NOT re-exported here.** ``_progress_dir``,
``_progress_lock``, ``_result_dir`` and ``_result_lock`` are mutable globals
that ``tests/test_alert_verification_async.py`` replaces with ``tmp_path``.
Re-exporting them would make ``monkeypatch.setattr(alert_verification,
"_result_dir", ...)`` rebind a *copy* while ``OperationResultStore`` kept
reading the real temp directory — a patch that silently does nothing and a
test that quietly stops testing isolation. Absent from this module, the same
call raises ``AttributeError`` and points at ``alert_verification.progress``,
which is where it belongs. The same applies to ``get_location_settings``
(patch ``.helpers``) and ``AlertSelfTestHarness`` (patch ``.routes_self_test``).
"""

from typing import TYPE_CHECKING

from . import (  # noqa: F401  - imported for their side effect of defining routes
    audio_buffer,
    composite_audio,
    decode_serialization,
    eas_detection,
    errors,
    helpers,
    progress,
    routes_api,
    routes_export,
    routes_operations,
    routes_page,
    routes_self_test,
    samples,
    temp_audio,
)
from .audio_buffer import _PCMBuffer, _extract_audio_segment_wav  # noqa: F401
from .composite_audio import _build_composite_audio_segment  # noqa: F401
from .decode_serialization import (  # noqa: F401
    _deserialize_decode_result,
    _serialize_decode_result,
)
from .eas_detection import _detect_comprehensive_eas_segments  # noqa: F401
from .errors import AlertSelfTestError  # noqa: F401
from .progress import OperationResultStore, ProgressTracker  # noqa: F401
from .samples import DEFAULT_SAMPLE_FILES  # noqa: F401
from .temp_audio import _process_temp_audio_file  # noqa: F401

if TYPE_CHECKING:  # pragma: no cover
    from flask import Flask

_ROUTE_MODULES = (
    routes_operations,
    routes_page,
    routes_self_test,
    routes_api,
    routes_export,
)


def register(app: 'Flask', logger) -> None:
    """Register alert verification routes on the Flask application."""

    route_logger = logger.getChild("alert_verification")

    # Clean up stale progress files on startup (files older than 1 hour)
    try:
        ProgressTracker.cleanup_old(max_age_seconds=3600)
        route_logger.info("Cleaned up stale alert verification progress files")
    except Exception as e:
        route_logger.warning(f"Failed to cleanup stale progress files: {e}")

    # Each module rebuilds the locals its own handlers captured, so it takes
    # the same (app, logger) the single-file register() did.
    for module in _ROUTE_MODULES:
        module.register(app, logger)


__all__ = ['register']
