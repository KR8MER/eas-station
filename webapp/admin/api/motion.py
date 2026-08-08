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

"""Parsing the NWS storm-motion parameter.

``_parse_event_motion`` turns the raw ``eventMotionDescription`` CAP parameter
into the bearing/speed dict the alert detail template renders. Only
``display_data`` calls it; it is its own module because it is a self-contained
string parser carrying its own format documentation.
"""

from typing import Any, Dict


def _parse_event_motion(raw: str) -> Dict[str, Any]:
    """Parse an NWS eventMotionDescription parameter string.

    Format (parts separated by '...' ):
      <ISO-timestamp>...storm...<degrees>DEG...<speed>KT...<lat1>,<lon1> <lat2>,<lon2>...

    The DEG value uses the same "from" convention as wind direction: it is the
    direction FROM which the storm is approaching, not the direction it is heading.
    062DEG means the storm is coming from the ENE and moving toward the WSW.

    Track coordinates are listed oldest-to-newest (first point = earliest known
    position, last point = most recent known position).

    Returns a dict with parsed fields. Raises on bad input so callers can
    catch and discard gracefully.
    """
    parts = [p.strip() for p in raw.split('...')]

    motion: Dict[str, Any] = {'raw': raw}

    for part in parts:
        upper = part.upper()
        if upper.endswith('DEG'):
            try:
                motion['direction_deg'] = int(part[:-3])
            except ValueError:
                pass
        elif upper.endswith('KT'):
            try:
                kt = float(part[:-2])
                motion['speed_kt'] = kt
                motion['speed_mph'] = round(kt * 1.15078, 1)
            except ValueError:
                pass
        elif 'T' in part and part[0].isdigit():
            motion['timestamp'] = part
        elif ',' in part:
            # Coordinate pairs — listed oldest first, newest last.
            coords = []
            for token in part.split():
                try:
                    lat_s, lon_s = token.split(',')
                    coords.append([float(lat_s), float(lon_s)])
                except ValueError:
                    pass
            if coords:
                motion['track'] = coords

    # direction_deg is the FROM direction (where the storm originated).
    # Compute the heading (where the storm is going) = FROM + 180°.
    deg = motion.get('direction_deg')
    if deg is not None:
        dirs = ['N', 'NNE', 'NE', 'ENE', 'E', 'ESE', 'SE', 'SSE',
                'S', 'SSW', 'SW', 'WSW', 'W', 'WNW', 'NW', 'NNW']
        # compass_from: direction the storm is approaching from (NWS convention)
        from_idx = int((deg + 11.25) / 22.5) % 16
        motion['compass_from'] = dirs[from_idx]
        # compass_toward: actual direction of travel (used for compass arrow)
        toward_deg = (deg + 180) % 360
        toward_idx = int((toward_deg + 11.25) / 22.5) % 16
        motion['compass_toward'] = dirs[toward_idx]
        motion['toward_deg'] = toward_deg
        # Keep 'compass' as the from-direction for backward compatibility
        motion['compass'] = motion['compass_from']

    return motion
