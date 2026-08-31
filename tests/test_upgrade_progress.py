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

Tests for the one-click upgrade's live progress feed
(webapp/admin/maintenance/routes_operations.py).

The one-click "System Upgrade" button runs update.sh as its own systemd
unit (eas-station-update.service, launched via bin/eas-station-run-update)
instead of as a direct child of eas-station-web.service, specifically so
update.sh's own "Restarting Services" step doesn't kill the process
reporting on it. get_upgrade_progress() reads that unit's state and journal
back out, deliberately never touching the in-memory _OPERATION_STATE dict
that resets when this worker restarts.

Result detection is journal-first, not unit-state-first: manual testing
against a real systemd-run --collect unit showed it gets garbage-collected
within a couple of seconds of exiting, success or failure alike, so
`systemctl show` reliably answers "is it running right now" but not "how
did it end" -- by the time anything polls, the unit routinely already looks
exactly like one that never ran. The journal doesn't get cleaned up, so
update.sh's own "=== UPDATE RESULT: ... ===" marker (or, if it crashed
before reaching that, systemd's own "Failed with result" / "Main process
exited" / "Deactivated successfully" lines for the same unit) is what these
tests -- and the endpoint -- actually rely on.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from webapp.admin.maintenance.routes_operations import (
    _classify_upgrade_log_line,
    check_for_upgrade,
    get_upgrade_progress,
    list_upgrade_tags,
)


class TestClassifyUpgradeLogLine:
    def test_step_line(self):
        result = _classify_upgrade_log_line("--- Step 7/12: Updating Python Dependencies ---")
        assert result["level"] == "step"
        assert result["step"] == {"num": 7, "total": 12, "label": "Updating Python Dependencies"}

    def test_success_line(self):
        result = _classify_upgrade_log_line("[ OK ]  Backup created: /var/backups/x.tar.gz")
        assert result["level"] == "success"
        assert result["step"] is None

    def test_info_line(self):
        result = _classify_upgrade_log_line("[INFO]  Using git to update...")
        assert result["level"] == "info"

    def test_warning_line(self):
        result = _classify_upgrade_log_line("[WARN]  Backup failed (non-critical)")
        assert result["level"] == "warning"

    def test_error_line(self):
        result = _classify_upgrade_log_line("[ERROR] Alembic not found in venv")
        assert result["level"] == "error"

    def test_success_result_marker(self):
        result = _classify_upgrade_log_line("=== UPDATE RESULT: SUCCESS ===")
        assert result["level"] == "result-success"

    def test_failure_result_marker(self):
        result = _classify_upgrade_log_line("=== UPDATE RESULT: ISSUES DETECTED ===")
        assert result["level"] == "result-failed"

    def test_systemd_failed_with_result_line(self):
        # Actual journal text observed from a real failing run.
        result = _classify_upgrade_log_line(
            "eas-station-update.service: Failed with result 'exit-code'."
        )
        assert result["level"] == "unit-failed"

    def test_systemd_main_process_exited_nonzero(self):
        result = _classify_upgrade_log_line(
            "eas-station-update.service: Main process exited, code=exited, status=1/FAILURE"
        )
        assert result["level"] == "unit-failed"

    def test_systemd_main_process_exited_zero_is_not_a_failure(self):
        result = _classify_upgrade_log_line(
            "eas-station-update.service: Main process exited, code=exited, status=0/SUCCESS"
        )
        assert result["level"] == "plain"

    def test_systemd_deactivated_successfully(self):
        result = _classify_upgrade_log_line("eas-station-update.service: Deactivated successfully.")
        assert result["level"] == "unit-deactivated-ok"

    def test_unrecognized_line_is_plain(self):
        result = _classify_upgrade_log_line("Some raw shell output with no prefix")
        assert result["level"] == "plain"
        assert result["step"] is None

    def test_preserves_original_text_including_whitespace(self):
        # The classifier matches against a stripped copy but must return the
        # original line untouched -- callers render `text` verbatim.
        result = _classify_upgrade_log_line("  [ OK ]  padded  ")
        assert result["text"] == "  [ OK ]  padded  "


def _fake_systemctl_show(active_state="inactive", sub_state="dead"):
    result = MagicMock()
    result.stdout = f"ActiveState={active_state}\nSubState={sub_state}\n"
    return result


