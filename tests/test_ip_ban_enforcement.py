"""
EAS Station - Emergency Alert System
Copyright (c) 2025-2026 Timothy Kramer (KR8MER)

Regression tests for global IP-ban enforcement.

Background: bans used to be checked only inside the login POST handler, so a
blocklisted IP was merely prevented from signing in while it could still browse
every page and hit every API. The Security Center work moved ban enforcement
into a global before_request gate backed by ``IPFilter.is_ip_blocked``. These
tests pin down that method's behaviour, which is what makes a ban actually
block.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

pytest.importorskip("flask")
pytest.importorskip("flask_sqlalchemy")

from app_utils import utc_now


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


def test_exact_blocklist_ip_is_blocked(app_with_filters):
    app, db = app_with_filters
    from app_core.auth.ip_filter import IPFilter, IPFilterReason

    with app.app_context():
        IPFilter.add_to_blocklist("203.0.113.7", reason=IPFilterReason.MANUAL.value)

        blocked, reason = IPFilter.is_ip_blocked("203.0.113.7")
        assert blocked is True
        assert reason == IPFilterReason.MANUAL.value

        # A different IP is not affected.
        assert IPFilter.is_ip_blocked("203.0.113.8") == (False, None)


def test_cidr_blocklist_matches_range(app_with_filters):
    app, db = app_with_filters
    from app_core.auth.ip_filter import IPFilter, IPFilterReason

    with app.app_context():
        IPFilter.add_to_blocklist("203.0.113.0/24", reason=IPFilterReason.AUTO_FLOOD.value)

        assert IPFilter.is_ip_blocked("203.0.113.55")[0] is True
        assert IPFilter.is_ip_blocked("198.51.100.1")[0] is False


def test_expired_ban_no_longer_blocks_and_is_deactivated(app_with_filters):
    app, db = app_with_filters
    from app_core.auth.ip_filter import IPFilter, IPFilterReason

    with app.app_context():
        entry = IPFilter.add_to_blocklist(
            "203.0.113.9", reason=IPFilterReason.AUTO_BRUTE_FORCE.value
        )
        # Force expiry into the past.
        entry.expires_at = utc_now() - timedelta(hours=1)
        db.session.commit()

        assert IPFilter.is_ip_blocked("203.0.113.9") == (False, None)
        # The expired entry should have been deactivated as a side effect.
        db.session.refresh(entry)
        assert entry.is_active is False


def test_allowlist_only_does_not_block_everyone(app_with_filters):
    """Safety property: an allowlist entry must not turn is_ip_blocked into a
    deny-all gate (that would brick the whole site for every other visitor)."""
    app, db = app_with_filters
    from app_core.auth.ip_filter import IPFilter

    with app.app_context():
        IPFilter.add_to_allowlist("203.0.113.10")

        # An IP that is NOT on the allowlist must still pass the ban gate.
        assert IPFilter.is_ip_blocked("198.51.100.42") == (False, None)


def test_inactive_blocklist_entry_does_not_block(app_with_filters):
    app, db = app_with_filters
    from app_core.auth.ip_filter import IPFilter, IPFilterReason

    with app.app_context():
        entry = IPFilter.add_to_blocklist("203.0.113.11", reason=IPFilterReason.MANUAL.value)
        entry.is_active = False
        db.session.commit()

        assert IPFilter.is_ip_blocked("203.0.113.11") == (False, None)
