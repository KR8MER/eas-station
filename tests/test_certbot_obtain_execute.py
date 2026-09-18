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

from __future__ import annotations

"""Characterization tests for ``obtain_certificate_execute``, its
pre-flight validation, and the three obtain methods it dispatches to.

Written before Phase 4a-ii cont. extracts collaborators from the handler's
single 387-line ``try`` block (see
``docs/development/LARGE_FILE_REFACTOR_PLAN.md``) — this module had *no*
test coverage at all before this file, run and passing against the
pre-refactor code first.

``subprocess.run`` and ``time.sleep`` are the true I/O boundary and are
patched globally (both modules are shared singletons, like ``psutil``
elsewhere in this codebase — patching the global attribute affects every
importer regardless of which module calls it). The higher-level
collaborators (``_check_nginx_status``, ``_install_certificate_internal``,
etc.) are plain functions imported *by value* into whichever module calls
them, so those patches target the actual call site: ``get_certbot_settings``,
``clear_stale_locks``, ``_ensure_certbot_directories``,
``_is_existing_cert_staging`` and ``_delete_staging_certs`` are called from
``routes_obtain_execute.py`` itself; the rest are called from
``obtain_methods.py``.

The permission decorator is bypassed via ``__wrapped__`` (it wraps with
``functools.wraps``, per the Phase 3h pre-split checklist item) rather than
standing up a full authenticated Flask test client — this file is about the
handler's own logic, not the auth layer.
"""

import subprocess as real_subprocess
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from flask import Flask

from webapp.admin.certbot import obtain_methods, routes_obtain_execute as mod

_HANDLER = mod.obtain_certificate_execute.__wrapped__

_APP = Flask("certbot-obtain-execute-test")


def _settings(enabled=True, domain_name="example.com", email="ops@example.com", staging=False):
    return SimpleNamespace(enabled=enabled, domain_name=domain_name, email=email, staging=staging)


def _proc(returncode=0, stdout="", stderr=""):
    result = MagicMock()
    result.returncode = returncode
    result.stdout = stdout
    result.stderr = stderr
    return result


def _call(payload, settings=None, run_side_effect=None, **extra_patches):
    """Invoke the handler inside a request context, with every collaborator
    mocked to an inert default unless overridden by ``extra_patches``."""

    route_module_defaults = dict(
        get_certbot_settings=MagicMock(return_value=settings or _settings()),
        clear_stale_locks=MagicMock(),
        _ensure_certbot_directories=MagicMock(),
        _is_existing_cert_staging=MagicMock(return_value=False),
        _delete_staging_certs=MagicMock(return_value={"deleted": [], "error": None}),
    )
    obtain_methods_defaults = dict(
        _check_nginx_status=MagicMock(return_value=False),
        _ensure_nginx_running=MagicMock(),
        _install_certificate_internal=MagicMock(
            return_value={"success": True, "details": {"reloaded": True}}
        ),
        _explain_certbot_failure=MagicMock(side_effect=lambda stderr, stdout: stderr),
        _ensure_webroot_directory=MagicMock(return_value=True),
    )

    for name, value in extra_patches.items():
        if name in obtain_methods_defaults:
            obtain_methods_defaults[name] = value
        else:
            route_module_defaults[name] = value

    patchers = [patch.object(mod, name, value) for name, value in route_module_defaults.items()]
    patchers += [patch.object(obtain_methods, name, value) for name, value in obtain_methods_defaults.items()]
    patchers.append(patch("time.sleep", MagicMock()))
    if run_side_effect is not None:
        patchers.append(patch("subprocess.run", MagicMock(side_effect=run_side_effect)))
    else:
        patchers.append(patch("subprocess.run", MagicMock(return_value=_proc(0))))

    for p in patchers:
        p.start()
    try:
        with _APP.test_request_context(
            "/admin/api/certbot/obtain-certificate-execute", method="POST", json=payload
        ):
            response = _HANDLER()
    finally:
        for p in patchers:
            p.stop()

    if isinstance(response, tuple):
        body, status = response
    else:
        body, status = response, 200
    return body.get_json(), status


# ---------------------------------------------------------------------------
# Pre-flight validation
# ---------------------------------------------------------------------------


def test_certbot_not_enabled():
    body, status = _call({}, settings=_settings(enabled=False))
    assert status == 400
    assert body["success"] is False
    assert "not enabled" in body["error"]


def test_domain_not_configured():
    body, status = _call({}, settings=_settings(domain_name=""))
    assert status == 400
    assert "Domain name" in body["error"]


def test_email_not_configured():
    body, status = _call({}, settings=_settings(email=""))
    assert status == 400
    assert "Email" in body["error"]