class TestUpgradeProgressEndpoint:
    """Calls the decorated view function inside a bare request context.

    A real dispatched request (``app_client.get(...)``) would also run
    Flask's before_request chain, which touches a DB-health gate that this
    suite's in-memory SQLite can't satisfy (JSONB columns elsewhere in the
    schema -- see test_gps_status_api.py's docstring and
    tests/known_failures.txt's test_support_smoke.py entry for the same,
    already-tracked limitation). ``test_request_context`` gives ``session``/
    ``jsonify`` a context to run in without going through that chain, which
    is all this view and its ``require_permission`` decorator need.
    """

    URL = "/admin/operations/upgrade/progress"

    def _get(self, app, json_accept=True):
        headers = {"Accept": "application/json"} if json_accept else {}
        with app.test_request_context(self.URL, headers=headers):
            return get_upgrade_progress()

    def test_unit_never_run_is_idle(self, app, authenticated_user):
        with patch("subprocess.run", return_value=_fake_systemctl_show()), \
             patch(
                 "webapp.admin.maintenance.routes_operations.get_systemd_logs",
                 return_value={"success": True, "logs": [], "count": 0},
             ):
            response = self._get(app)

        assert response.status_code == 200
        data = response.get_json()
        assert data["unit"]["active_state"] == "inactive"
        assert data["result"] == "idle"
        assert data["lines"] == []

    def test_running_unit_with_no_result_marker_yet_reports_running(self, app, authenticated_user):
        logs = {
            "success": True,
            "count": 2,
            "logs": [
                {"message": "--- Step 3/12: Stopping Services ---"},
                {"message": "[INFO]  Stopping EAS Station services..."},
            ],
        }
        with patch(
            "subprocess.run",
            return_value=_fake_systemctl_show(active_state="active", sub_state="running"),
        ), patch(
            "webapp.admin.maintenance.routes_operations.get_systemd_logs",
            return_value=logs,
        ):
            response = self._get(app)

        data = response.get_json()
        assert data["unit"]["active_state"] == "active"
        assert data["result"] == "running"
        assert data["lines"][0]["step"] == {"num": 3, "total": 12, "label": "Stopping Services"}

    def test_success_marker_wins_even_after_the_collected_unit_looks_gone(self, app, authenticated_user):
        # By the time the unit shows as inactive (post --collect, which in
        # practice happens within a couple of seconds of exit either way),
        # the journal already has the final marker update.sh printed just
        # before exiting successfully -- that marker is authoritative
        # regardless of what systemctl show currently reports.
        logs = {
            "success": True,
            "count": 4,
            "logs": [
                {"message": "--- Step 12/12: Restarting Services ---"},
                {"message": "=== UPDATE RESULT: SUCCESS ==="},
                {"message": "eas-station-update.service: Deactivated successfully."},
                {"message": "Finished eas-station-update.service - update.sh."},
            ],
        }
        with patch(
            "subprocess.run",
            return_value=_fake_systemctl_show(),
        ), patch(
            "webapp.admin.maintenance.routes_operations.get_systemd_logs",
            return_value=logs,
        ):
            response = self._get(app)

        assert response.get_json()["result"] == "success"

    def test_failure_marker_reports_failed(self, app, authenticated_user):
        logs = {
            "success": True,
            "count": 1,
            "logs": [{"message": "=== UPDATE RESULT: ISSUES DETECTED ==="}],
        }
        with patch(
            "subprocess.run",
            return_value=_fake_systemctl_show(),
        ), patch(
            "webapp.admin.maintenance.routes_operations.get_systemd_logs",
            return_value=logs,
        ):
            response = self._get(app)

        assert response.get_json()["result"] == "failed"

    def test_crash_before_any_result_marker_falls_back_to_systemd_failure_line(self, app, authenticated_user):
        # `set -e` killed update.sh on an early command failure, before it
        # ever reached its own success/failure summary block -- there is no
        # "=== UPDATE RESULT ===" line at all, only update.sh's own error
        # output and systemd's record of the unit failing.
        logs = {
            "success": True,
            "count": 3,
            "logs": [
                {"message": "[ERROR] Failed to change ownership"},
                {"message": "eas-station-update.service: Main process exited, code=exited, status=1/FAILURE"},
                {"message": "eas-station-update.service: Failed with result 'exit-code'."},
            ],
        }
        with patch(
            "subprocess.run",
            return_value=_fake_systemctl_show(active_state="failed", sub_state="failed"),
        ), patch(
            "webapp.admin.maintenance.routes_operations.get_systemd_logs",
            return_value=logs,
        ):
            response = self._get(app)

        assert response.get_json()["result"] == "failed"

    def test_requires_authentication(self, app):
        # Called directly rather than through Flask's dispatcher, a (body,
        # status) tuple return doesn't get normalized into a Response.
        _body, status = self._get(app)
        assert status == 401


def _proc(stdout="", returncode=0, stderr=""):
    result = MagicMock()
    result.stdout = stdout
    result.stderr = stderr
    result.returncode = returncode
    return result


