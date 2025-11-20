"""
EAS Station - Emergency Alert System
Copyright (c) 2025 Timothy Kramer (KR8MER)

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

"""
Audio Pipeline Test Runner Routes

Web UI for running and viewing audio pipeline test results.
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, List

from flask import Flask, jsonify, render_template, request

from app_utils import utc_now


def register(app: Flask, logger) -> None:
    """Attach audio pipeline test routes to the Flask app."""

    route_logger = logger.getChild("routes_audio_tests")

    def _run_pytest(test_module: str = None, verbose: bool = True) -> Dict[str, Any]:
        """
        Run pytest and return structured results.
        
        Args:
            test_module: Specific test module to run (e.g., 'test_audio_playout_queue')
            verbose: Whether to use verbose output
            
        Returns:
            Dictionary with test results
        """
        try:
            # Build pytest command
            cmd = [sys.executable, "-m", "pytest"]
            
            if test_module:
                test_path = f"tests/{test_module}.py"
                cmd.append(test_path)
            else:
                # Run all audio pipeline tests
                cmd.extend([
                    "tests/test_audio_playout_queue.py",
                    "tests/test_audio_output_service.py",
                    "tests/test_audio_pipeline_integration.py",
                ])
            
            if verbose:
                cmd.append("-v")
            
            # Add JSON output for parsing
            cmd.extend(["--tb=short", "--color=no"])
            
            route_logger.info(f"Running pytest: {' '.join(cmd)}")
            
            # Run pytest
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                cwd=Path(__file__).parent.parent,
                timeout=120,  # 2 minute timeout
            )
            
            # Log subprocess completion
            route_logger.info(f"Pytest completed with return code: {result.returncode}")
            
            # Parse output
            output_lines = result.stdout.split('\n')
            
            # Extract test results
            passed = 0
            failed = 0
            skipped = 0
            errors = 0
            test_details = []
            
            for line in output_lines:
                if " PASSED" in line:
                    passed += 1
                    test_name = line.split("::")[1].split(" ")[0] if "::" in line else "unknown"
                    test_details.append({
                        "name": test_name,
                        "status": "passed",
                        "module": line.split("::")[0].split("/")[-1] if "::" in line else "unknown"
                    })
                elif " FAILED" in line:
                    failed += 1
                    test_name = line.split("::")[1].split(" ")[0] if "::" in line else "unknown"
                    test_details.append({
                        "name": test_name,
                        "status": "failed",
                        "module": line.split("::")[0].split("/")[-1] if "::" in line else "unknown"
                    })
                elif " SKIPPED" in line:
                    skipped += 1
                elif " ERROR" in line:
                    errors += 1
            
            # Extract summary line
            summary = ""
            for line in output_lines:
                if " passed" in line or " failed" in line:
                    summary = line.strip()
                    break
            
            # Log test results
            route_logger.info(f"Test results: {passed} passed, {failed} failed, {skipped} skipped, {errors} errors")
            if summary:
                route_logger.info(f"Test summary: {summary}")
            
            # Log stderr if present
            if result.stderr:
                route_logger.warning(f"Pytest stderr output: {result.stderr[:500]}")
            
            # Log a preview of stdout for debugging
            if result.stdout:
                stdout_preview = result.stdout[:500] if len(result.stdout) > 500 else result.stdout
                route_logger.debug(f"Pytest stdout preview: {stdout_preview}")
            else:
                route_logger.warning("Pytest produced no stdout output")
            
            return {
                "success": result.returncode == 0,
                "return_code": result.returncode,
                "passed": passed,
                "failed": failed,
                "skipped": skipped,
                "errors": errors,
                "total": passed + failed + skipped,
                "summary": summary,
                "output": result.stdout,
                "stderr": result.stderr,
                "test_details": test_details,
                "timestamp": utc_now().isoformat(),
            }
            
        except subprocess.TimeoutExpired:
            route_logger.error("Test execution timed out after 120 seconds")
            return {
                "success": False,
                "error": "Test execution timed out after 120 seconds",
                "timestamp": utc_now().isoformat(),
            }
        except Exception as exc:
            route_logger.error(f"Error running tests: {exc}", exc_info=True)
            return {
                "success": False,
                "error": str(exc),
                "timestamp": utc_now().isoformat(),
            }

    @app.route("/audio/tests")
    def audio_tests_dashboard():
        """Display audio pipeline test dashboard."""
        return render_template(
            "audio/tests_dashboard.html",
            title="Audio Pipeline Tests",
        )

    @app.route("/api/audio/tests/run", methods=["POST"])
    def run_audio_tests():
        """
        Run audio pipeline tests via API.
        
        POST body (JSON):
        {
            "test_module": "test_audio_playout_queue",  // optional, specific module
            "verbose": true  // optional, default true
        }
        
        Returns:
            JSON with test results
        """
        try:
            data = request.get_json() or {}
            test_module = data.get("test_module")
            verbose = data.get("verbose", True)
            
            route_logger.info(f"Running audio tests: module={test_module}, verbose={verbose}")
            
            results = _run_pytest(test_module, verbose)
            
            # Log the result status
            if results.get("success"):
                route_logger.info(f"Test execution successful: {results.get('passed', 0)} passed, {results.get('failed', 0)} failed")
            else:
                route_logger.error(f"Test execution failed: {results.get('error', 'Unknown error')}")
            
            return jsonify(results)
            
        except Exception as exc:
            route_logger.error(f"Error in run_audio_tests: {exc}")
            return jsonify({
                "success": False,
                "error": str(exc),
                "timestamp": utc_now().isoformat(),
            }), 500

    @app.route("/api/audio/tests/modules")
    def list_test_modules():
        """List available audio pipeline test modules."""
        try:
            modules = [
                {
                    "id": "test_audio_playout_queue",
                    "name": "Playout Queue Tests",
                    "description": "FCC precedence, priority queue, and preemption logic",
                    "test_count": 39,
                },
                {
                    "id": "test_audio_output_service",
                    "name": "Output Service Tests",
                    "description": "Service initialization, GPIO integration, and error handling",
                    "test_count": 29,
                },
                {
                    "id": "test_audio_pipeline_integration",
                    "name": "Pipeline Integration Tests",
                    "description": "End-to-end alert flow, FCC compliance, and resilience",
                    "test_count": 13,
                },
            ]
            
            return jsonify({
                "success": True,
                "modules": modules,
                "total_modules": len(modules),
                "total_tests": sum(m["test_count"] for m in modules),
            })
            
        except Exception as exc:
            route_logger.error(f"Error listing test modules: {exc}")
            return jsonify({
                "success": False,
                "error": str(exc),
            }), 500

    @app.route("/api/audio/tests/queue/status")
    def audio_queue_status():
        """Get current audio playout queue status for testing."""
        try:
            # Import queue module to get status
            from app_core.audio.playout_queue import AudioPlayoutQueue
            
            # This would ideally get the actual queue instance from the app
            # For now, we'll return a placeholder
            return jsonify({
                "success": True,
                "message": "Queue status endpoint - to be implemented with actual queue instance",
                "timestamp": utc_now().isoformat(),
            })
            
        except Exception as exc:
            route_logger.error(f"Error getting queue status: {exc}")
            return jsonify({
                "success": False,
                "error": str(exc),
            }), 500

    route_logger.info("Audio pipeline test routes registered")
