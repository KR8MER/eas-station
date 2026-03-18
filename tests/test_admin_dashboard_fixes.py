"""
EAS Station - Emergency Alert System
Copyright (c) 2025-2026 Timothy Kramer (KR8MER)

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


def test_future_annotations_is_first():
    """Test that from __future__ import annotations is the first import.

    Python requires module docstrings to precede __future__ imports (PEP 236),
    so we skip over any leading docstring block and comments before checking.
    """
    with open('webapp/admin/dashboard.py', 'r') as f:
        lines = f.readlines()

    # Skip blank lines, comment lines, and module-level docstring blocks.
    # A single-line docstring opens and closes with the same triple-quote on one
    # line (e.g. """text""" or """""").  A multi-line docstring spans until the
    # next occurrence of the matching closing triple-quote.
    in_docstring = False
    docstring_quote = None
    first_import_line = None
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith('#'):
            continue
        if in_docstring:
            # Look for the closing triple-quote
            if docstring_quote in stripped:
                in_docstring = False
                docstring_quote = None
            continue
        # Detect start of a triple-quoted string block
        for quote in ('"""', "'''"):
            if stripped.startswith(quote):
                rest = stripped[len(quote):]
                # Single-line: the closing quote appears in rest (handles empty
                # docstrings like """""" where rest == '"""')
                if quote in rest:
                    break  # single-line — skip and move to next line
                # Multi-line: wait for closing quote on a later line
                in_docstring = True
                docstring_quote = quote
                break
        else:
            # Not a blank/comment/docstring — this is the first real code line
            first_import_line = stripped
            break

    assert first_import_line == 'from __future__ import annotations'


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
