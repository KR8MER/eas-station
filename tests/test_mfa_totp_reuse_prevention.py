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

"""Test TOTP code replay prevention.

Replay prevention keys off the RFC 6238 *time step* a code belongs to, not off
elapsed wall-clock time since the last login.  The distinction matters: an
elapsed-time check cannot tell a replayed code from the brand-new one the
authenticator rotated to, so it rejects both — which locked operators out for
90 seconds after every login and forced them to wait out several code rotations.
"""

import time
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, Mock, patch

import pytest

from app_core.auth.mfa import (
    TOTP_INTERVAL_SECONDS,
    MFAManager,
    enroll_user_mfa,
    verify_user_mfa,
)

TEST_SECRET = "JBSWY3DPEHPK3PXP"


@pytest.fixture
def mock_user():
    """Create a mock user with MFA enabled and no code spent yet."""
    user = Mock()
    user.id = 1
    user.username = "testuser"
    user.mfa_enabled = True
    user.mfa_secret = TEST_SECRET
    user.mfa_backup_codes_hash = None
    user.mfa_last_totp_at = None
    user.mfa_last_totp_counter = None
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
        mock_now.return_value = datetime(2025, 12, 3, 12, 0, 0, tzinfo=timezone.utc)
        yield mock_now


@pytest.fixture
def mock_logger():
    """Mock Flask app logger.

    ``new=`` is passed explicitly so mock never introspects the real
    ``current_app`` LocalProxy — resolving it outside an application context
    raises, which is what previously made every test in this module error out
    during fixture setup.
    """
    replacement = Mock()
    replacement.logger = Mock()
    with patch('app_core.auth.mfa.current_app', new=replacement):
        yield replacement.logger


def _counter_now() -> int:
    """The time step the current real clock falls in."""
    return int(time.time()) // TOTP_INTERVAL_SECONDS


# ---------------------------------------------------------------------------
# verify_totp_with_counter: which time step did this code come from?
# ---------------------------------------------------------------------------


def test_counter_matches_current_time_step():
    """A freshly generated code reports the current time step."""
    pyotp = pytest.importorskip("pyotp")
    code = pyotp.TOTP(TEST_SECRET).now()

    is_valid, counter = MFAManager.verify_totp_with_counter(TEST_SECRET, code)

    assert is_valid is True
    assert counter == _counter_now()


def test_counter_reports_skewed_step_for_previous_code():
    """A code from the previous step verifies but reports that older step."""
    pyotp = pytest.importorskip("pyotp")
    totp = pyotp.TOTP(TEST_SECRET)
    previous_code = totp.at(int(time.time()), -1)

    is_valid, counter = MFAManager.verify_totp_with_counter(TEST_SECRET, previous_code)

    assert is_valid is True
    assert counter == _counter_now() - 1


def test_invalid_code_reports_no_counter():
    """A wrong code is rejected and yields no time step."""
    pytest.importorskip("pyotp")
    assert MFAManager.verify_totp_with_counter(TEST_SECRET, "000000") == (False, None)


def test_spaces_in_submitted_code_are_tolerated():
    """Codes pasted as displayed ("123 456") still verify."""
    pyotp = pytest.importorskip("pyotp")
    code = pyotp.TOTP(TEST_SECRET).now()
    spaced = f"{code[:3]} {code[3:]}"

    assert MFAManager.verify_totp_with_counter(TEST_SECRET, spaced)[0] is True


def test_blank_code_is_rejected():
    """An empty submission never verifies (and never raises)."""
    pytest.importorskip("pyotp")
    assert MFAManager.verify_totp_with_counter(TEST_SECRET, "") == (False, None)
    assert MFAManager.verify_totp_with_counter(TEST_SECRET, "   ") == (False, None)


# ---------------------------------------------------------------------------
# verify_user_mfa: replay rejection without punishing new codes
# ---------------------------------------------------------------------------


