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

"""Pin down what the deny-by-default gate lets through without a session.

Two directions matter and they pull against each other:

* Documentation, help and licence pages must be readable by anyone. Putting the
  AGPL attribution notices or the docs tree behind a login defeats their point.
* Endpoints that describe the *machine* — hostname, primary IP, disk SMART data
  including drive serial numbers, receiver and audio-hardware state — must not
  be readable by the internet on a box published at a public hostname.

The middle tier exists because the display subsystem's screen renderer fetches
several of those diagnostics from ``http://localhost:5000`` with no session, so
they cannot simply be gated outright.
"""

import app as appmod

APP = appmod.app

#: Everything an anonymous visitor from the internet must be able to read.
EXPECTED_PUBLIC_PAGES = {
    '/',
    '/about',
    '/help',
    '/terms',
    '/privacy',
    '/sms-compliance',
    '/docs',
    '/support',
    '/version',
    '/help/version',
    '/repo-stats',
    '/attribution',
    '/style-guide',
}

#: Machine-describing GETs that must never answer an anonymous internet caller.
MACHINE_DETAIL_APIS = {
    '/api/system_status',
    '/api/system_health',
    '/api/smart_diag',
    '/api/audio/metrics',
    '/api/audio/metrics/latest',
    '/api/audio/health',
    '/api/audio/sources',
    '/api/eas-monitor/status',
    '/api/monitoring/radio',
    '/api/gps_status',
}


def _is_public_page(path: str) -> bool:
    return (
        path in appmod._PUBLIC_PAGE_PATHS
        or any(path.startswith(prefix) for prefix in appmod._PUBLIC_PAGE_PREFIXES)
    )


# ---------------------------------------------------------------------------
# Documentation must not require a password
# ---------------------------------------------------------------------------


def test_documentation_and_licence_pages_are_public():
    """Docs, help, legal and attribution pages are readable without signing in."""
    missing = sorted(p for p in EXPECTED_PUBLIC_PAGES if not _is_public_page(p))
    assert not missing, f"these should not require a login: {missing}"


def test_docs_tree_and_search_are_public():
    """The whole /docs viewer, its assets and its search are public."""
    for path in (
        '/docs',
        '/docs/architecture/THEORY_OF_OPERATION.md',
        '/docs/assets/diagrams/security-auth-architecture.svg',
        '/docs/search',
        '/docs/search/api',
    ):
        assert _is_public_page(path), f"{path} requires a login"


def test_every_registered_docs_route_is_public():
    """No route under /docs may be added behind the gate by accident."""
    gated = [
        str(rule)
        for rule in APP.url_map.iter_rules()
        if str(rule).startswith('/docs') and not _is_public_page(str(rule))
    ]
    assert not gated, f"documentation routes behind auth: {gated}"


# ---------------------------------------------------------------------------
# ...but machine details must not be world-readable
# ---------------------------------------------------------------------------


def test_machine_detail_apis_are_not_internet_public():
    """None of the machine-describing GETs sit in the internet-public set."""
    leaked = sorted(MACHINE_DETAIL_APIS & appmod.PUBLIC_API_GET_PATHS)
    assert not leaked, (
        f"these expose host details to anonymous internet callers: {leaked}"
    )


def test_machine_detail_apis_are_reachable_locally():
    """They stay unauthenticated for on-box callers.

    ``scripts.screen_renderer.ScreenRenderer`` fetches them from
    http://localhost:5000 with no session to populate OLED/LED/VFD screens.
    """
    assert MACHINE_DETAIL_APIS <= appmod.LOCAL_API_GET_PATHS


def test_public_and_local_api_sets_are_disjoint():
    assert not (appmod.PUBLIC_API_GET_PATHS & appmod.LOCAL_API_GET_PATHS)


def test_screen_renderer_endpoints_are_all_reachable_without_a_session():
    """Every endpoint shipped in a default display screen must still resolve.

    Gating one of these without noticing would blank a hardware screen.
    """
    allowed = appmod.PUBLIC_API_GET_PATHS | appmod.LOCAL_API_GET_PATHS
    for endpoint in (
        '/api/system_status',
        '/api/system_health',
        '/api/alerts',
        '/api/audio/health',
        '/api/audio/metrics',
        '/api/monitoring/radio',
        '/api/eas-monitor/status',
        '/api/gps_status',
    ):
        assert endpoint in allowed, f"display screens fetch {endpoint}"


# ---------------------------------------------------------------------------
# Local-network detection
# ---------------------------------------------------------------------------


def test_loopback_and_private_addresses_count_as_local():
    for addr in (
        '127.0.0.1',
        '::1',
        '192.168.1.50',
        '10.0.0.7',
        '172.16.4.9',
        'fd00::1',
        '169.254.10.1',
    ):
        assert appmod._is_local_network_client(addr) is True, addr


def test_public_addresses_do_not_count_as_local():
    """A remote caller cannot reach the local-only tier.

    request.remote_addr is the real client IP (ProxyFix, one trusted hop), so
    an attacker cannot claim to be local by sending its own X-Forwarded-For.

    Note: RFC 5737 documentation ranges (192.0.2/24, 198.51.100/24, 203.0.113/24)
    are *not* usable here as "public" examples — ipaddress classifies them as
    private, correctly, since they are not globally routable. Use real routable
    addresses.
    """
    for addr in ('8.8.8.8', '1.1.1.1', '93.184.216.34', '2001:4860:4860::8888'):
        assert appmod._is_local_network_client(addr) is False, addr


def test_missing_or_malformed_address_is_not_local():
    """Fail closed when the client address is unavailable or nonsense."""
    for addr in (None, '', '   ', 'not-an-ip', 'localhost'):
        assert appmod._is_local_network_client(addr) is False, repr(addr)
