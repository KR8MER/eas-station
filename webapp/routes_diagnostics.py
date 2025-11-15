"""
System Diagnostics Routes

Provides web-based system validation and diagnostics.
Exposes the validation checks as API endpoints for the UI.
"""

from __future__ import annotations

import logging
import subprocess
from typing import Any, Dict, List, Tuple

from flask import Flask, jsonify, render_template

logger = logging.getLogger(__name__)


def run_command(cmd: List[str]) -> Tuple[int, str, str]:
    """Run shell command and return exit code, stdout, stderr."""
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30
        )
        return result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return -1, "", "Command timed out"
    except Exception as e:
        return -1, "", str(e)


def check_services_running() -> Dict[str, List[str]]:
    """Check if Docker services are running."""
    passed = []
    warnings = []
    failed = []
    info = []
    
    try:
        code, stdout, stderr = run_command(["docker", "compose", "ps", "--format", "json"])
        if code != 0:
            failed.append("Unable to check Docker Compose services")
            return {"passed": passed, "warnings": warnings, "failed": failed, "info": info}
        
        import json
        services = []
        for line in stdout.strip().split('\n'):
            if line:
                try:
                    services.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
        
        if not services:
            failed.append("No Docker Compose services found")
            return {"passed": passed, "warnings": warnings, "failed": failed, "info": info}
        
        expected_services = ["app", "nginx", "alerts-db"]
        
        for service in services:
            name = service.get("Service", "unknown")
            state = service.get("State", "unknown")
            
            if state == "running":
                passed.append(f"Service '{name}' is running")
            else:
                failed.append(f"Service '{name}' is not running (state: {state})")
        
        # Check for expected services
        running_names = [s.get("Service") for s in services if s.get("State") == "running"]
        for expected in expected_services:
            if expected not in running_names:
                warnings.append(f"Expected service '{expected}' not found")
    
    except Exception as e:
        logger.error(f"Error checking services: {e}")
        failed.append(f"Error checking services: {str(e)}")
    
    return {"passed": passed, "warnings": warnings, "failed": failed, "info": info}


def check_database_connection() -> Dict[str, List[str]]:
    """Check database connectivity."""
    passed = []
    warnings = []
    failed = []
    info = []
    
    try:
        from app_core.extensions import db
        from flask import current_app
        
        # Try to execute a simple query
        with current_app.app_context():
            db.engine.connect()
            passed.append("Database connection successful")
    
    except Exception as e:
        logger.error(f"Database connection failed: {e}")
        failed.append(f"Database connection failed: {str(e)}")
    
    return {"passed": passed, "warnings": warnings, "failed": failed, "info": info}


def check_environment_config() -> Dict[str, List[str]]:
    """Check environment configuration."""
    passed = []
    warnings = []
    failed = []
    info = []
    
    try:
        import os
        from pathlib import Path
        
        env_file = Path(".env")
        if not env_file.exists():
            failed.append(".env file not found")
            return {"passed": passed, "warnings": warnings, "failed": failed, "info": info}
        
        passed.append(".env file exists")
        
        # Check critical environment variables
        critical_vars = [
            "SECRET_KEY",
            "POSTGRES_PASSWORD",
            "DEFAULT_STATE_CODE",
            "DEFAULT_COUNTY_NAME"
        ]
        
        for var in critical_vars:
            value = os.getenv(var)
            if value:
                # Check for default/weak values
                if var == "SECRET_KEY" and any(x in value.lower() for x in ["change", "secret", "example"]):
                    warnings.append(f"{var} appears to use a default value - should be changed for production")
                elif var == "POSTGRES_PASSWORD" and any(x in value.lower() for x in ["changeme", "password", "postgres"]):
                    warnings.append(f"{var} appears to use a weak password - should be changed for production")
                else:
                    passed.append(f"{var} is configured")
            else:
                warnings.append(f"{var} not found in environment")
    
    except Exception as e:
        logger.error(f"Error checking environment: {e}")
        failed.append(f"Error checking environment: {str(e)}")
    
    return {"passed": passed, "warnings": warnings, "failed": failed, "info": info}


