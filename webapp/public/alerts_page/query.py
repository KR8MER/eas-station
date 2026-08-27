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

"""Turning :class:`AlertFilters` into a CAPAlert query."""

from app_core.models import CAPAlert
from app_utils import utc_now
from sqlalchemy import or_

from .filters import AlertFilters

# Columns the free-text search scans. Matching any one of them includes the
# alert, so a search for a county name and a search for an event type both work.
SEARCH_COLUMNS = (
    CAPAlert.headline,
    CAPAlert.description,
    CAPAlert.event,
    CAPAlert.area_desc,
)


def apply_search(query, search: str):
    """Case-insensitive partial match across the searchable columns."""
    if not search:
        return query
    term = f"%{search}%"
    return query.filter(or_(*(column.ilike(term) for column in SEARCH_COLUMNS)))


def apply_exact_filters(query, filters: AlertFilters):
    """The four exact-match dropdowns. An empty value means "no filter"."""
    if filters.status:
        query = query.filter(CAPAlert.status == filters.status)
    if filters.severity:
        query = query.filter(CAPAlert.severity == filters.severity)
    if filters.event:
        query = query.filter(CAPAlert.event == filters.event)
    if filters.source:
        query = query.filter(CAPAlert.source == filters.source)
    return query


def apply_date_range(query, filters: AlertFilters):
    """Bound by ``sent``. Dates that did not parse were already dropped."""
    if filters.date_from_dt is not None:
        query = query.filter(CAPAlert.sent >= filters.date_from_dt)
    if filters.date_to_dt is not None:
        query = query.filter(CAPAlert.sent < filters.date_to_dt)
    return query


def apply_vtec(query, filters: AlertFilters):
    """Narrow to one VTEC event chain.

    A non-numeric ``vtec_etn``/``vtec_year`` is skipped rather than rejected —
    but it still counts as "browsing a chain" for
    :meth:`AlertFilters.vtec_active`, so the visibility rules below stay
    relaxed.
    """
    if filters.vtec_office:
        query = query.filter(CAPAlert.vtec_office == filters.vtec_office)
    if filters.vtec_etn_int is not None:
        query = query.filter(CAPAlert.vtec_etn == filters.vtec_etn_int)
    if filters.vtec_year_int is not None:
        query = query.filter(CAPAlert.vtec_year == filters.vtec_year_int)
    return query


def apply_visibility(query, filters: AlertFilters):
    """Hide expired and superseded alerts unless asked for.

    Both rules are suspended while browsing a VTEC event chain: the chain is
    the *history* of one event, so hiding its expired and superseded members
    would render it full of holes.
    """
    if not filters.show_expired and not filters.vtec_active:
        # status.notin_ (not just != "Expired") because a Cancel/Update
        # arriving before the original expires time sets status='Cancelled'
        # without touching expires -- that alert must hide here too, or it
        # keeps showing as current on the public page indefinitely.
        query = query.filter(
            or_(CAPAlert.expires.is_(None), CAPAlert.expires > utc_now())
        ).filter(CAPAlert.status.notin_(("Expired", "Cancelled")))

    # Hide superseded alerts by default; they are shown when the operator
    # explicitly requests them or is browsing a VTEC event chain.
    if not filters.show_superseded and not filters.vtec_active:
        query = query.filter(CAPAlert.superseded_by_id.is_(None))

    return query


def apply_sort(query, filters: AlertFilters):
    """Order by the allow-listed column and direction."""
    column = filters.sort_column
    return query.order_by(column.asc() if filters.direction == "asc" else column.desc())


def build_alert_query(filters: AlertFilters):
    """The full /alerts listing query, filtered and sorted."""
    query = CAPAlert.query
    query = apply_search(query, filters.search)
    query = apply_exact_filters(query, filters)
    query = apply_date_range(query, filters)
    query = apply_vtec(query, filters)
    query = apply_visibility(query, filters)
    return apply_sort(query, filters)


__all__ = [
    "SEARCH_COLUMNS",
    "apply_date_range",
    "apply_exact_filters",
    "apply_search",
    "apply_sort",
    "apply_visibility",
    "apply_vtec",
    "build_alert_query",
]
