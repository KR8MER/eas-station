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

"""Declarative navigation for EAS Station™.

One tree (:data:`webapp.navigation.registry.NAVIGATION`) feeds the navbar, the
``/settings`` hub and the ``/navigation`` site map. See ``registry.py`` for the
tree itself and ``types.py`` for the node types and filtering rules.

Templates receive the already-filtered tree through
:func:`inject_navigation`, registered as a Flask context processor in
``app.py``:

    ``nav_sections``     tuple[ResolvedSection] — visible top-level sections
    ``nav_user_menu``    tuple[ResolvedItem]    — the signed-in user's menu
    ``nav_section_map``  dict[str, ResolvedSection] — sections keyed by key
"""

import logging

from .registry import NAVIGATION, USER_MENU
from .types import (
    NAVBAR_DROPDOWN,
    NAVBAR_HIDDEN,
    NAVBAR_LINK,
    NavGroup,
    NavItem,
    NavSection,
    ResolvedGroup,
    ResolvedItem,
    ResolvedSection,
    build_navigation,
    resolve_url,
)

logger = logging.getLogger(__name__)


def _viewer_context():
    """Resolve the current viewer's auth state and permission checker.

    Returns:
        Tuple of (is_authenticated, permission_checker).
    """
    from flask import g

    from app_core.auth.roles import has_permission

    user = getattr(g, "current_user", None)
    is_authenticated = bool(user is not None and getattr(user, "is_authenticated", False))
    return is_authenticated, has_permission


def get_navigation():
    """Build the navigation tree for the current request.

    Returns:
        Tuple of ResolvedSection visible to the current viewer. Returns an
        empty tuple if navigation cannot be built — a broken menu must never
        take down the page that renders it.
    """
    from flask import url_for

    try:
        is_authenticated, permission_checker = _viewer_context()
        return build_navigation(
            NAVIGATION,
            is_authenticated=is_authenticated,
            permission_checker=permission_checker,
            url_builder=url_for,
        )
    except Exception as exc:  # pragma: no cover - defensive, navbar renders everywhere
        logger.error("Failed to build navigation tree: %s", exc)
        return ()


def get_user_menu():
    """Build the signed-in user's own menu items.

    Returns:
        Tuple of ResolvedItem, empty when signed out or on failure.
    """
    from flask import url_for

    try:
        is_authenticated, permission_checker = _viewer_context()
        if not is_authenticated:
            return ()
        section = build_navigation(
            (
                NavSection(
                    key="user",
                    label=USER_MENU.label,
                    icon=USER_MENU.icon,
                    groups=(USER_MENU,),
                ),
            ),
            is_authenticated=is_authenticated,
            permission_checker=permission_checker,
            url_builder=url_for,
        )
        if not section:
            return ()
        return section[0].groups[0].items
    except Exception as exc:  # pragma: no cover - defensive
        logger.error("Failed to build user menu: %s", exc)
        return ()


def inject_navigation() -> dict:
    """Flask context processor injecting the navigation tree into templates.

    Example:
        >>> from webapp.navigation import inject_navigation
        >>> app.context_processor(inject_navigation)
    """
    sections = get_navigation()
    return {
        "nav_sections": sections,
        "nav_section_map": {section.key: section for section in sections},
        "nav_user_menu": get_user_menu(),
    }


__all__ = [
    "NAVBAR_DROPDOWN",
    "NAVBAR_HIDDEN",
    "NAVBAR_LINK",
    "NAVIGATION",
    "NavGroup",
    "NavItem",
    "NavSection",
    "ResolvedGroup",
    "ResolvedItem",
    "ResolvedSection",
    "USER_MENU",
    "build_navigation",
    "get_navigation",
    "get_user_menu",
    "inject_navigation",
    "resolve_url",
]
