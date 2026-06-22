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

"""Test API field fixes for runtime errors."""
import pytest


def test_api_uses_correct_message_type_field():
    """Test that api.py uses message_type instead of msg_type."""
    with open('webapp/admin/api.py', 'r') as f:
        content = f.read()
    
    # Verify we use the correct field name
    assert 'alert.message_type' in content
    # Verify we don't use the incorrect field name
    assert 'alert.msg_type' not in content


def test_api_system_status_has_db_error_handling():
    """Test that api_system_status function has proper database error handling."""
    with open('webapp/admin/api.py', 'r') as f:
        content = f.read()
    
    # Verify database error handling is present
    assert 'database_status' in content
    assert "db.session.rollback()" in content
    # Verify we use specific SQLAlchemy exceptions instead of bare Exception
    assert 'SQLAlchemyError' in content
    assert 'from sqlalchemy.exc import SQLAlchemyError' in content


def test_api_imports_syntax():
    """Test that api.py has valid Python syntax."""
    import py_compile
    py_compile.compile('webapp/admin/api.py', doraise=True)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
