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

"""Test admin dashboard fixes for runtime errors."""
import re

import pytest


def test_dashboard_imports_syntax():
    """Test that dashboard.py has valid Python syntax."""
    # This will fail if there are syntax errors
    import py_compile
    py_compile.compile('webapp/admin/dashboard.py', doraise=True)


def test_dashboard_uses_current_app():
    """Test that dashboard.py uses current_app instead of app."""
    with open('webapp/admin/dashboard.py', 'r') as f:
        content = f.read()
    
    # Verify current_app is imported
    assert 'from flask import' in content
    assert 'current_app' in content
    
    # Verify we're not using undefined 'app' variable in routes
    # Check that the problematic line uses current_app
    assert "current_app.config.get('EAS_BROADCAST_ENABLED'" in content
    assert "current_app.config.get('EAS_OUTPUT_WEB_SUBDIR'" in content
    
    # Verify logger calls use current_app.logger
    assert 'current_app.logger.warning' in content
    assert 'current_app.logger.error' in content


def test_future_annotations_is_present():
    """Test that from __future__ import annotations is present before other imports."""
    with open('webapp/admin/dashboard.py', 'r') as f:
        content = f.read()

    # The file may start with a license docstring; __future__ import must appear
    # before any non-future import statement.
    assert 'from __future__ import annotations' in content

    future_pos = content.index('from __future__ import annotations')
    # No regular import should appear before the __future__ import
    for m in re.finditer(r'^(?:import |from (?!__future__))', content, re.MULTILINE):
        assert m.start() > future_pos, (
            f"Regular import found before 'from __future__ import annotations' at pos {m.start()}"
        )


def test_navbar_uses_auth_blueprint_routes():
    """Test that navbar.html uses correct auth blueprint routes."""
    with open('templates/components/navbar.html', 'r') as f:
        content = f.read()

    # Verify auth.logout is used instead of plain logout
    assert "url_for('auth.logout')" in content
    assert "url_for('logout')" not in content

    # Verify auth.login is used instead of plain login
    assert "url_for('auth.login')" in content
    assert "url_for('login')" not in content


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
