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

"""
Audio Pipeline Test Runner Routes

Web UI for running and viewing audio pipeline test results.

Tests are discovered dynamically from the ``tests/`` directory and executed
via ``pytest``. Counts and per-test results are parsed from a JUnit XML report
produced by pytest itself, so the dashboard always reflects what actually ran
rather than hardcoded numbers.
"""

import os
import re
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

from flask import Flask, jsonify, render_template, request

from app_utils import utc_now
from app_core.auth.roles import require_permission


# Test files belonging to the audio pipeline. Anything matching the patterns
# below in ``tests/`` is offered on the dashboard. Patterns are evaluated
# relative to the project root.
AUDIO_TEST_GLOBS: Tuple[str, ...] = (
    "test_audio_*.py",
    "test_broadcast_*.py",
    "test_icecast_*.py",
    "test_buffer_mount_identifier.py",
    "test_forwarded_alert_audio_flow.py",
)


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _tests_dir() -> Path:
    return _project_root() / "tests"


def _discover_audio_tests() -> List[Path]:
    """Return absolute paths of audio-related test files, sorted."""
    tests_dir = _tests_dir()
    if not tests_dir.is_dir():
        return []
    seen: Dict[str, Path] = {}
    for pattern in AUDIO_TEST_GLOBS:
        for path in tests_dir.glob(pattern):
            if path.is_file():
                seen[path.name] = path
    return [seen[name] for name in sorted(seen)]


def _humanize_module(name: str) -> str:
    """Turn ``test_audio_playout_queue`` into ``Audio Playout Queue``."""
    stem = name[len("test_"):] if name.startswith("test_") else name
    return stem.replace("_", " ").title()


def _module_description(name: str) -> str:
    """Best-effort: read the module docstring's first line for a summary."""
    path = _tests_dir() / f"{name}.py"
    try:
        source = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    # Match a leading triple-quoted docstring after optional license header.
    match = re.search(
        r'^(?:\s*#.*\n|\s*"""[\s\S]*?"""\s*\n|\s*\n)*\s*(?:r|u|b)?"""([\s\S]*?)"""',
        source,
        flags=re.MULTILINE,
    )
    if not match:
        return ""
    first_line = match.group(1).strip().splitlines()
    return first_line[0].strip() if first_line else ""


def _pytest_command_base() -> List[str]:
    return [sys.executable, "-m", "pytest", "--color=no"]


def _collect_counts(test_files: List[Path], timeout: int = 60) -> Dict[str, int]:
    """Return ``{module_stem: count}`` using ``pytest --collect-only -q``."""
    counts: Dict[str, int] = {f.stem: 0 for f in test_files}
    if not test_files:
        return counts

    cmd = _pytest_command_base() + ["--collect-only", "-q"]
    cmd.extend(str(p) for p in test_files)

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=_project_root(),
            timeout=timeout,
        )
    except (subprocess.TimeoutExpired, OSError):
        return counts

    # ``-q`` collect output prints one node id per line, e.g.:
    #   tests/test_audio_playout_queue.py::TestThing::test_method[param]
    for line in result.stdout.splitlines():
        line = line.strip()
        if not line or "::" not in line:
            continue
        file_part = line.split("::", 1)[0]
        stem = Path(file_part).stem
        if stem in counts:
            counts[stem] += 1

    return counts


def _parse_junit_xml(xml_path: Path) -> Tuple[Dict[str, int], List[Dict[str, Any]]]:
    """Parse a pytest JUnit XML report and return totals + per-test details."""
    totals = {"passed": 0, "failed": 0, "skipped": 0, "errors": 0, "total": 0}
    details: List[Dict[str, Any]] = []

    if not xml_path.exists() or xml_path.stat().st_size == 0:
        return totals, details

    try:
        tree = ET.parse(xml_path)
    except ET.ParseError:
        return totals, details

    root = tree.getroot()
    # Pytest emits either ``<testsuites>`` wrapping ``<testsuite>``, or a
    # single top-level ``<testsuite>``.
    suites = root.findall("testsuite") if root.tag == "testsuites" else [root]

    for suite in suites:
        for case in suite.findall("testcase"):
            classname = case.get("classname", "")
            name = case.get("name", "")
            try:
                duration = float(case.get("time", "0") or 0.0)
            except ValueError:
                duration = 0.0

            failure = case.find("failure")
            error = case.find("error")
            skipped = case.find("skipped")

            if failure is not None:
                status = "failed"
                message = failure.get("message", "") or (failure.text or "").strip()
                totals["failed"] += 1
            elif error is not None:
                status = "error"
                message = error.get("message", "") or (error.text or "").strip()
                totals["errors"] += 1
            elif skipped is not None:
                status = "skipped"
                message = skipped.get("message", "") or (skipped.text or "").strip()
                totals["skipped"] += 1
            else:
                status = "passed"
                message = ""
                totals["passed"] += 1

            # ``classname`` is dotted: ``tests.test_audio_foo`` or
            # ``tests.test_audio_foo.TestClass``. The first dotted segment after
            # ``tests.`` is the module.
            module = ""
            if classname.startswith("tests."):
                module = classname.split(".", 2)[1] if "." in classname[len("tests."):] else classname[len("tests."):]
            else:
                module = classname.split(".")[0]

            # Trim very long error messages so the JSON payload stays small.
            if message and len(message) > 1000:
                message = message[:1000] + "..."

            details.append({
                "name": name,
                "module": module,
                "status": status,
                "duration": round(duration, 3),
                "message": message,
            })

    totals["total"] = totals["passed"] + totals["failed"] + totals["skipped"] + totals["errors"]
    return totals, details


