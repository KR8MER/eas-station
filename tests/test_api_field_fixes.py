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

"""Test API field fixes for runtime errors.

These read the admin API source rather than calling it, because what they
guard is a name that only fails at request time: ``alert.msg_type`` raises
``AttributeError`` inside a handler, which the route's own ``except`` turns
into a 500 rather than a test failure.

The source used to be a single ``webapp/admin/api.py``; it is the
``webapp/admin/api/`` package now, so these scan the package. Reading a
directory rather than a fixed filename also means a future split cannot make
them pass vacuously — an assertion against a file that no longer exists fails
loudly, but one against a shim that no longer holds the code would not.
"""
import py_compile
from pathlib import Path

import pytest

PACKAGE_DIR = Path(__file__).resolve().parents[1] / 'webapp' / 'admin' / 'api'


def _package_files() -> list[Path]:
    files = sorted(PACKAGE_DIR.glob('*.py'))
    assert files, f'no modules found in {PACKAGE_DIR} — has the package moved?'
    return files


def _package_source() -> str:
    return '\n'.join(p.read_text(encoding='utf-8') for p in _package_files())


def test_api_uses_correct_message_type_field():
    """The admin API must use message_type, not the non-existent msg_type."""
    content = _package_source()

    # Verify we use the correct field name
    assert 'alert.message_type' in content
    # Verify we don't use the incorrect field name
    assert 'alert.msg_type' not in content


def test_api_system_status_has_db_error_handling():
    """api_system_status must handle a database failure specifically."""
    content = (PACKAGE_DIR / 'routes_system.py').read_text(encoding='utf-8')

    # Verify database error handling is present
    assert 'database_status' in content
    assert "db.session.rollback()" in content
    # Verify we use specific SQLAlchemy exceptions instead of bare Exception
    assert 'SQLAlchemyError' in content
    assert 'from sqlalchemy.exc import SQLAlchemyError' in content


def test_api_imports_syntax():
    """Every module in the package has valid Python syntax."""
    for path in _package_files():
        py_compile.compile(str(path), doraise=True)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
