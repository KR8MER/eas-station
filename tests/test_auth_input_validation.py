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

"""Tests for authentication input validation and SQL injection prevention."""

import pytest
from app_core.auth.input_validation import InputValidator


class TestInputValidator:
    """Test InputValidator class for malicious input detection."""
    
    def test_validate_username_valid(self):
        """Test that valid usernames are accepted."""
        valid_usernames = [
            'admin',
            'user123',
            'john.doe',
            'jane_smith',
            'test-user',
            'user@example.com',
        ]
        
        for username in valid_usernames:
            is_valid, error = InputValidator.validate_username(username)
            assert is_valid, f"Valid username '{username}' was rejected: {error}"
            assert error is None
    
    def test_validate_username_sql_injection(self):
        """Test that SQL injection attempts in usernames are rejected."""
        sql_injection_attempts = [
            "' OR 1=1 --",
            "' OR '1'='1",
            "admin' --",
            "1' OR '1' = '1",
            "' OR 1=1; --",
            "admin'/*",
            "' UNION SELECT * FROM users --",
            "admin'; DROP TABLE users; --",
            "; DELETE FROM users WHERE 1=1 --",
            "1=1",
            "true; --",
        ]
        
        for attempt in sql_injection_attempts:
            is_valid, error = InputValidator.validate_username(attempt)
            assert not is_valid, f"SQL injection attempt '{attempt}' was not rejected"
            assert error == "Invalid username format"
    
    def test_validate_username_command_injection(self):
        """Test that command injection attempts in usernames are rejected."""
        command_injection_attempts = [
            "admin && whoami",
            "user; ls -la",
            "test | cat /etc/passwd",
            "admin`whoami`",
            "user$(whoami)",
            "test || echo hacked",
            "admin > /tmp/test",
            "user; cat /etc/passwd",
        ]
        
        for attempt in command_injection_attempts:
            is_valid, error = InputValidator.validate_username(attempt)
            assert not is_valid, f"Command injection attempt '{attempt}' was not rejected"
            assert error == "Invalid username format"
    
    def test_validate_username_empty(self):
        """Test that empty username is rejected."""
        is_valid, error = InputValidator.validate_username("")
        assert not is_valid
        assert error == "Username is required"
    
    def test_validate_username_too_long(self):
        """Test that overly long usernames are rejected."""
        long_username = "a" * (InputValidator.MAX_USERNAME_LENGTH + 1)
        is_valid, error = InputValidator.validate_username(long_username)
        assert not is_valid
        assert f"exceeds maximum length" in error
    
    def test_validate_username_non_printable(self):
        """Test that usernames with non-printable characters are rejected."""
        is_valid, error = InputValidator.validate_username("admin\x00test")
        assert not is_valid
        assert error == "Username contains invalid characters"
    
    def test_validate_password_valid(self):
        """Test that valid passwords are accepted."""
        valid_passwords = [
            "password123",
            "MyP@ssw0rd!",
            "verySecurePassword123!@#",
        ]
        
        for password in valid_passwords:
            is_valid, error = InputValidator.validate_password(password)
            assert is_valid, f"Valid password was rejected: {error}"
            assert error is None
    
    def test_validate_password_empty(self):
        """Test that empty password is rejected."""
        is_valid, error = InputValidator.validate_password("")
        assert not is_valid
        assert error == "Password is required"
    
    def test_validate_password_too_long(self):
        """Test that overly long passwords are rejected."""
        long_password = "a" * (InputValidator.MAX_PASSWORD_LENGTH + 1)
        is_valid, error = InputValidator.validate_password(long_password)
        assert not is_valid
        assert "exceeds maximum length" in error
    
    def test_sanitize_for_logging_removes_dangerous_chars(self):
        """Test that dangerous characters are removed when sanitizing for logs."""
        dangerous_inputs = [
            ("' OR 1=1; --", "OR11"),
            ("admin && whoami", "adminwhoami"),
            ("test`command`", "testcommand"),
            ("user$(cmd)", "usercmd"),
            ("admin; DROP TABLE", "adminDROPTABLE"),
        ]
        
        for input_val, expected_contains in dangerous_inputs:
            sanitized = InputValidator.sanitize_for_logging(input_val)
            # Check that dangerous characters are removed
            assert "'" not in sanitized
            assert ";" not in sanitized
            assert "`" not in sanitized
            assert "$" not in sanitized
            assert "(" not in sanitized
            assert ")" not in sanitized
    
    def test_sanitize_for_logging_truncates_long_input(self):
        """Test that long inputs are truncated for logging."""
        long_input = "a" * 200
        sanitized = InputValidator.sanitize_for_logging(long_input, max_length=100)
        assert len(sanitized) <= 103  # 100 + "..."
        assert sanitized.endswith("...")
    
    def test_sanitize_for_logging_preserves_safe_chars(self):
        """Test that safe characters are preserved."""
        safe_input = "admin_user.test@example.com"
        sanitized = InputValidator.sanitize_for_logging(safe_input)
        assert sanitized == safe_input
    
    def test_sanitize_for_logging_empty_string(self):
        """Test that empty strings are handled correctly."""
        sanitized = InputValidator.sanitize_for_logging("")
        assert sanitized == ""
        
        sanitized = InputValidator.sanitize_for_logging(None)
        assert sanitized == ""


class TestSQLInjectionPatterns:
    """Test specific SQL injection patterns that have been observed."""
    
    def test_observed_attack_pattern_1(self):
        """Test the observed pattern: ' OR 1=1 && whoami"""
        is_valid, error = InputValidator.validate_username("' OR 1=1 && whoami")
        assert not is_valid
        assert error == "Invalid username format"
    
    def test_observed_attack_pattern_2(self):
        """Test the observed pattern: ' OR 1=1; --"""
        is_valid, error = InputValidator.validate_username("' OR 1=1; --")
        assert not is_valid
        assert error == "Invalid username format"
    
    def test_sanitized_output_for_observed_patterns(self):
        """Test that observed attack patterns are properly sanitized for logging."""
        pattern1 = "' OR 1=1 && whoami"
        pattern2 = "' OR 1=1; --"
        
        sanitized1 = InputValidator.sanitize_for_logging(pattern1)
        sanitized2 = InputValidator.sanitize_for_logging(pattern2)
        
        # Ensure dangerous characters are removed
        assert "'" not in sanitized1
        assert "&&" not in sanitized1
        assert "'" not in sanitized2
        assert ";" not in sanitized2
        assert "--" not in sanitized2
        
        # But alphanumeric content is preserved
        assert "OR" in sanitized1
        assert "whoami" in sanitized1
        assert "OR" in sanitized2
