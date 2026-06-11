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

"""Build a coverage-map / alert-summary image for notification emails.

Reuses the same share-card renderer that powers the alert detail page's
"Export image" feature (``app_utils.image_export.generate_alert_image``)
so notification emails carry the identical, already-tested visual: an
event-themed header, the coverage map with the affected polygon drawn on
top, and the headline / affected areas / description pulled from the CAP
alert.

The caller's ``db_session`` is threaded through to the renderer for the
PostGIS geometry / county-outline queries, because notification emails are
sent from the CAP poller and audio monitoring services — standalone
processes with no Flask application context where the renderer's default
Flask-SQLAlchemy session would fail. Any failure (Pillow unavailable, no
geometry, offline tile fetch, …) degrades to ``None`` and the email is
simply sent without the image.
"""

import logging
from typing import Optional

logger = logging.getLogger(__name__)


def build_alert_image(
    db_session,
    cap_alert_id: Optional[int],
    log: Optional[logging.Logger] = None,
) -> Optional[bytes]:
    """Render a PNG share card for the CAP alert behind a broadcast.

    Args:
        db_session:   Active SQLAlchemy session used to load the CAPAlert.
        cap_alert_id: Primary key of the CAPAlert to render. ``None`` skips.
        log:          Optional logger override.

    Returns:
        PNG bytes on success, or ``None`` if the image could not be built.
    """
    out = log or logger
    if not cap_alert_id:
        return None

    try:
        from app_core.models import CAPAlert
        from app_utils.image_export import generate_alert_image

        alert = db_session.get(CAPAlert, cap_alert_id)
        if alert is None:
            out.debug("build_alert_image: CAPAlert %s not found", cap_alert_id)
            return None

        # Location settings drive the county label on the card; optional.
        location_settings = None
        try:
            from app_core.location import get_location_settings

            location_settings = get_location_settings()
        except Exception:
            location_settings = None

        # coverage_data / ipaws_data are pure enrichment — the renderer
        # tolerates empty/None and still draws the map + headline + areas
        # straight from the CAPAlert row.
        return generate_alert_image(
            alert,
            {},
            None,
            location_settings,
            aspect_ratio="landscape",
            image_format="png",
            db_session=db_session,
        )

    except Exception as exc:  # pragma: no cover - defensive
        out.warning(
            "Could not build alert image for CAP alert %s: %s", cap_alert_id, exc
        )
        return None


__all__ = ["build_alert_image"]