def test_invalid_domain_in_database():
    body, status = _call({}, settings=_settings(domain_name="not a domain!"))
    assert status == 500
    assert "Invalid domain name" in body["error"]


def test_invalid_email_in_database():
    body, status = _call({}, settings=_settings(email="not-an-email"))
    assert status == 500
    assert "Invalid email" in body["error"]


def test_invalid_method_rejected():
    body, status = _call({"method": "carrier-pigeon"})
    assert status == 400
    assert "Invalid method" in body["error"]


def test_defaults_to_standalone_method():
    body, status = _call(
        {}, run_side_effect=[_proc(0), _proc(0), _proc(0), _proc(0)]
    )
    assert status == 200
    assert body["success"] is True


def test_certbot_not_installed():
    run_mock_calls = []

    def side_effect(command, **kwargs):
        run_mock_calls.append(command)
        return _proc(1)

    body, status = _call({"method": "standalone"}, run_side_effect=side_effect)
    assert status == 500
    assert "not installed" in body["error"]
    assert len(run_mock_calls) == 1  # never got past the `which certbot` check


def test_certbot_installation_check_raises():
    body, status = _call({"method": "standalone"}, run_side_effect=OSError("no fork"))
    assert status == 500
    assert "Failed to check certbot installation" in body["error"]


def test_staging_to_production_switch_deletes_staging_certs():
    is_staging = MagicMock(return_value=True)
    delete = MagicMock(return_value={"deleted": ["example.com"], "error": None})
    body, status = _call(
        {"method": "standalone"},
        settings=_settings(staging=False),
        _is_existing_cert_staging=is_staging,
        _delete_staging_certs=delete,
        run_side_effect=[_proc(0), _proc(0), _proc(0), _proc(0)],
    )
    assert status == 200
    delete.assert_called_once_with("example.com")


# ---------------------------------------------------------------------------
# standalone method
# ---------------------------------------------------------------------------


def test_standalone_happy_path_installs_certificate():
    body, status = _call(
        {"method": "standalone"},
        run_side_effect=[
            _proc(0),  # which certbot
            _proc(0),  # stop nginx
            _proc(0, stdout="cert obtained"),  # certbot
            _proc(0),  # start nginx
        ],
    )
    assert status == 200
    assert body["success"] is True
    assert body["installation"] == {"reloaded": True}


def test_standalone_stop_nginx_failure_never_runs_certbot():
    calls = []

    def side_effect(command, **kwargs):
        calls.append(command)
        if len(calls) == 1:
            return _proc(0)  # which certbot
        return _proc(1, stderr="stop failed")  # stop nginx fails

    body, status = _call({"method": "standalone"}, run_side_effect=side_effect)
    assert status == 500
    assert "Failed to stop nginx" in body["error"]
    assert len(calls) == 2  # never reached the certbot invocation


def test_standalone_nginx_still_active_after_stop_aborts():
    body, status = _call(
        {"method": "standalone"},
        run_side_effect=[_proc(0), _proc(0)],
        _check_nginx_status=MagicMock(return_value=True),
    )
    assert status == 500
    assert "still running" in body["error"]


def test_standalone_certbot_failure_restarts_nginx_and_augments_permission_error():
    body, status = _call(
        {"method": "standalone"},
        run_side_effect=[
            _proc(0), _proc(0), _proc(1, stderr="Permission denied binding port 80"), _proc(0),
        ],
        _explain_certbot_failure=MagicMock(return_value="Permission denied binding port 80"),
    )
    assert status == 500
    assert "root privileges" in body["error"]


def test_standalone_certbot_failure_augments_port_in_use_error():
    # The raw message must itself contain "address already in use" to
    # trigger the augmentation branch, so assert on text that only the
    # *augmented* wrapper adds -- otherwise the assertion passes whether or
    # not the augmentation branch ran, since the raw text already matches.
    body, status = _call(
        {"method": "standalone"},
        run_side_effect=[
            _proc(0), _proc(0), _proc(1, stderr="bind failed: address already in use"), _proc(0),
        ],
        _explain_certbot_failure=MagicMock(return_value="bind failed: address already in use"),
    )
    assert status == 500
    assert "Another process may be using it" in body["error"]


def test_standalone_certificate_obtained_but_install_fails_is_still_reported_success():
    body, status = _call(
        {"method": "standalone"},
        run_side_effect=[_proc(0), _proc(0), _proc(0), _proc(0)],
        _install_certificate_internal=MagicMock(
            return_value={"success": False, "error": "nginx reload failed"}
        ),
    )
    assert status == 200
    assert body["success"] is True
    assert body["installation_error"] == "nginx reload failed"
    assert "installation" not in body


