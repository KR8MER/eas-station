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
    """Test that from __future__ import annotations is the first import."""
    with open('webapp/admin/dashboard.py', 'r') as f:
        lines = f.readlines()
    
    # Find first non-empty, non-comment line
    first_import_line = None
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith('#'):
            first_import_line = stripped
            break
    
    assert first_import_line == 'from __future__ import annotations'


def test_navbar_uses_auth_blueprint_routes():
    """Test that navbar_new.html uses correct auth blueprint routes."""
    with open('templates/components/navbar_new.html', 'r') as f:
        content = f.read()
    
    # Verify auth.logout is used instead of plain logout
    assert "url_for('auth.logout')" in content
    assert "url_for('logout')" not in content
    
    # Verify auth.login is used instead of plain login
    assert "url_for('auth.login')" in content
    assert "url_for('login')" not in content


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
