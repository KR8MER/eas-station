"""Regression tests ensuring informational pages stay outside authentication.

Documentation (including the Theory of Operation), help files and the project
sponsorship/support page must be readable without signing in. These live in the
deny-by-default ``before_request`` allowlists in ``app.py``; if someone removes a
path from those allowlists this test fails loudly.
"""

from app import _PUBLIC_PAGE_PATHS, _PUBLIC_PAGE_PREFIXES, PUBLIC_API_GET_PATHS


def _is_public(path: str) -> bool:
    """Mirror the membership check used by app.before_request."""
    return path in _PUBLIC_PAGE_PATHS or any(
        path.startswith(prefix) for prefix in _PUBLIC_PAGE_PREFIXES
    )


def test_documentation_pages_are_public():
    # The documentation index and any doc under the /docs tree must be public,
    # including the Theory of Operation and the docs search.
    assert _is_public("/docs")
    assert _is_public("/docs/architecture/THEORY_OF_OPERATION")
    assert _is_public("/docs/search")
    assert _is_public("/docs/assets/diagram.png")
    assert _is_public("/repo-stats")


def test_help_files_are_public():
    assert _is_public("/help")
    assert _is_public("/about")


def test_support_page_is_public():
    assert _is_public("/support")


def test_broadcast_state_api_is_public():
    # base.html + the navbar poll /api/broadcast/state on every page (a 1.5s
    # WebSocket-fallback) to drive the air-chain overlay — including the login
    # page and after a session expires. It must stay in the public GET allowlist
    # or those polls flood the logs with 401s.
    assert "/api/broadcast/state" in PUBLIC_API_GET_PATHS
