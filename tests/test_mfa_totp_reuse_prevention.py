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

"""Test TOTP code reuse prevention functionality."""

import pytest
from datetime import datetime, timedelta
from unittest.mock import Mock, patch, MagicMock

from app_core.auth.mfa import verify_user_mfa, enroll_user_mfa, MFAManager


@pytest.fixture
def mock_user():
    """Create a mock user with MFA enabled."""
    user = Mock()
    user.id = 1
    user.username = "testuser"
    user.mfa_enabled = True
    user.mfa_secret = "JBSWY3DPEHPK3PXP"  # Example TOTP secret
    user.mfa_backup_codes_hash = None
    user.mfa_last_totp_at = None
    return user


@pytest.fixture
def mock_db_session():
    """Mock the database session."""
    with patch('app_core.auth.mfa.db.session') as mock_session:
        mock_session.commit = MagicMock()
        yield mock_session


@pytest.fixture
def mock_utc_now():
    """Mock utc_now function."""
    with patch('app_core.auth.mfa.utc_now') as mock_now:
        yield mock_now


@pytest.fixture
def mock_logger():
    """Mock Flask app logger."""
    with patch('app_core.auth.mfa.current_app') as mock_app:
        mock_app.logger = Mock()
        yield mock_app.logger


def test_first_totp_code_succeeds(mock_user, mock_db_session, mock_utc_now, mock_logger):
    """Test that a valid TOTP code succeeds on first use."""
    current_time = datetime(2025, 12, 3, 12, 0, 0)
    mock_utc_now.return_value = current_time
    
    # Mock the verify_totp_code to return True (valid code)
    with patch('app_core.auth.mfa.verify_totp_code', return_value=True):
        result = verify_user_mfa(mock_user, "123456")
    
    assert result is True
    assert mock_user.mfa_last_totp_at == current_time
    mock_db_session.commit.assert_called_once()


def test_totp_code_reuse_within_90_seconds_fails(mock_user, mock_db_session, mock_utc_now, mock_logger):
    """Test that reusing a TOTP code within 90 seconds fails."""
    first_use_time = datetime(2025, 12, 3, 12, 0, 0)
    second_use_time = first_use_time + timedelta(seconds=30)  # 30 seconds later
    
    # Simulate first use
    mock_user.mfa_last_totp_at = first_use_time
    mock_utc_now.return_value = second_use_time
    
    # Mock the verify_totp_code to return True (code is still technically valid)
    with patch('app_core.auth.mfa.verify_totp_code', return_value=True):
        result = verify_user_mfa(mock_user, "123456")
    
    assert result is False
    assert mock_user.mfa_last_totp_at == first_use_time  # Timestamp unchanged
    mock_logger.warning.assert_called_once()
    assert "TOTP code reuse attempt" in mock_logger.warning.call_args[0][0]


def test_totp_code_succeeds_after_90_seconds(mock_user, mock_db_session, mock_utc_now, mock_logger):
    """Test that a TOTP code can be used after 90 seconds."""
    first_use_time = datetime(2025, 12, 3, 12, 0, 0)
    second_use_time = first_use_time + timedelta(seconds=91)  # 91 seconds later
    
    # Simulate first use
    mock_user.mfa_last_totp_at = first_use_time
    mock_utc_now.return_value = second_use_time
    
    # Mock the verify_totp_code to return True (valid code)
    with patch('app_core.auth.mfa.verify_totp_code', return_value=True):
        result = verify_user_mfa(mock_user, "654321")
    
    assert result is True
    assert mock_user.mfa_last_totp_at == second_use_time  # Timestamp updated
    mock_db_session.commit.assert_called_once()


def test_invalid_totp_code_fails(mock_user, mock_db_session, mock_utc_now, mock_logger):
    """Test that an invalid TOTP code fails."""
    current_time = datetime(2025, 12, 3, 12, 0, 0)
    mock_utc_now.return_value = current_time
    
    # Mock the verify_totp_code to return False (invalid code)
    with patch('app_core.auth.mfa.verify_totp_code', return_value=False):
        result = verify_user_mfa(mock_user, "000000")
    
    assert result is False
    assert mock_user.mfa_last_totp_at is None  # Timestamp not set
    mock_db_session.commit.assert_not_called()


def test_totp_reuse_just_under_90_seconds_fails(mock_user, mock_db_session, mock_utc_now, mock_logger):
    """Test that reusing a TOTP code just under 90 seconds still fails."""
    first_use_time = datetime(2025, 12, 3, 12, 0, 0)
    second_use_time = first_use_time + timedelta(seconds=89.9)  # Just under 90 seconds
    
    # Simulate first use
    mock_user.mfa_last_totp_at = first_use_time
    mock_utc_now.return_value = second_use_time
    
    # Mock the verify_totp_code to return True
    with patch('app_core.auth.mfa.verify_totp_code', return_value=True):
        result = verify_user_mfa(mock_user, "123456")
    
    assert result is False
    assert mock_user.mfa_last_totp_at == first_use_time  # Timestamp unchanged


def test_backup_code_still_works(mock_user, mock_db_session, mock_utc_now, mock_logger):
    """Test that backup codes still work normally."""
    current_time = datetime(2025, 12, 3, 12, 0, 0)
    mock_utc_now.return_value = current_time
    
    # Set up backup codes
    mock_user.mfa_backup_codes_hash = '["hash1", "hash2"]'
    
    # Mock verify_totp_code to return False (not a TOTP code)
    # Mock verify_backup_code to return True
    with patch('app_core.auth.mfa.verify_totp_code', return_value=False):
        with patch('app_core.auth.mfa.MFAManager.verify_backup_code', return_value=(True, '["hash2"]')):
            result = verify_user_mfa(mock_user, "BACKUPCODE123")
    
    assert result is True
    assert mock_user.mfa_backup_codes_hash == '["hash2"]'
    mock_db_session.commit.assert_called_once()


def test_enrollment_initializes_timestamp(mock_db_session, mock_utc_now, mock_logger):
    """Test that enrollment initializes the last TOTP timestamp."""
    current_time = datetime(2025, 12, 3, 12, 0, 0)
    mock_utc_now.return_value = current_time
    
    user = Mock()
    user.username = "newuser"
    user.mfa_secret = "JBSWY3DPEHPK3PXP"
    user.mfa_enabled = False
    user.mfa_enrolled_at = None
    user.mfa_last_totp_at = None
    
    # Mock verify_totp_code to return True
    with patch('app_core.auth.mfa.verify_totp_code', return_value=True):
        with patch('app_core.auth.mfa.MFAManager.generate_backup_codes', return_value=["CODE1", "CODE2"]):
            with patch('app_core.auth.mfa.MFAManager.hash_backup_codes', return_value='["hash1", "hash2"]'):
                success, codes = enroll_user_mfa(user, "123456")
    
    assert success is True
    assert user.mfa_enabled is True
    assert user.mfa_enrolled_at == current_time
    assert user.mfa_last_totp_at == current_time
    mock_db_session.commit.assert_called_once()