def check_health_endpoint() -> Dict[str, List[str]]:
    """Check system health endpoint."""
    passed = []
    warnings = []
    failed = []
    info = []
    
    try:
        import requests
        
        # Check health endpoint
        response = requests.get("http://localhost/health/dependencies", timeout=10)
        
        if response.status_code == 200:
            data = response.json()
            
            if data.get("status") == "healthy":
                passed.append("System health check passed")
                
                # Check individual dependencies
                deps = data.get("dependencies", {})
                for dep_name, dep_status in deps.items():
                    if dep_status.get("healthy"):
                        info.append(f"Dependency '{dep_name}' is healthy")
                    else:
                        warnings.append(f"Dependency '{dep_name}' is unhealthy")
            else:
                warnings.append("System health check returned non-healthy status")
        else:
            warnings.append(f"Health endpoint returned HTTP {response.status_code}")
    
    except requests.exceptions.RequestException as e:
        warnings.append(f"Could not reach health endpoint: {str(e)}")
    except Exception as e:
        logger.error(f"Error checking health: {e}")
        failed.append(f"Error checking health: {str(e)}")
    
    return {"passed": passed, "warnings": warnings, "failed": failed, "info": info}


def check_audio_devices() -> Dict[str, List[str]]:
    """Check for audio devices."""
    passed = []
    warnings = []
    failed = []
    info = []
    
    try:
        import os
        
        # Check if audio is enabled
        if os.getenv("AUDIO_OUTPUT_ENABLED", "false").lower() == "false":
            info.append("Audio output is disabled in configuration")
            return {"passed": passed, "warnings": warnings, "failed": failed, "info": info}
        
        # Try to list audio devices
        code, stdout, stderr = run_command([
            "docker", "compose", "exec", "-T", "app",
            "aplay", "-l"
        ])
        
        if code == 0:
            if "card" in stdout.lower():
                passed.append("Audio devices detected")
                # Count devices
                card_count = stdout.lower().count("card ")
                info.append(f"Found {card_count} audio card(s)")
            else:
                warnings.append("No audio devices found")
        else:
            info.append("Could not check audio devices (may not be configured)")
    
    except Exception as e:
        logger.error(f"Error checking audio: {e}")
        info.append(f"Audio device check skipped: {str(e)}")
    
    return {"passed": passed, "warnings": warnings, "failed": failed, "info": info}


def check_recent_logs() -> Dict[str, List[str]]:
    """Check for recent errors in logs."""
    passed = []
    warnings = []
    failed = []
    info = []
    
    try:
        code, stdout, stderr = run_command([
            "docker", "compose", "logs", "--tail=100"
        ])
        
        if code == 0:
            # Look for error patterns
            error_patterns = {
                "ERROR": 0,
                "CRITICAL": 0,
                "Exception": 0,
                "Traceback": 0
            }
            
            for pattern in error_patterns:
                count = stdout.count(pattern)
                error_patterns[pattern] = count
            
            total_errors = sum(error_patterns.values())
            
            if total_errors == 0:
                passed.append("No obvious errors in recent logs")
            elif total_errors < 5:
                warnings.append(f"Found {total_errors} error pattern(s) in recent logs")
                info.append("Review logs with: docker compose logs --tail=100")
            else:
                warnings.append(f"Found {total_errors} error pattern(s) in recent logs - review recommended")
                info.append("Review logs with: docker compose logs --tail=100")
        else:
            warnings.append("Could not retrieve Docker Compose logs")
    
    except Exception as e:
        logger.error(f"Error checking logs: {e}")
        info.append(f"Log check skipped: {str(e)}")
    
    return {"passed": passed, "warnings": warnings, "failed": failed, "info": info}


def register(app: Flask, route_logger: logging.Logger) -> None:
    """Register diagnostics routes."""
    
    @app.route("/diagnostics")
    def diagnostics_page() -> Any:
        """Render the diagnostics page."""
        return render_template("diagnostics.html")
    
    @app.route("/api/diagnostics/validate", methods=["POST"])
    def validate_installation() -> Tuple[Any, int]:
        """Run system validation checks."""
        try:
            all_results = {
                "passed": [],
                "warnings": [],
                "failed": [],
                "info": []
            }
            
            # Run all checks
            checks = [
                ("Services", check_services_running),
                ("Database", check_database_connection),
                ("Environment", check_environment_config),
                ("Health", check_health_endpoint),
                ("Audio", check_audio_devices),
                ("Logs", check_recent_logs),
            ]
            
            for check_name, check_func in checks:
                try:
                    result = check_func()
                    all_results["passed"].extend(result["passed"])
                    all_results["warnings"].extend(result["warnings"])
                    all_results["failed"].extend(result["failed"])
                    all_results["info"].extend(result["info"])
                except Exception as e:
                    route_logger.error(f"Error in {check_name} check: {e}")
                    all_results["failed"].append(f"{check_name} check failed: {str(e)}")
            
            return jsonify({
                "success": True,
                **all_results
            }), 200
        
        except Exception as e:
            route_logger.error(f"Error running diagnostics: {e}")
            return jsonify({
                "success": False,
                "error": str(e)
            }), 500


__all__ = ["register"]
