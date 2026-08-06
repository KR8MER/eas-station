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

"""Data types for the declarative navigation registry.

The navigation tree is plain data (see :mod:`webapp.navigation.registry`) so
that the navbar, the ``/settings`` hub and the ``/navigation`` site map can all
render from one source instead of each keeping a hand-maintained copy.

Three levels:

    NavSection  →  NavGroup  →  NavItem

A section is a top-level navbar entry (``Monitor``, ``Broadcast``, …). Groups
become the ``<h6 class="dropdown-header">`` labels inside a dropdown and the
sub-headings on the hub pages. Items are the actual links.

Visibility is declared per item as an *any-of* permission tuple; groups and
sections are hidden automatically once every child is filtered out, so adding a
page never means touching a template conditional.
"""

from dataclasses import dataclass
from typing import Callable, Optional, Sequence, Tuple

# How a section is presented in the top navbar.
NAVBAR_DROPDOWN = "dropdown"  # dropdown listing the section's groups/items
NAVBAR_LINK = "link"          # single link straight to the section's own href
NAVBAR_HIDDEN = "hidden"      # not in the navbar (site map / hub only)


@dataclass(frozen=True)
class NavItem:
    """A single navigable destination.

    Exactly one of ``endpoint`` or ``href`` identifies the target. ``endpoint``
    is preferred — it is resolved through ``url_for`` so a route rename is
    caught at render time instead of silently 404-ing.

    Args:
        label: Link text shown in the navbar, hub cards and site map.
        icon: Font Awesome classes, e.g. ``'fas fa-bell'``.
        endpoint: Flask endpoint name, resolved via ``url_for``.
        href: Literal path (may carry a query string) used when no endpoint.
        query: Query string appended to a resolved ``endpoint`` URL.
        description: One-line summary; shown on hub cards and the site map.
        permissions: Any-of permission names. Empty means "no permission gate".
        requires_auth: Hide the item from signed-out visitors.
        modal_target: CSS id of a Bootstrap modal. When set the item renders as
            a ``<button>`` opening that modal rather than an ``<a>``.
    """

    label: str
    icon: str = ""
    endpoint: str = ""
    href: str = ""
    query: str = ""
    description: str = ""
    permissions: Tuple[str, ...] = ()
    requires_auth: bool = True
    modal_target: str = ""


@dataclass(frozen=True)
class NavGroup:
    """A labelled cluster of items inside a section."""

    label: str
    items: Tuple[NavItem, ...]
    icon: str = ""
    permissions: Tuple[str, ...] = ()
    requires_auth: bool = True


@dataclass(frozen=True)
class NavSection:
    """A top-level navigation section."""

    key: str
    label: str
    icon: str
    groups: Tuple[NavGroup, ...] = ()
    navbar: str = NAVBAR_DROPDOWN
    endpoint: str = ""
    href: str = ""
    description: str = ""
    permissions: Tuple[str, ...] = ()
    requires_auth: bool = True
    # Bootstrap contextual colour used for the section card on the site map.
    accent: str = "primary"


# ---------------------------------------------------------------------------
# Resolved (render-ready) mirrors of the types above
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ResolvedItem:
    """A NavItem with its URL resolved and permissions already applied."""

    label: str
    icon: str
    url: str
    description: str = ""
    modal_target: str = ""


@dataclass(frozen=True)
class ResolvedGroup:
    label: str
    icon: str
    items: Tuple[ResolvedItem, ...]


@dataclass(frozen=True)
class ResolvedSection:
    key: str
    label: str
    icon: str
    groups: Tuple[ResolvedGroup, ...]
    navbar: str
    url: str
    description: str
    accent: str

    @property
    def item_count(self) -> int:
        """Total number of visible items across all groups."""
        return sum(len(group.items) for group in self.groups)


def _allowed(
    permissions: Sequence[str],
    requires_auth: bool,
    *,
    is_authenticated: bool,
    permission_checker: Callable[[str], bool],
) -> bool:
    """Return True when the current viewer may see this node.

    Permissions are *any-of*: holding one of them is enough. An empty tuple
    means the node has no permission gate (``requires_auth`` may still apply).
    """
    if requires_auth and not is_authenticated:
        return False
    if not permissions:
        return True
    return any(permission_checker(name) for name in permissions)


