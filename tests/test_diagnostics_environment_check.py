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

"""Regression test for the environment-config diagnostic check.

check_environment_config() used to check os.getenv('POSTGRES_PASSWORD') as
a "critical" variable. app.py reads DATABASE_URL directly and raises at
startup if it's missing -- there's no discrete POSTGRES_HOST/PORT/DB/USER/
PASSWORD fallback in the running app, and install.sh / .env.example both
only ever set DATABASE_URL. So on every current-style install,
POSTGRES_PASSWORD was never set, and this check permanently reported a
false-positive "POSTGRES_PASSWORD is not set" warning on the Diagnostics
page. Fixed to check DATABASE_URL's embedded password instead.
"""

import pytest

import webapp.routes_diagnostics as diagnostics

pytestmark = pytest.mark.unit


def test_database_url_with_a_real_password_passes(monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "a" * 32)
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql+psycopg2://eas_station:a-real-secure-password@127.0.0.1:5432/alerts",
    )
    monkeypatch.setenv("DEFAULT_STATE_CODE", "OH")
    monkeypatch.setenv("DEFAULT_COUNTY_NAME", "Putnam County")

    result = diagnostics.check_environment_config()

    assert any("DATABASE_URL is configured" in msg for msg in result["passed"])
    assert not any("DATABASE_URL" in msg for msg in result["warnings"])
    assert not any("POSTGRES_PASSWORD" in msg for msg in result["warnings"])


def test_database_url_with_weak_password_warns(monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "a" * 32)
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql+psycopg2://eas_station:changeme@127.0.0.1:5432/alerts",
    )
    monkeypatch.setenv("DEFAULT_STATE_CODE", "OH")
    monkeypatch.setenv("DEFAULT_COUNTY_NAME", "Putnam County")

    result = diagnostics.check_environment_config()

    assert any("DATABASE_URL uses a known weak/default database password" in msg for msg in result["warnings"])


def test_missing_database_url_warns_as_not_set(monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "a" * 32)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("DEFAULT_STATE_CODE", "OH")
    monkeypatch.setenv("DEFAULT_COUNTY_NAME", "Putnam County")

    result = diagnostics.check_environment_config()

    assert any("DATABASE_URL is not set" in msg for msg in result["warnings"])
