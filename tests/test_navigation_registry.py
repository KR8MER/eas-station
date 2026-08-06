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

"""Regression tests for the declarative navigation registry.

The navbar, the ``/settings`` hub and the ``/navigation`` site map all render
from ``webapp/navigation/registry.py``. Before that registry existed the three
were hand-maintained copies that had silently drifted apart — the site map
linked pages the navbar didn't, and both linked labels that no longer matched.

These tests lock in the properties that keep them honest:

* every link in the registry points at a route that actually exists
* every permission name is a real ``PermissionDefinition``
* permission filtering prunes empty groups and sections
* the templates render from the registry rather than hardcoded ``<a>`` tags
"""

import re
from pathlib import Path

import pytest

from app_core.auth.roles import PermissionDefinition
from webapp.navigation import NAVIGATION, USER_MENU, build_navigation
from webapp.navigation.types import NAVBAR_LINK

PROJECT_ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = PROJECT_ROOT / "templates"

VALID_PERMISSIONS = {member.value for member in PermissionDefinition}


def _all_items():
    """Yield (section, group, item) for every item in the registry."""
    for section in NAVIGATION:
        for group in section.groups:
            for item in group.items:
                yield section, group, item


def _all_nodes():
    """Yield every permission-bearing node with a human-readable label."""
    for section in NAVIGATION:
        yield f"section {section.key}", section
        for group in section.groups:
            yield f"group {section.key}/{group.label}", group
            for item in group.items:
                yield f"item {section.key}/{group.label}/{item.label}", item
    yield f"group user-menu/{USER_MENU.label}", USER_MENU
    for item in USER_MENU.items:
        yield f"item user-menu/{item.label}", item


# ---------------------------------------------------------------------------
# Registry integrity
# ---------------------------------------------------------------------------


def test_registry_is_not_empty():
    """A navbar with no sections means the registry failed to import."""
    assert NAVIGATION, "navigation registry is empty"
    assert sum(1 for _ in _all_items()) > 40, "suspiciously few navigation items"


def test_every_permission_name_is_real():
    """A typo'd permission name silently hides a page from every user."""
    unknown = {}
    for label, node in _all_nodes():
        for name in node.permissions:
            if name not in VALID_PERMISSIONS:
                unknown.setdefault(label, []).append(name)

    assert not unknown, (
        "Unknown permission names in the navigation registry "
        f"(not in PermissionDefinition): {unknown}"
    )


def test_every_item_has_a_target():
    """Each item must resolve to somewhere — a route, a path, or a modal."""
    orphans = [
        f"{section.key}/{group.label}/{item.label}"
        for section, group, item in _all_items()
        if not (item.endpoint or item.href or item.modal_target)
    ]
    assert not orphans, f"Navigation items with no target: {orphans}"


def test_every_item_has_label_icon_and_description():
    """Hub cards and the site map render the description; a blank one looks broken."""
    incomplete = [
        f"{section.key}/{group.label}/{item.label}"
        for section, group, item in _all_items()
        if not (item.label and item.icon and item.description)
    ]
    assert not incomplete, f"Navigation items missing label/icon/description: {incomplete}"


def test_no_duplicate_urls_within_a_section():
    """Two links to the same page inside one dropdown is a copy/paste slip."""
    problems = {}
    for section in NAVIGATION:
        seen = {}
        for group in section.groups:
            for item in group.items:
                target = (item.endpoint, item.href, item.query)
                if target in seen:
                    problems.setdefault(section.key, []).append(
                        f"{item.label} duplicates {seen[target]}"
                    )
                seen[target] = item.label
    assert not problems, f"Duplicate destinations within a section: {problems}"


def test_settings_is_a_direct_link_not_a_two_item_dropdown():
    """Settings used to be a dropdown holding only 'System Settings' + a modal.

    It is now a single navbar link straight to the /settings hub, and the hub
    itself renders the section's groups as cards.
    """
    settings = next(s for s in NAVIGATION if s.key == "settings")
    assert settings.navbar == NAVBAR_LINK
    assert settings.href == "/settings"
    assert len(settings.groups) >= 5, "settings hub lost its card categories"