def test_first_totp_code_succeeds(mock_user, mock_db_session, mock_utc_now, mock_logger):
    """A valid code succeeds on first use and records its time step."""
    with patch('app_core.auth.mfa.verify_totp_code_with_counter', return_value=(True, 100)):
        result = verify_user_mfa(mock_user, "123456")

    assert result is True
    assert mock_user.mfa_last_totp_counter == 100
    assert mock_user.mfa_last_totp_at == mock_utc_now.return_value
    mock_db_session.commit.assert_called_once()


def test_replaying_the_same_code_fails(mock_user, mock_db_session, mock_utc_now, mock_logger):
    """Submitting an already-spent code again is rejected."""
    mock_user.mfa_last_totp_counter = 100

    with patch('app_core.auth.mfa.verify_totp_code_with_counter', return_value=(True, 100)):
        result = verify_user_mfa(mock_user, "123456")

    assert result is False
    assert mock_user.mfa_last_totp_counter == 100  # unchanged
    mock_db_session.commit.assert_not_called()
    mock_logger.warning.assert_called_once()
    assert "TOTP code reuse attempt" in mock_logger.warning.call_args[0][0]


def test_older_code_after_a_newer_one_fails(mock_user, mock_db_session, mock_utc_now, mock_logger):
    """A code from a step at or before the last accepted one is a replay.

    Clock skew means the previous step's code is still cryptographically valid;
    once a later step has been spent it must not be accepted again.
    """
    mock_user.mfa_last_totp_counter = 100

    with patch('app_core.auth.mfa.verify_totp_code_with_counter', return_value=(True, 99)):
        result = verify_user_mfa(mock_user, "111111")

    assert result is False
    assert mock_user.mfa_last_totp_counter == 100


def test_next_code_succeeds_immediately(mock_user, mock_db_session, mock_utc_now, mock_logger):
    """The regression: the very next rotated code works right away.

    Under the old elapsed-time rule this login was rejected for 90 seconds
    after the previous one, so operators had to wait out several rotations.
    """
    mock_user.mfa_last_totp_counter = 100

    with patch('app_core.auth.mfa.verify_totp_code_with_counter', return_value=(True, 101)):
        result = verify_user_mfa(mock_user, "654321")

    assert result is True
    assert mock_user.mfa_last_totp_counter == 101
    mock_db_session.commit.assert_called_once()


def test_legacy_row_without_counter_accepts_next_code(
    mock_user, mock_db_session, mock_utc_now, mock_logger
):
    """Rows written before the counter column fall back to the timestamp.

    The derived counter still blocks a replay inside the same 30-second step,
    but the next step's code is accepted immediately rather than after 90 s.
    """
    last_login = datetime(2025, 12, 3, 12, 0, 10, tzinfo=timezone.utc)
    mock_user.mfa_last_totp_counter = None
    mock_user.mfa_last_totp_at = last_login
    legacy_counter = int(last_login.timestamp()) // TOTP_INTERVAL_SECONDS

    # Same step as the recorded login -> replay.
    with patch(
        'app_core.auth.mfa.verify_totp_code_with_counter', return_value=(True, legacy_counter)
    ):
        assert verify_user_mfa(mock_user, "123456") is False

    # Next step -> accepted, and the exact counter is recorded from now on.
    with patch(
        'app_core.auth.mfa.verify_totp_code_with_counter',
        return_value=(True, legacy_counter + 1),
    ):
        assert verify_user_mfa(mock_user, "654321") is True
    assert mock_user.mfa_last_totp_counter == legacy_counter + 1


def test_invalid_totp_code_fails(mock_user, mock_db_session, mock_utc_now, mock_logger):
    """An invalid code fails and spends nothing."""
    with patch('app_core.auth.mfa.verify_totp_code_with_counter', return_value=(False, None)):
        result = verify_user_mfa(mock_user, "000000")

    assert result is False
    assert mock_user.mfa_last_totp_at is None
    assert mock_user.mfa_last_totp_counter is None
    mock_db_session.commit.assert_not_called()


