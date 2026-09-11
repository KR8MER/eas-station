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

Tests for _validate_git_ref (webapp/admin/maintenance/routes_operations.py),
the guard in front of the two places a request-supplied branch/tag/commit
reaches a `git`/update-script subprocess call (System Upgrade's "check for
updates" and the upgrade itself). Renamed from a bool-returning
_is_valid_git_ref to one that returns the sanitized value re-derived from
the regex match, after CodeQL's py/command-line-injection flagged the old
shape -- a separate bool check followed by reuse of the original string
isn't recognized as a sanitizer, but reassigning from match.group(0) is.
"""

from __future__ import annotations

from webapp.admin.maintenance.routes_operations import _validate_git_ref


class TestValidateGitRef:
    def test_accepts_a_plain_branch_name(self):
        assert _validate_git_ref("main") == "main"

    def test_accepts_a_version_tag(self):
        assert _validate_git_ref("v2.232.0") == "v2.232.0"

    def test_accepts_a_full_commit_sha(self):
        sha = "a" * 40
        assert _validate_git_ref(sha) == sha

    def test_accepts_a_ref_with_slashes(self):
        assert _validate_git_ref("feature/my-branch") == "feature/my-branch"

    def test_rejects_empty(self):
        assert _validate_git_ref("") is None

    def test_rejects_a_leading_dash_flag_injection_attempt(self):
        assert _validate_git_ref("--upload-pack=/bin/sh") is None

    def test_rejects_a_double_dot_range_expression(self):
        assert _validate_git_ref("main..evil") is None

    def test_rejects_embedded_whitespace(self):
        assert _validate_git_ref("main; rm -rf /") is None

    def test_rejects_shell_metacharacters(self):
        for bad in ("main`whoami`", "main$(whoami)", "main|cat", "main&&ls"):
            assert _validate_git_ref(bad) is None, bad

    def test_returns_a_value_derived_from_the_match_not_the_original_string(self):
        # Same content either way here, but the point is the *code path*:
        # the return value must come from match.group(0), not from
        # returning the caller's own `ref` variable directly.
        result = _validate_git_ref("main")
        assert isinstance(result, str)
        assert result == "main"
