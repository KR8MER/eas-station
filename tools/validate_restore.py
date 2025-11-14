#!/usr/bin/env python3
"""Post-restore validation script for EAS Station.

This script validates system health after restoring from a backup,
checking database connectivity, configuration integrity, hardware
accessibility, and service availability.

Usage:
    python3 tools/validate_restore.py [--host HOST] [--port PORT]
    
    # With Docker Compose
    docker compose exec app python3 /app/tools/validate_restore.py
    
Exit codes:
    0 - All validation checks passed
    1 - One or more validation checks failed
    2 - Configuration or runtime error
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError


class ValidationResult:
    """Result of a validation check."""
    
    def __init__(self, name: str, passed: bool, message: str, details: Optional[Dict] = None):
        self.name = name
        self.passed = passed
        self.message = message
        self.details = details or {}
    
    def __str__(self) -> str:
        status = "✓ PASS" if self.passed else "✗ FAIL"
        return f"{status}: {self.name} - {self.message}"


class RestoreValidator:
    """Validates system health after restore."""
    
    def __init__(self, host: str = "localhost", port: int = 8080):
        self.host = host
        self.port = port
        self.base_url = f"http://{host}:{port}"
        self.results: List[ValidationResult] = []
    
    def _http_get(self, path: str, timeout: int = 10) -> Tuple[bool, Optional[Dict], str]:
        """Make HTTP GET request to the API.
        
        Returns:
            Tuple of (success, json_data, error_message)
        """
        url = f"{self.base_url}{path}"
        try:
            req = Request(url)
            req.add_header('Accept', 'application/json')
            with urlopen(req, timeout=timeout) as response:
                data = json.loads(response.read().decode())
                return True, data, ""
        except HTTPError as e:
            return False, None, f"HTTP {e.code}: {e.reason}"
        except URLError as e:
            return False, None, f"Connection error: {e.reason}"
        except json.JSONDecodeError as e:
            return False, None, f"Invalid JSON response: {e}"
        except Exception as e:
            return False, None, f"Unexpected error: {e}"
    
    def validate_web_service(self) -> ValidationResult:
        """Check if web service is responding."""
        success, _, error = self._http_get("/")
        
        if success:
            return ValidationResult(
                "Web Service",
                True,
                f"Web service is responding at {self.base_url}"
            )
        else:
            return ValidationResult(
                "Web Service",
                False,
                f"Web service not responding: {error}"
            )
    
    def validate_health_endpoint(self) -> ValidationResult:
        """Check system health endpoint."""
        success, data, error = self._http_get("/health")
        
        if not success:
            return ValidationResult(
                "Health Endpoint",
                False,
                f"Health endpoint not responding: {error}"
            )
        
        if not data:
            return ValidationResult(
                "Health Endpoint",
                False,
                "Health endpoint returned no data"
            )
        
        status = data.get("status")
        if status == "healthy":
            return ValidationResult(
                "Health Endpoint",
                True,
                "System reports healthy status",
                details=data
            )
        else:
            return ValidationResult(
                "Health Endpoint",
                False,
                f"System reports unhealthy status: {status}",
                details=data
            )
    
    def validate_database_connection(self) -> ValidationResult:
        """Check database connectivity."""
        success, data, error = self._http_get("/health")
        
        if not success:
            return ValidationResult(
                "Database Connection",
                False,
                f"Cannot check database status: {error}"
            )
        
        db_status = data.get("database", "unknown")
        if db_status == "connected":
            return ValidationResult(
                "Database Connection",
                True,
                "Database is connected and accessible"
            )
        else:
            return ValidationResult(
                "Database Connection",
                False,
                f"Database connection issue: {db_status}"
            )
    
    def validate_database_migrations(self) -> ValidationResult:
        """Check that all database migrations are applied."""
        success, data, error = self._http_get("/api/release-manifest")
        
        if not success:
            return ValidationResult(
                "Database Migrations",
                False,
                f"Cannot check migration status: {error}"
            )
        
        db_info = data.get("database", {})
        pending_count = db_info.get("pending_count", -1)
        pending_migrations = db_info.get("pending_migrations", [])
        
        if pending_count == 0:
            return ValidationResult(
                "Database Migrations",
                True,
                "All database migrations are applied"
            )
        elif pending_count > 0:
            return ValidationResult(
                "Database Migrations",
                False,
                f"{pending_count} pending migration(s): {', '.join(pending_migrations)}"
            )
        else:
            return ValidationResult(
                "Database Migrations",
                False,
                "Unable to determine migration status"
            )
    
    def validate_dependencies(self) -> ValidationResult:
        """Check external dependencies."""
        success, data, error = self._http_get("/health/dependencies")
        
        if not success:
            return ValidationResult(
                "Dependencies",
                False,
                f"Cannot check dependencies: {error}"
            )
        
        if not data or not isinstance(data, dict):
            return ValidationResult(
                "Dependencies",
                False,
                "Invalid dependencies response"
            )
        
        # Check for any failed dependencies
        failed = []
        for service, info in data.items():
            if isinstance(info, dict):
                status = info.get("status", "unknown")
                if status not in ("healthy", "connected", "available"):
                    failed.append(f"{service}: {status}")
        
        if not failed:
            return ValidationResult(
                "Dependencies",
                True,
                f"All {len(data)} dependencies are healthy",
                details=data
            )
        else:
            return ValidationResult(
                "Dependencies",
                False,
                f"{len(failed)} dependency issue(s): {', '.join(failed)}",
                details=data
            )
    
    def validate_configuration(self) -> ValidationResult:
        """Check configuration file integrity."""
        # Check if running in Docker container
        config_paths = [
            Path("/app-config/.env"),  # Docker persistent volume
            Path("/app/.env"),          # Docker app directory
            Path(".env"),               # Current directory
        ]
        
        config_file = None
        for path in config_paths:
            if path.exists():
                config_file = path
                break
        
        if not config_file:
            return ValidationResult(
                "Configuration",
                False,
                "Configuration file .env not found in expected locations"
            )
        
        try:
            content = config_file.read_text()
            
            # Check for critical configuration keys
            critical_keys = [
                "SECRET_KEY",
                "POSTGRES_HOST",
                "POSTGRES_DB",
                "POSTGRES_USER",
            ]
            
            missing = []
            for key in critical_keys:
                if f"{key}=" not in content:
                    missing.append(key)
            
            if missing:
                return ValidationResult(
                    "Configuration",
                    False,
                    f"Missing critical keys: {', '.join(missing)}"
                )
            
            return ValidationResult(
                "Configuration",
                True,
                f"Configuration file found at {config_file} with all critical keys"
            )
            
        except Exception as e:
            return ValidationResult(
                "Configuration",
                False,
                f"Error reading configuration: {e}"
            )
    
    def validate_gpio_availability(self) -> ValidationResult:
        """Check GPIO hardware availability (if configured)."""
        # This is optional - GPIO might not be configured in all deployments
        success, data, error = self._http_get("/health")
        
        if not success:
            return ValidationResult(
                "GPIO Availability",
                True,  # Not a failure if we can't check
                "Cannot check GPIO status (non-critical)"
            )
        
        gpio_available = data.get("gpio_available")
        if gpio_available is None:
            return ValidationResult(
                "GPIO Availability",
                True,
                "GPIO status not reported (optional feature)"
            )
        
        if gpio_available:
            return ValidationResult(
                "GPIO Availability",
                True,
                "GPIO hardware is available"
            )
        else:
            return ValidationResult(
                "GPIO Availability",
                True,  # Not a critical failure
                "GPIO hardware not available (optional feature)"
            )
    
    def validate_audio_devices(self) -> ValidationResult:
        """Check audio device availability (if configured)."""
        # Check if audio output is configured
        success, data, error = self._http_get("/api/settings/audio")
        
        if not success:
            return ValidationResult(
                "Audio Devices",
                True,  # Not a failure if we can't check
                "Cannot check audio status (non-critical)"
            )
        
        # Audio configuration is optional, so this is informational
        return ValidationResult(
            "Audio Devices",
            True,
            "Audio configuration endpoint accessible"
        )
    
    def validate_api_access(self) -> ValidationResult:
        """Check API endpoints are accessible."""
        endpoints_to_check = [
            "/api/alerts",
            "/api/release-manifest",
        ]
        
        accessible = []
        failed = []
        
        for endpoint in endpoints_to_check:
            success, _, error = self._http_get(endpoint)
            if success:
                accessible.append(endpoint)
            else:
                failed.append(f"{endpoint}: {error}")
        
        if not failed:
            return ValidationResult(
                "API Access",
                True,
                f"All {len(accessible)} API endpoints are accessible"
            )
        else:
            return ValidationResult(
                "API Access",
                False,
                f"{len(failed)} endpoint(s) failed: {', '.join(failed)}"
            )
    
    def run_all_validations(self) -> List[ValidationResult]:
        """Run all validation checks."""
        print("=" * 70)
        print("EAS Station Post-Restore Validation")
        print("=" * 70)
        print(f"Target: {self.base_url}")
        print()
        
        validators = [
            ("Web Service", self.validate_web_service),
            ("Health Endpoint", self.validate_health_endpoint),
            ("Database Connection", self.validate_database_connection),
            ("Database Migrations", self.validate_database_migrations),
            ("Dependencies", self.validate_dependencies),
            ("Configuration", self.validate_configuration),
            ("API Access", self.validate_api_access),
            ("GPIO Availability", self.validate_gpio_availability),
            ("Audio Devices", self.validate_audio_devices),
        ]
        
        results = []
        for name, validator in validators:
            print(f"Checking {name}...", end=" ", flush=True)
            try:
                result = validator()
                results.append(result)
                print("✓" if result.passed else "✗")
            except Exception as e:
                result = ValidationResult(name, False, f"Validation error: {e}")
                results.append(result)
                print("✗")
        
        self.results = results
        return results
    
    def print_summary(self) -> bool:
        """Print validation summary.
        
        Returns:
            True if all checks passed, False otherwise
        """
        print()
        print("=" * 70)
        print("Validation Results")
        print("=" * 70)
        print()
        
        passed = 0
        failed = 0
        
        for result in self.results:
            print(result)
            if result.passed:
                passed += 1
            else:
                failed += 1
                # Print details for failed checks
                if result.details:
                    print(f"  Details: {json.dumps(result.details, indent=2)}")
        
        print()
        print("=" * 70)
        print(f"Total: {len(self.results)} checks | Passed: {passed} | Failed: {failed}")
        print("=" * 70)
        
        all_passed = failed == 0
        
        if all_passed:
            print()
            print("✓ All validation checks PASSED")
            print()
            print("Next Steps:")
            print("1. Access the web UI and verify functionality")
            print("2. Check recent logs for any warnings:")
            print("   docker compose logs --since 10m | grep -i warning")
            print("3. Review system health in the admin dashboard")
            print()
        else:
            print()
            print("✗ Some validation checks FAILED")
            print()
            print("Recommended Actions:")
            print("1. Review failed checks above")
            print("2. Check application logs:")
            print("   docker compose logs --tail=100 app")
            print("3. Verify database status:")
            print("   docker compose exec app python -m alembic current")
            print("4. Restart services if needed:")
            print("   docker compose restart")
            print()
        
        return all_passed


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Validate EAS Station system health after restore",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    parser.add_argument(
        "--host",
        default=os.environ.get("VALIDATION_HOST", "localhost"),
        help="Host to connect to (default: localhost)"
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("VALIDATION_PORT", "8080")),
        help="Port to connect to (default: 8080)"
    )
    parser.add_argument(
        "--wait",
        type=int,
        default=0,
        help="Wait N seconds before starting validation"
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable verbose output"
    )
    
    args = parser.parse_args()
    
    if args.wait > 0:
        print(f"Waiting {args.wait} seconds for services to start...")
        time.sleep(args.wait)
    
    try:
        validator = RestoreValidator(host=args.host, port=args.port)
        validator.run_all_validations()
        all_passed = validator.print_summary()
        
        sys.exit(0 if all_passed else 1)
        
    except KeyboardInterrupt:
        print("\n\nValidation interrupted by user")
        sys.exit(2)
    except Exception as e:
        print(f"\n\nFatal error: {e}", file=sys.stderr)
        if args.verbose:
            import traceback
            traceback.print_exc()
        sys.exit(2)


if __name__ == "__main__":
    main()