def test_display_units_lives_in_the_user_menu():
    """Display Units is per-browser personalization, not station configuration."""
    labels = [item.label for item in USER_MENU.items]
    assert "Display Units" in labels

    units = next(item for item in USER_MENU.items if item.label == "Display Units")
    assert units.modal_target == "globalUnitsModal"

    # And it must NOT also sit in the Settings section — that was the point.
    settings = next(s for s in NAVIGATION if s.key == "settings")
    settings_labels = {i.label for g in settings.groups for i in g.items}
    assert "Display Units" not in settings_labels


def test_tests_are_consolidated_into_one_section():
    """Test pages used to be spread across Broadcast, Tools and Monitor."""
    diagnostics = next(s for s in NAVIGATION if s.key == "diagnostics")
    labels = {item.label for group in diagnostics.groups for item in group.items}
    for expected in ("Audio Tests", "Alert Verification", "Weekly Test Schedule",
                     "SDR Diagnostics", "System Diagnostics"):
        assert expected in labels, f"{expected} is not in the Diagnostics section"

    # No other section should carry a test page.
    for section in NAVIGATION:
        if section.key == "diagnostics":
            continue
        stray = {
            item.label
            for group in section.groups
            for item in group.items
            if "Test" in item.label
        }
        assert not stray, f"Test pages leaked back into '{section.key}': {stray}"


# ---------------------------------------------------------------------------
# Permission filtering
# ---------------------------------------------------------------------------


def _build(permissions, *, authenticated=True):
    return build_navigation(
        NAVIGATION,
        is_authenticated=authenticated,
        permission_checker=lambda name: name in permissions,
        url_builder=lambda endpoint: f"/resolved/{endpoint}",
    )


def test_anonymous_visitor_sees_only_public_entries():
    """Signed-out visitors must not be shown admin pages."""
    sections = _build(set(), authenticated=False)
    keys = {section.key for section in sections}

    assert "settings" not in keys
    assert "reports" not in keys
    assert "broadcast" not in keys

    urls = {item.url for s in sections for g in s.groups for i in g.items for item in [i]}
    assert not any(url.startswith("/admin") for url in urls), (
        f"Anonymous navigation exposes admin URLs: "
        f"{[u for u in urls if u.startswith('/admin')]}"
    )


def test_administrator_sees_every_section():
    """With all permissions granted nothing should be filtered out."""
    sections = _build(VALID_PERMISSIONS)
    keys = [section.key for section in sections]
    assert keys == ["dashboard", "monitor", "broadcast", "diagnostics",
                    "reports", "settings", "help"]


def test_empty_groups_and_sections_are_pruned():
    """A group whose every item is filtered away must not render a bare header."""
    sections = _build({"alerts.view"})
    for section in sections:
        for group in section.groups:
            assert group.items, (
                f"Group '{section.key}/{group.label}' rendered with no items"
            )
        if section.navbar != NAVBAR_LINK:
            assert section.groups, f"Dropdown section '{section.key}' has no groups"


def test_viewer_role_gets_no_configuration_pages():
    """The read-only viewer role must not reach anything that writes config."""
    viewer = {
        "alerts.view", "alerts.export", "eas.view", "system.view_config",
        "system.view_users", "logs.view", "receivers.view", "gpio.view", "api.read",
    }
    sections = _build(viewer)
    settings = next((s for s in sections if s.key == "settings"), None)
    assert settings is not None, "viewer should still reach read-only settings"

    labels = {item.label for group in settings.groups for item in group.items}
    for forbidden in ("Application Settings", "Backups", "SSL Certificates",
                      "User Accounts", "Security Policies", "Text-to-Speech"):
        assert forbidden not in labels, (
            f"viewer role can see '{forbidden}', which requires system.configure "
            "or system.manage_users"
        )


def test_user_menu_is_empty_when_signed_out():
    """The account menu should not render for anonymous visitors."""
    from webapp.navigation.types import NavSection

    sections = build_navigation(
        (NavSection(key="user", label="Account", icon="", groups=(USER_MENU,)),),
        is_authenticated=False,
        permission_checker=lambda name: False,
        url_builder=lambda endpoint: f"/resolved/{endpoint}",
    )
    assert sections == ()