def test_backup_code_still_works(mock_user, mock_db_session, mock_utc_now, mock_logger):
    """Backup codes remain unaffected by TOTP replay tracking."""
    mock_user.mfa_backup_codes_hash = '["hash1", "hash2"]'

    with patch('app_core.auth.mfa.verify_totp_code_with_counter', return_value=(False, None)):
        with patch(
            'app_core.auth.mfa.MFAManager.verify_backup_code',
            return_value=(True, '["hash2"]'),
        ):
            result = verify_user_mfa(mock_user, "BACKUPCODE123")

    assert result is True
    assert mock_user.mfa_backup_codes_hash == '["hash2"]'
    mock_db_session.commit.assert_called_once()


def test_enrollment_spends_the_enrollment_code(mock_db_session, mock_utc_now, mock_logger):
    """Enrollment records the enrolling code's step so it can't be replayed."""
    user = Mock()
    user.username = "newuser"
    user.mfa_secret = TEST_SECRET
    user.mfa_enabled = False
    user.mfa_enrolled_at = None
    user.mfa_last_totp_at = None
    user.mfa_last_totp_counter = None

    with patch('app_core.auth.mfa.verify_totp_code_with_counter', return_value=(True, 500)):
        with patch(
            'app_core.auth.mfa.MFAManager.generate_backup_codes', return_value=["CODE1", "CODE2"]
        ):
            with patch(
                'app_core.auth.mfa.MFAManager.hash_backup_codes',
                return_value='["hash1", "hash2"]',
            ):
                success, codes = enroll_user_mfa(user, "123456")

    assert success is True
    assert user.mfa_enabled is True
    assert user.mfa_enrolled_at == mock_utc_now.return_value
    assert user.mfa_last_totp_counter == 500
    assert codes == ["CODE1", "CODE2"]
    mock_db_session.commit.assert_called_once()


def test_end_to_end_new_code_accepted_after_previous_login(
    mock_user, mock_db_session, mock_logger
):
    """Full path with real pyotp: consecutive steps both authenticate.

    No mocking of the verifier — this is the operator-visible behaviour that
    regressed, exercised against real code generation.
    """
    pyotp = pytest.importorskip("pyotp")
    totp = pyotp.TOTP(TEST_SECRET)
    now_ts = int(time.time())

    with patch('app_core.auth.mfa.utc_now', return_value=datetime.now(timezone.utc)):
        # Log in with the previous step's code (valid within the skew window).
        assert verify_user_mfa(mock_user, totp.at(now_ts, -1)) is True
        spent = mock_user.mfa_last_totp_counter

        # Replaying it fails...
        assert verify_user_mfa(mock_user, totp.at(now_ts, -1)) is False
        assert mock_user.mfa_last_totp_counter == spent

        # ...but the current code is accepted without waiting.
        assert verify_user_mfa(mock_user, totp.now()) is True
        assert mock_user.mfa_last_totp_counter == spent + 1


def test_login_survives_missing_counter_column(mock_user, mock_utc_now, mock_logger):
    """A database without the counter column must not break MFA login.

    ``update.sh`` migrates before restarting, but the documented bare
    ``git pull`` + restart flow does not — the commit would then fail on the
    unknown column and reject an otherwise valid code.
    """
    mock_user.mfa_last_totp_counter = None

    commits = []

    def _commit():
        commits.append(getattr(mock_user, 'mfa_last_totp_counter', 'missing'))
        if len(commits) == 1:
            raise RuntimeError('column "mfa_last_totp_counter" does not exist')

    with patch('app_core.auth.mfa.db.session') as session:
        session.commit.side_effect = _commit
        session.rollback = MagicMock()
        with patch(
            'app_core.auth.mfa.verify_totp_code_with_counter', return_value=(True, 100)
        ):
            result = verify_user_mfa(mock_user, "123456")

    assert result is True, "valid code rejected because the counter could not be stored"
    assert len(commits) == 2, "no retry without the new column"
    assert session.rollback.called
    assert mock_user.mfa_last_totp_at == mock_utc_now.return_value
    mock_logger.error.assert_called_once()
