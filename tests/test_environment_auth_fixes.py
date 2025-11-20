"""
EAS Station - Emergency Alert System
Copyright (c) 2025 Timothy Kramer (KR8MER)

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

"""Test fixes for NameError and BuildError in environment and auth modules."""
import pytest


def test_environment_imports_logging():
    """Test that environment.py imports logging module."""
    with open('webapp/admin/environment.py', 'r') as f:
        content = f.read()
    
    # Verify logging is imported
    assert 'import logging' in content
    
    # Verify logger is instantiated
    assert 'logger = logging.getLogger(__name__)' in content


def test_environment_py_syntax():
    """Test that environment.py has valid Python syntax."""
    import py_compile
    py_compile.compile('webapp/admin/environment.py', doraise=True)


def test_environment_html_uses_blueprint_route():
    """Test that environment.html uses correct blueprint route for download."""
    with open('templates/settings/environment.html', 'r') as f:
        content = f.read()
    
    # Verify url_for uses blueprint prefix
    assert "url_for('environment.admin_download_env')" in content
    
    # Verify we're not using the old route without blueprint
    assert "url_for('admin_download_env')" not in content


def test_auth_py_syntax():
    """Test that auth.py has valid Python syntax."""
    import py_compile
    py_compile.compile('webapp/admin/auth.py', doraise=True)


def test_auth_uses_blueprint_route():
    """Test that auth.py uses correct blueprint route for mfa_verify."""
    with open('webapp/admin/auth.py', 'r') as f:
        content = f.read()
    
    # Verify url_for uses blueprint prefix for mfa_verify
    assert "url_for('auth.mfa_verify'" in content
    
    # Verify we're not using the old route without blueprint
    # Note: We need to be careful to not match comments or strings
    lines = content.split('\n')
    for line in lines:
        # Skip comments
        if line.strip().startswith('#'):
            continue
        # Check that we don't have the incorrect pattern
        if "url_for('mfa_verify'" in line and "url_for('auth.mfa_verify'" not in line:
            pytest.fail(f"Found incorrect url_for('mfa_verify') without blueprint prefix: {line}")


def test_logger_used_in_environment():
    """Test that logger is actually used in environment.py (regression test)."""
    with open('webapp/admin/environment.py', 'r') as f:
        content = f.read()
    
    # Verify logger is used in various places
    assert 'logger.info(' in content
    assert 'logger.error(' in content
    assert 'logger.warning(' in content or 'logger.debug(' in content
