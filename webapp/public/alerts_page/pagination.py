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

"""Pagination for /alerts, with a fallback for when the real one fails.

``Query.paginate`` issues a windowed query plus a count in one go, and on a
large or unhealthy database that can fail where a plain ``offset``/``limit``
still succeeds. Rather than 500 the page, the handler retries by hand and wraps
the result in :class:`MockPagination`, which presents the same surface the
template consumes — including ``iter_pages()``.
"""

from app_core.extensions import db


class MockPagination:
    """A stand-in with the same shape as flask-sqlalchemy's Pagination."""

    def __init__(self, page_num: int, page_size: int, total: int, items):
        self.page = page_num
        self.per_page = page_size
        self.total = total
        self.items = items
        self.pages = (total + page_size - 1) // page_size if page_size > 0 else 1
        self.has_prev = page_num > 1
        self.has_next = page_num < self.pages
        self.prev_num = page_num - 1 if self.has_prev else None
        self.next_num = page_num + 1 if self.has_next else None

    def iter_pages(
        self,
        left_edge: int = 2,
        left_current: int = 2,
        right_current: int = 3,
        right_edge: int = 2,
    ):
        """Page numbers to render, with ``None`` marking an elided run."""
        last = self.pages
        for num in range(1, last + 1):
            if (
                num <= left_edge
                or (self.page - left_current - 1 < num < self.page + right_current)
                or num > last - right_edge
            ):
                yield num
            elif num == left_edge + 1 or num == self.page + right_current:
                yield None


def paginate_alerts(query, page: int, per_page: int, route_logger):
    """Paginate, falling back to offset/limit and finally to an empty page.

    Returns ``(pagination, items)``. Three outcomes, in order of preference:
    the real paginator, a hand-rolled window, or an empty result — the page
    renders in all three cases.
    """
    try:
        pagination = query.paginate(page=page, per_page=per_page, error_out=False)
        return pagination, pagination.items
    except Exception as exc:
        route_logger.warning("Pagination error: %s", exc)

    # The failed paginate may have aborted the transaction; without a rollback
    # the retry below cannot issue any SQL at all.
    try:
        db.session.rollback()
    except Exception:
        pass

    try:
        total_count = query.count()
        offset = (page - 1) * per_page
        alerts_list = query.offset(offset).limit(per_page).all()
    except Exception as fallback_exc:
        db.session.rollback()
        route_logger.error("Fallback pagination failed: %s", fallback_exc)
        alerts_list = []
        total_count = 0

    return MockPagination(page, per_page, total_count, alerts_list), alerts_list


__all__ = ["MockPagination", "paginate_alerts"]
