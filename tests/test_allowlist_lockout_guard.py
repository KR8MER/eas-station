"""
EAS Station - Emergency Alert System
Copyright (c) 2025-2026 Timothy Kramer (KR8MER)

Regression tests for the allowlist self-lockout guard.

Background: the moment any active allowlist entry exists, login flips into
allowlist-only mode (``IPFilter.is_ip_allowed`` / ``webapp/admin/auth.py``) where
only listed IPs may sign in and loopback is NOT exempt. An admin who allowlisted
a range that excluded their own IP (e.g. a private LAN range on a public
deployment) locked themselves out of login entirely. ``add_ip_filter`` now
refuses such an addition unless ``confirm_lockout`` is supplied; this pins down
the decision helper that drives that refusal.
"""

from __future__ import annotations

import pytest

pytest.importorskip("flask")
pytest.importorskip("flask_sqlalchemy")


@pytest.fixture
def app_with_filters():
    """Minimal Flask app + in-memory SQLite with the ip_filters table created."""
    from flask import Flask
    from app_core.extensions import db

    app = Flask(__name__)
    app.secret_key = "test-secret"
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    db.init_app(app)

    from app_core import models  # noqa: F401  (registers mappers)

    with app.app_context():
        from app_core.auth.ip_filter import IPFilter

        IPFilter.__table__.create(db.engine)
        yield app, db


def test_lan_range_excluding_admin_is_flagged(app_with_filters):
    """The exact footgun: allowlisting 192.168.0.0/16 from a public IP."""
    app, _ = app_with_filters
    from app_core.auth.ip_filter import IPFilter

    with app.app_context():
        assert IPFilter.allowlist_addition_would_lock_out("203.0.113.7", "192.168.0.0/16") is True


def test_entry_covering_admin_is_safe(app_with_filters):
    app, _ = app_with_filters
    from app_core.auth.ip_filter import IPFilter

    with app.app_context():
        # Admin IP falls inside the new entry -> no lockout.
        assert IPFilter.allowlist_addition_would_lock_out("192.168.1.5", "192.168.0.0/16") is False
        # Exact-match entry for the admin's own IP -> no lockout.
        assert IPFilter.allowlist_addition_would_lock_out("203.0.113.7", "203.0.113.7") is False


def test_admin_already_covered_by_existing_entry_is_safe(app_with_filters):
    app, db = app_with_filters
    from app_core.auth.ip_filter import IPFilter

    with app.app_context():
        # Admin previously allowlisted their own IP; adding an unrelated range
        # must not be flagged because they remain reachable.
        IPFilter.add_to_allowlist("203.0.113.7")
        assert IPFilter.allowlist_addition_would_lock_out("203.0.113.7", "10.0.0.0/8") is False


def test_inactive_existing_entry_does_not_count_as_coverage(app_with_filters):
    app, db = app_with_filters
    from app_core.auth.ip_filter import IPFilter

    with app.app_context():
        entry = IPFilter.add_to_allowlist("203.0.113.7")
        entry.is_active = False
        db.session.commit()

        # The only entry covering the admin is inactive, so the new range would
        # still lock them out.
        assert IPFilter.allowlist_addition_would_lock_out("203.0.113.7", "10.0.0.0/8") is True


def test_missing_admin_ip_never_flags(app_with_filters):
    app, _ = app_with_filters
    from app_core.auth.ip_filter import IPFilter

    with app.app_context():
        assert IPFilter.allowlist_addition_would_lock_out(None, "192.168.0.0/16") is False
        assert IPFilter.allowlist_addition_would_lock_out("", "192.168.0.0/16") is False
