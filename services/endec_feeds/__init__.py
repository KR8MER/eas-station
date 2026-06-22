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

"""ENDEC device-feed subsystem.

Serves the Sage-ENDEC-compatible TCP "device feeds" (Generic Character
Generator, News Feed, decoder status, raw EAS encoder mirror). The wire
formats live in :mod:`app_utils.endec_feeds`; this package owns the TCP
fan-out and the subscription to the Redis feed-event channel.
"""

from services.endec_feeds.server import FeedListener, FeedManager, normalize_feeds

__all__ = ["FeedListener", "FeedManager", "normalize_feeds"]