def resolve_url(
    endpoint: str,
    href: str,
    query: str,
    url_builder: Optional[Callable[[str], str]],
) -> str:
    """Resolve a nav target to a URL string.

    Endpoint resolution is preferred but never fatal: a nav entry pointing at a
    route that no longer exists is dropped from the menu rather than raising and
    taking down every page that renders the navbar.

    Returns:
        The resolved URL, or an empty string when it cannot be resolved.
    """
    if endpoint and url_builder is not None:
        try:
            resolved = url_builder(endpoint)
        except Exception:  # noqa: BLE001 - werkzeug raises BuildError; be lenient
            return ""
        return f"{resolved}{query}" if query else resolved
    if href:
        return f"{href}{query}" if query else href
    return ""


def build_navigation(
    sections: Sequence[NavSection],
    *,
    is_authenticated: bool,
    permission_checker: Callable[[str], bool],
    url_builder: Optional[Callable[[str], str]] = None,
) -> Tuple[ResolvedSection, ...]:
    """Filter and resolve the navigation tree for one viewer.

    Args:
        sections: The declarative registry (normally ``NAVIGATION``).
        is_authenticated: Whether a user is signed in.
        permission_checker: Callable taking a permission name, returning bool.
        url_builder: Callable taking an endpoint name and returning a URL —
            normally Flask's ``url_for``. When omitted, endpoint-based entries
            are dropped and only literal ``href`` entries survive.

    Returns:
        Tuple of ResolvedSection, with empty groups and sections removed.

    Example:
        >>> visible = build_navigation(
        ...     NAVIGATION,
        ...     is_authenticated=True,
        ...     permission_checker=lambda name: True,
        ...     url_builder=url_for,
        ... )
        >>> [section.key for section in visible][:2]
        ['dashboard', 'monitor']
    """
    resolved_sections = []

    for section in sections:
        if not _allowed(
            section.permissions,
            section.requires_auth,
            is_authenticated=is_authenticated,
            permission_checker=permission_checker,
        ):
            continue

        resolved_groups = []
        for group in section.groups:
            if not _allowed(
                group.permissions,
                group.requires_auth,
                is_authenticated=is_authenticated,
                permission_checker=permission_checker,
            ):
                continue

            resolved_items = []
            for item in group.items:
                if not _allowed(
                    item.permissions,
                    item.requires_auth,
                    is_authenticated=is_authenticated,
                    permission_checker=permission_checker,
                ):
                    continue
                url = resolve_url(item.endpoint, item.href, item.query, url_builder)
                # A modal item has no URL of its own; everything else needs one.
                if not url and not item.modal_target:
                    continue
                resolved_items.append(
                    ResolvedItem(
                        label=item.label,
                        icon=item.icon,
                        url=url,
                        description=item.description,
                        modal_target=item.modal_target,
                    )
                )

            if resolved_items:
                resolved_groups.append(
                    ResolvedGroup(
                        label=group.label,
                        icon=group.icon,
                        items=tuple(resolved_items),
                    )
                )

        section_url = resolve_url(section.endpoint, section.href, "", url_builder)

        # A LINK section stands on its own URL; a DROPDOWN section is only
        # meaningful when it still has something to drop down.
        if section.navbar == NAVBAR_LINK:
            if not section_url:
                continue
        elif not resolved_groups:
            continue

        resolved_sections.append(
            ResolvedSection(
                key=section.key,
                label=section.label,
                icon=section.icon,
                groups=tuple(resolved_groups),
                navbar=section.navbar,
                url=section_url,
                description=section.description,
                accent=section.accent,
            )
        )

    return tuple(resolved_sections)


__all__ = [
    "NAVBAR_DROPDOWN",
    "NAVBAR_HIDDEN",
    "NAVBAR_LINK",
    "NavGroup",
    "NavItem",
    "NavSection",
    "ResolvedGroup",
    "ResolvedItem",
    "ResolvedSection",
    "build_navigation",
    "resolve_url",
]