def _run_pytest_and_parse(
    test_files: List[Path],
    verbose: bool,
    logger,
    timeout: int = 180,
) -> Dict[str, Any]:
    """Run pytest on ``test_files`` and return a structured result dict."""
    if not test_files:
        return {
            "success": False,
            "error": "No test files selected.",
            "passed": 0,
            "failed": 0,
            "skipped": 0,
            "errors": 0,
            "total": 0,
            "summary": "No tests to run",
            "output": "",
            "stderr": "",
            "test_details": [],
            "timestamp": utc_now().isoformat(),
        }

    with tempfile.NamedTemporaryFile(prefix="eas-pytest-", suffix=".xml", delete=False) as tf:
        xml_path = Path(tf.name)

    try:
        cmd = _pytest_command_base() + [
            "--tb=short",
            f"--junit-xml={xml_path}",
        ]
        if verbose:
            cmd.append("-v")
        cmd.extend(str(p) for p in test_files)

        logger.info("Running pytest: %s", " ".join(cmd))

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                cwd=_project_root(),
                timeout=timeout,
            )
            stdout = result.stdout
            stderr = result.stderr
            return_code = result.returncode
            timed_out = False
        except subprocess.TimeoutExpired as exc:
            stdout = exc.stdout or ""
            stderr = (exc.stderr or "") + f"\nTest run exceeded {timeout}s timeout."
            return_code = -1
            timed_out = True

        totals, details = _parse_junit_xml(xml_path)

        if timed_out:
            summary = f"Timed out after {timeout}s"
            success = False
        elif totals["total"] == 0:
            # No JUnit data — likely a collection error.
            summary = "No tests collected (check stderr for collection errors)"
            success = False
        else:
            parts = [f"{totals['passed']} passed"]
            if totals["failed"]:
                parts.append(f"{totals['failed']} failed")
            if totals["errors"]:
                parts.append(f"{totals['errors']} error(s)")
            if totals["skipped"]:
                parts.append(f"{totals['skipped']} skipped")
            summary = ", ".join(parts)
            success = totals["failed"] == 0 and totals["errors"] == 0

        logger.info(
            "Test results: %d passed, %d failed, %d skipped, %d errors (rc=%s)",
            totals["passed"], totals["failed"], totals["skipped"], totals["errors"],
            return_code,
        )

        if not success and stderr:
            logger.warning("Pytest stderr: %s", stderr[:500])

        return {
            "success": success,
            "return_code": return_code,
            "passed": totals["passed"],
            "failed": totals["failed"],
            "skipped": totals["skipped"],
            "errors": totals["errors"],
            "total": totals["total"],
            "summary": summary,
            "output": stdout,
            "stderr": stderr,
            "test_details": details,
            "timestamp": utc_now().isoformat(),
        }
    finally:
        try:
            xml_path.unlink()
        except OSError:
            pass


def _resolve_requested_files(test_module: Optional[str]) -> Tuple[List[Path], Optional[str]]:
    """Given an optional module id, return the test files to run plus an error."""
    discovered = _discover_audio_tests()
    if not test_module:
        return discovered, None

    # Sanitise: only allow simple module names (no path separators).
    if "/" in test_module or ".." in test_module or test_module.endswith(".py"):
        return [], "Invalid test module name."

    target_name = f"{test_module}.py"
    for path in discovered:
        if path.name == target_name:
            return [path], None
    return [], f"Unknown test module: {test_module}"


def register(app: Flask, logger) -> None:
    """Attach audio pipeline test routes to the Flask app."""

    route_logger = logger.getChild("routes_audio_tests")

    @app.route("/audio/tests")
    def audio_tests_dashboard():
        """Display audio pipeline test dashboard."""
        return render_template(
            "audio/tests_dashboard.html",
            title="Audio Pipeline Tests",
        )

    @app.route("/api/audio/tests/modules")
    def list_test_modules():
        """List available audio pipeline test modules with live counts."""
        try:
            files = _discover_audio_tests()
            counts = _collect_counts(files)
            modules = []
            for path in files:
                stem = path.stem
                modules.append({
                    "id": stem,
                    "name": _humanize_module(stem),
                    "description": _module_description(stem) or "Audio pipeline tests",
                    "test_count": counts.get(stem, 0),
                    "path": f"tests/{path.name}",
                })

            return jsonify({
                "success": True,
                "modules": modules,
                "total_modules": len(modules),
                "total_tests": sum(m["test_count"] for m in modules),
                "timestamp": utc_now().isoformat(),
            })

        except Exception as exc:
            route_logger.error("Error listing test modules: %s", exc, exc_info=True)
            return jsonify({"success": False, "error": str(exc)}), 500

    @app.route("/api/audio/tests/run", methods=["POST"])
    @require_permission('system.configure')
    def run_audio_tests():
        """Run audio pipeline tests and return structured JUnit-parsed results."""
        try:
            data = request.get_json(silent=True) or {}
            test_module = data.get("test_module")
            verbose = bool(data.get("verbose", True))

            files, err = _resolve_requested_files(test_module)
            if err:
                return jsonify({
                    "success": False,
                    "error": err,
                    "timestamp": utc_now().isoformat(),
                }), 400

            route_logger.info(
                "Running audio tests: module=%s verbose=%s files=%d",
                test_module, verbose, len(files),
            )

            results = _run_pytest_and_parse(files, verbose, route_logger)
            return jsonify(results)

        except Exception as exc:
            route_logger.error("Error in run_audio_tests: %s", exc, exc_info=True)
            return jsonify({
                "success": False,
                "error": str(exc),
                "timestamp": utc_now().isoformat(),
            }), 500

    route_logger.info("Audio pipeline test routes registered")


__all__ = ["register"]