def test_standalone_timeout_restarts_nginx_via_ensure_running():
    ensure_running = MagicMock()
    # A MagicMock's side_effect list only special-cases exception
    # instances/classes (raising them) -- a plain callable placed in the
    # list is returned as-is, not invoked. Put the exception itself in the
    # list, not a function that raises it.
    body, status = _call(
        {"method": "standalone"},
        run_side_effect=[_proc(0), _proc(0), real_subprocess.TimeoutExpired(cmd="certbot", timeout=120)],
        _ensure_nginx_running=ensure_running,
    )
    assert status == 500
    assert "timed out" in body["error"]
    ensure_running.assert_called_once()


def test_standalone_generic_exception_restarts_nginx_via_ensure_running():
    ensure_running = MagicMock()
    body, status = _call(
        {"method": "standalone"},
        run_side_effect=[_proc(0), _proc(0), RuntimeError("boom")],
        _ensure_nginx_running=ensure_running,
    )
    assert status == 500
    assert "Failed to execute certbot" in body["error"]
    ensure_running.assert_called_once()


# ---------------------------------------------------------------------------
# nginx method
# ---------------------------------------------------------------------------


def test_nginx_method_requires_nginx_running():
    calls = []

    def side_effect(command, **kwargs):
        calls.append(command)
        return _proc(0)

    body, status = _call(
        {"method": "nginx"},
        run_side_effect=side_effect,
        _check_nginx_status=MagicMock(return_value=False),
    )
    assert status == 400
    assert "must be running" in body["error"]
    assert len(calls) == 1  # only the `which certbot` check ran


def test_nginx_method_happy_path():
    body, status = _call(
        {"method": "nginx"},
        run_side_effect=[_proc(0), _proc(0, stdout="ok")],
        _check_nginx_status=MagicMock(return_value=True),
    )
    assert status == 200
    assert body["success"] is True


def test_nginx_method_augments_permission_error():
    body, status = _call(
        {"method": "nginx"},
        run_side_effect=[
            _proc(0), _proc(1, stderr="Permission denied: /var/log/nginx/error.log"),
        ],
        _check_nginx_status=MagicMock(return_value=True),
    )
    assert status == 500
    assert "known limitation of the nginx plugin" in body["error"]


def test_nginx_method_timeout_does_not_call_ensure_nginx_running():
    """Pinning current behaviour: unlike the standalone branch, the nginx
    method's timeout handler does not call ``_ensure_nginx_running`` — it
    never stopped nginx in the first place, so there is nothing to restore."""

    ensure_running = MagicMock()
    body, status = _call(
        {"method": "nginx"},
        run_side_effect=[_proc(0), real_subprocess.TimeoutExpired(cmd="certbot", timeout=120)],
        _check_nginx_status=MagicMock(return_value=True),
        _ensure_nginx_running=ensure_running,
    )
    assert status == 500
    assert "timed out" in body["error"]
    ensure_running.assert_not_called()


# ---------------------------------------------------------------------------
# webroot method
# ---------------------------------------------------------------------------


def test_webroot_method_requires_directory_setup():
    calls = []

    def side_effect(command, **kwargs):
        calls.append(command)
        return _proc(0)

    body, status = _call(
        {"method": "webroot"},
        run_side_effect=side_effect,
        _ensure_webroot_directory=MagicMock(return_value=False),
    )
    assert status == 500
    assert "Failed to configure webroot directory" in body["error"]
    assert len(calls) == 1


def test_webroot_method_happy_path_installs_certificate():
    body, status = _call(
        {"method": "webroot"},
        run_side_effect=[_proc(0), _proc(0, stdout="ok")],
    )
    assert status == 200
    assert body["success"] is True
    assert body["installation"] == {"reloaded": True}


def test_webroot_method_augments_missing_directory_error():
    body, status = _call(
        {"method": "webroot"},
        run_side_effect=[_proc(0), _proc(1, stderr="No such file or directory")],
    )
    assert status == 500
    assert "acme-challenge" in body["error"]


def test_webroot_method_augments_permission_error():
    body, status = _call(
        {"method": "webroot"},
        run_side_effect=[_proc(0), _proc(1, stderr="Permission denied writing challenge file")],
    )
    assert status == 500
    assert "accessible by both root" in body["error"]


def test_webroot_method_timeout():
    body, status = _call(
        {"method": "webroot"},
        run_side_effect=[_proc(0), real_subprocess.TimeoutExpired(cmd="certbot", timeout=120)],
    )
    assert status == 500
    assert "timed out" in body["error"]


# ---------------------------------------------------------------------------
# Outer safety net
# ---------------------------------------------------------------------------


def test_outer_exception_handler_catches_setup_failures():
    body, status = _call(
        {"method": "standalone"},
        clear_stale_locks=MagicMock(side_effect=RuntimeError("disk full")),
    )
    assert status == 500
    assert body["success"] is False
    assert "disk full" in body["error"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