# ---------------------------------------------------------------------------
# Templates render from the registry, not from hardcoded copies
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "template",
    ["components/navbar.html", "settings_hub.html", "site_navigation.html"],
)
def test_navigation_templates_have_no_hardcoded_links(template):
    """Guard against the three-way drift the registry was built to end.

    Any ``href`` in these templates must come from a registry value
    (``{{ item.url }}`` / ``{{ section.url }}``) rather than a literal path.
    The brand link to "/" is the one allowed exception.
    """
    content = (TEMPLATES / template).read_text()

    literal_hrefs = []
    for match in re.finditer(r'href="([^"]*)"', content):
        value = match.group(1)
        if "{{" in value or "{%" in value:
            continue  # rendered from the registry or url_for
        if value in ("/", "#"):
            continue  # brand link / dropdown toggles
        literal_hrefs.append(value)

    assert not literal_hrefs, (
        f"{template} contains hardcoded links {literal_hrefs}. "
        "Add the page to webapp/navigation/registry.py instead."
    )


def test_navbar_template_carries_no_permission_conditionals():
    """Permission logic belongs in the registry, not in Jinja.

    The old navbar had 48 ``{% if can_view_* %}`` tests inline; that is what
    made it unmaintainable.
    """
    content = (TEMPLATES / "components" / "navbar.html").read_text()
    permission_tests = re.findall(r"{%-?\s*(?:el)?if[^%]*\bcan_[a-z_]+", content)
    assert not permission_tests, (
        f"navbar.html reintroduced inline permission checks: {permission_tests}"
    )


def test_navbar_preserves_the_command_palette_dom_contract():
    """static/js/core/nav-enhance.js indexes the rendered navbar.

    It walks ``.navbar-nav > .nav-item`` → ``.dropdown-menu > li``, reading
    ``.dropdown-header`` as the group label and ``a.dropdown-item[href]`` as a
    page. Breaking that nesting silently empties Ctrl+K and the breadcrumbs.
    """
    content = (TEMPLATES / "components" / "navbar.html").read_text()
    for required in ('class="navbar-nav primary-nav"',
                     'class="nav-item dropdown"',
                     'class="dropdown-menu',
                     'class="dropdown-header"',
                     'class="dropdown-item"'):
        assert required in content, f"navbar.html lost the marker {required!r}"


# ---------------------------------------------------------------------------
# Every destination exists
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def flask_app():
    """The real application, for URL-map checks."""
    from app import app as flask_application

    return flask_application


def test_every_endpoint_in_the_registry_exists(flask_app):
    """A renamed route must not leave a menu entry pointing at nothing.

    Endpoint-based entries are silently dropped by ``build_navigation`` when
    ``url_for`` raises, so without this test a typo would just make the link
    vanish from the menu with no error anywhere.
    """
    known = {rule.endpoint for rule in flask_app.url_map.iter_rules()}
    missing = {}
    for label, node in _all_nodes():
        endpoint = getattr(node, "endpoint", "")
        if endpoint and endpoint not in known:
            missing[label] = endpoint
    assert not missing, f"Navigation references unknown Flask endpoints: {missing}"


def test_every_literal_href_in_the_registry_resolves(flask_app):
    """Literal paths must match a registered GET route.

    Flask redirects ``/admin/poller`` → ``/admin/poller/``; both spellings are
    accepted here, matching what a browser does.
    """
    adapter = flask_app.url_map.bind("localhost")
    dead = {}
    for label, node in _all_nodes():
        href = getattr(node, "href", "")
        if not href or not href.startswith("/"):
            continue
        path = href.split("?")[0]
        for candidate in (path, path.rstrip("/") + "/"):
            try:
                adapter.match(candidate, method="GET")
                break
            except Exception:  # noqa: BLE001 - werkzeug raises NotFound/RequestRedirect
                continue
        else:
            dead[label] = href
    assert not dead, f"Navigation links point at routes that do not exist: {dead}"


def test_settings_link_never_leads_to_an_empty_hub():
    """Settings is a navbar LINK, so its own gate decides whether it renders.

    A LINK section is kept whenever its URL resolves — unlike a dropdown, it is
    not pruned for having no visible groups. If the section-level permission
    tuple were broader than the union of its items', a user could click
    Settings and land on a hub with nothing on it.
    """
    for permission in sorted(VALID_PERMISSIONS):
        sections = _build({permission})
        settings = next((s for s in sections if s.key == "settings"), None)
        if settings is None:
            continue
        assert settings.item_count > 0, (
            f"A user holding only '{permission}' sees the Settings link but the "
            "hub renders no cards"
        )