class TestCheckForUpgrade:
    """git fetch only updates this checkout's own remote-tracking refs, so
    the endpoint is safe to call from a page-load handler -- unlike the
    upgrade itself, it never touches the working tree. Every subprocess.run
    call in check_for_upgrade() is mocked in the exact sequence the view
    makes them: fetch, `git show origin/<ref>:VERSION`, `rev-parse HEAD`,
    `rev-parse origin/<ref>`, and (only when the two heads differ)
    `rev-list --count`.
    """

    URL = "/admin/operations/upgrade/check"

    def _get(self, app, query_string=""):
        url = self.URL + (f"?{query_string}" if query_string else "")
        with app.test_request_context(url, headers={"Accept": "application/json"}):
            return check_for_upgrade()

    def test_up_to_date(self, app, authenticated_user):
        same_head = "abc1234" * 5 + "abcd"  # 44 chars, arbitrary but consistent
        with patch(
            "webapp.admin.maintenance.routes_operations.get_git_metadata",
            return_value={"branch": "main"},
        ), patch(
            "subprocess.run",
            side_effect=[
                _proc(),  # fetch
                _proc(stdout="2.203.6\n"),  # show origin/main:VERSION
                _proc(stdout=same_head + "\n"),  # rev-parse HEAD
                _proc(stdout=same_head + "\n"),  # rev-parse origin/main
            ],
        ):
            response = self._get(app)

        data = response.get_json()
        assert data["update_available"] is False
        assert data["commits_behind"] == 0
        assert data["remote_version"] == "2.203.6"
        assert data["ref"] == "main"

    def test_update_available_reports_commits_behind(self, app, authenticated_user):
        with patch(
            "webapp.admin.maintenance.routes_operations.get_git_metadata",
            return_value={"branch": "main"},
        ), patch(
            "subprocess.run",
            side_effect=[
                _proc(),  # fetch
                _proc(stdout="2.204.0\n"),  # show origin/main:VERSION
                _proc(stdout="local000\n"),  # rev-parse HEAD
                _proc(stdout="remote999\n"),  # rev-parse origin/main
                _proc(stdout="14\n"),  # rev-list --count
            ],
        ):
            response = self._get(app)

        data = response.get_json()
        assert data["update_available"] is True
        assert data["commits_behind"] == 14
        assert data["remote_version"] == "2.204.0"

    def test_explicit_ref_query_param_is_used(self, app, authenticated_user):
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = [
                _proc(),
                _proc(stdout="1.0.0\n"),
                _proc(stdout="same\n"),
                _proc(stdout="same\n"),
            ]
            self._get(app, query_string="ref=release-branch")

        fetch_args = mock_run.call_args_list[0][0][0]
        assert "release-branch" in fetch_args

    def test_fetch_failure_returns_502(self, app, authenticated_user):
        with patch(
            "subprocess.run",
            return_value=_proc(returncode=1, stderr="unable to access remote"),
        ):
            response, status = self._get(app)

        assert status == 502
        assert "unable to access remote" in response.get_json()["error"]

    def test_unknown_ref_returns_404(self, app, authenticated_user):
        with patch(
            "webapp.admin.maintenance.routes_operations.get_git_metadata",
            return_value={"branch": "main"},
        ), patch(
            "subprocess.run",
            side_effect=[
                _proc(),  # fetch succeeds (git fetch accepts a bogus short name)
                _proc(returncode=1),  # show origin/<ref>:VERSION fails
                _proc(stdout="local\n"),  # rev-parse HEAD
                _proc(returncode=1),  # rev-parse origin/<ref> fails -- no such ref
            ],
        ):
            response, status = self._get(app, query_string="ref=no-such-branch")

        assert status == 404

    def test_requires_authentication(self, app):
        _body, status = self._get(app)
        assert status == 401


class TestListUpgradeTags:
    """The version-picker dropdown on the upgrade page is populated from
    this endpoint. `git ls-remote --tags` is a pure remote query -- it
    never touches a local ref, unlike `git fetch` -- so, like
    check_for_upgrade(), this is safe to call from a page-load handler.
    """

    URL = "/admin/operations/upgrade/tags"

    def _get(self, app):
        with app.test_request_context(self.URL, headers={"Accept": "application/json"}):
            return list_upgrade_tags()

    def test_lists_tags_newest_first_and_dedupes_annotated_refs(self, app, authenticated_user):
        ls_remote_output = (
            "abc123\trefs/tags/v2.205.0\n"
            "abc124\trefs/tags/v2.205.0^{}\n"
            "abc125\trefs/tags/v2.204.0\n"
            "abc126\trefs/tags/v2.203.0\n"
        )
        with patch(
            "webapp.admin.maintenance.routes_operations.get_git_metadata",
            return_value={"branch": "main"},
        ), patch(
            "subprocess.run",
            return_value=_proc(stdout=ls_remote_output),
        ):
            response = self._get(app)

        data = response.get_json()
        assert data["branch"] == "main"
        assert data["tags"] == ["v2.205.0", "v2.204.0", "v2.203.0"]

    def test_caps_at_fifteen_tags(self, app, authenticated_user):
        ls_remote_output = "".join(
            f"sha{i}\trefs/tags/v0.0.{i}\n" for i in range(20)
        )
        with patch(
            "webapp.admin.maintenance.routes_operations.get_git_metadata",
            return_value={"branch": "main"},
        ), patch(
            "subprocess.run",
            return_value=_proc(stdout=ls_remote_output),
        ):
            response = self._get(app)

        assert len(response.get_json()["tags"]) == 15

    def test_ls_remote_failure_returns_502(self, app, authenticated_user):
        with patch(
            "subprocess.run",
            return_value=_proc(returncode=1, stderr="unable to access remote"),
        ):
            response, status = self._get(app)

        assert status == 502
        assert "unable to access remote" in response.get_json()["error"]

    def test_requires_authentication(self, app):
        _body, status = self._get(app)
        assert status == 401
