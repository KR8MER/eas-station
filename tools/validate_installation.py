#!/usr/bin/env python3
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
Post-Installation Validation Script

Validates EAS Station installation and configuration, checking:
- Docker services status
- Database connectivity and schema
- Environment configuration
- Audio subsystem
- Network connectivity
- API endpoints
- File permissions

Usage:
    python tools/validate_installation.py
    python tools/validate_installation.py --verbose
    python tools/validate_installation.py --fix-permissions
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Dict, List, Tuple

# Color codes for terminal output
class Colors:
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    BLUE = '\033[94m'
    BOLD = '\033[1m'
    RESET = '\033[0m'


class ValidationResult:
    """Container for validation check results."""
    
    def __init__(self):
        self.passed: List[str] = []
        self.warnings: List[str] = []
        self.failed: List[str] = []
        self.info: List[str] = []
    
    def add_pass(self, message: str):
        self.passed.append(message)
    
    def add_warning(self, message: str):
        self.warnings.append(message)
    
    def add_fail(self, message: str):
        self.failed.append(message)
    
    def add_info(self, message: str):
        self.info.append(message)
    
    def has_failures(self) -> bool:
        return len(self.failed) > 0
    
    def print_summary(self):
        """Print colored summary of results."""
        print(f"\n{Colors.BOLD}=== Validation Summary ==={Colors.RESET}\n")
        
        if self.passed:
            print(f"{Colors.GREEN}✓ Passed ({len(self.passed)}):{Colors.RESET}")
            for msg in self.passed:
                print(f"  • {msg}")
        
        if self.warnings:
            print(f"\n{Colors.YELLOW}⚠ Warnings ({len(self.warnings)}):{Colors.RESET}")
            for msg in self.warnings:
                print(f"  • {msg}")
        
        if self.failed:
            print(f"\n{Colors.RED}✗ Failed ({len(self.failed)}):{Colors.RESET}")
            for msg in self.failed:
                print(f"  • {msg}")
        
        if self.info:
            print(f"\n{Colors.BLUE}ℹ Information:{Colors.RESET}")
            for msg in self.info:
                print(f"  • {msg}")
        
        print()


def run_command(cmd: List[str], capture=True) -> Tuple[int, str, str]:
    """Run shell command and return exit code, stdout, stderr."""
    try:
        if capture:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30
            )
            return result.returncode, result.stdout, result.stderr
        else:
            result = subprocess.run(cmd, timeout=30)
            return result.returncode, "", ""
    except subprocess.TimeoutExpired:
        return -1, "", "Command timed out"
    except Exception as e:
        return -1, "", str(e)


def check_docker_installed(results: ValidationResult, verbose: bool = False):
    """Check if Docker and Docker Compose are installed."""
    print("Checking Docker installation...")
    
    # Check Docker
    code, stdout, stderr = run_command(["docker", "--version"])
    if code == 0:
        results.add_pass(f"Docker is installed: {stdout.strip()}")
        if verbose:
            results.add_info(f"Docker version: {stdout.strip()}")
    else:
        results.add_fail("Docker is not installed or not in PATH")
        return
    
    # Check Docker Compose
    code, stdout, stderr = run_command(["docker", "compose", "version"])
    if code == 0:
        results.add_pass(f"Docker Compose is installed: {stdout.strip()}")
    else:
        results.add_fail("Docker Compose V2 is not installed")


def check_services_running(results: ValidationResult, verbose: bool = False):
    """Check if EAS Station services are running."""
    print("Checking service status...")
    
    code, stdout, stderr = run_command(["docker", "compose", "ps", "--format", "json"])
    if code != 0:
        results.add_fail("Unable to check Docker Compose services")
        return
    
    # Parse service status
    import json
    try:
        services = []
        for line in stdout.strip().split('\n'):
            if line:
                services.append(json.loads(line))
        
        if not services:
            results.add_fail("No Docker Compose services found")
            return
        
        expected_services = ["app", "nginx", "alerts-db"]
        running_services = [s for s in services if s.get("State") == "running"]
        
        for service in services:
            name = service.get("Service", "unknown")
            state = service.get("State", "unknown")
            
            if state == "running":
                results.add_pass(f"Service '{name}' is running")
            else:
                results.add_fail(f"Service '{name}' is not running (state: {state})")
        
        # Check for expected services
        running_names = [s.get("Service") for s in running_services]
        for expected in expected_services:
            if expected not in running_names:
                results.add_warning(f"Expected service '{expected}' not found")
    
    except json.JSONDecodeError:
        results.add_warning("Could not parse service status (older Docker version?)")


def check_database_connection(results: ValidationResult, verbose: bool = False):
    """Check database connectivity."""
    print("Checking database connection...")
    
    # Try to connect to database via app container
    code, stdout, stderr = run_command([
        "docker", "compose", "exec", "-T", "app",
        "python", "-c",
        "from app_core.extensions import db; "
        "from app import create_app; "
        "app = create_app(); "
        "with app.app_context(): db.engine.connect(); "
        "print('OK')"
    ])
    
    if code == 0 and "OK" in stdout:
        results.add_pass("Database connection successful")
    else:
        results.add_fail(f"Database connection failed: {stderr}")


def check_environment_config(results: ValidationResult, verbose: bool = False):
    """Check environment configuration."""
    print("Checking environment configuration...")
    
    env_file = Path(".env")
    if not env_file.exists():
        results.add_fail(".env file not found")
        return
    
    results.add_pass(".env file exists")
    
    # Check critical environment variables
    critical_vars = [
        "SECRET_KEY",
        "POSTGRES_PASSWORD",
        "DEFAULT_STATE_CODE",
        "DEFAULT_COUNTY_NAME"
    ]
    
    env_content = env_file.read_text()
    for var in critical_vars:
        if f"{var}=" in env_content:
            # Check if it's not using default/example values
            if var == "SECRET_KEY":
                if "your-secret-key-here" in env_content or "CHANGE_ME" in env_content:
                    results.add_warning(f"{var} appears to use a default value")
                else:
                    results.add_pass(f"{var} is configured")
            elif var == "POSTGRES_PASSWORD":
                if "changeme" in env_content or "password" in env_content.lower():
                    results.add_warning(f"{var} appears to use a weak default password")
                else:
                    results.add_pass(f"{var} is configured")
            else:
                results.add_pass(f"{var} is configured")
        else:
            results.add_warning(f"{var} not found in .env file")


def check_web_interface(results: ValidationResult, verbose: bool = False):
    """Check if web interface is accessible."""
    print("Checking web interface...")
    
    # Check if curl is available
    code, _, _ = run_command(["which", "curl"])
    if code != 0:
        results.add_warning("curl not installed, skipping web interface check")
        return
    
    # Check HTTP endpoint (should redirect to HTTPS)
    code, stdout, stderr = run_command([
        "curl", "-s", "-o", "/dev/null", "-w", "%{http_code}",
        "http://localhost", "--max-time", "10"
    ])
    
    if code == 0:
        status_code = stdout.strip()
        if status_code in ["200", "301", "302"]:
            results.add_pass(f"Web interface responding (HTTP {status_code})")
        else:
            results.add_warning(f"Web interface returned HTTP {status_code}")
    else:
        results.add_fail("Web interface not accessible on port 80")
    
    # Check HTTPS endpoint
    code, stdout, stderr = run_command([
        "curl", "-k", "-s", "-o", "/dev/null", "-w", "%{http_code}",
        "https://localhost", "--max-time", "10"
    ])
    
    if code == 0:
        status_code = stdout.strip()
        if status_code == "200":
            results.add_pass("HTTPS interface responding")
        else:
            results.add_warning(f"HTTPS interface returned HTTP {status_code}")
    else:
        results.add_fail("HTTPS interface not accessible on port 443")


def check_health_endpoint(results: ValidationResult, verbose: bool = False):
    """Check /health/dependencies endpoint."""
    print("Checking health endpoint...")
    
    code, _, _ = run_command(["which", "curl"])
    if code != 0:
        results.add_warning("curl not installed, skipping health check")
        return
    
    code, stdout, stderr = run_command([
        "curl", "-k", "-s",
        "https://localhost/health/dependencies",
        "--max-time", "10"
    ])
    
    if code == 0:
        try:
            import json
            health_data = json.loads(stdout)
            
            if health_data.get("status") == "healthy":
                results.add_pass("System health check passed")
                
                # Check individual dependencies
                deps = health_data.get("dependencies", {})
                for dep_name, dep_status in deps.items():
                    if dep_status.get("healthy"):
                        if verbose:
                            results.add_info(f"Dependency '{dep_name}' is healthy")
                    else:
                        results.add_warning(f"Dependency '{dep_name}' is unhealthy")
            else:
                results.add_warning("System health check returned non-healthy status")
        
        except json.JSONDecodeError:
            results.add_warning("Could not parse health check response")
    else:
        results.add_fail("Health check endpoint not accessible")


def check_file_permissions(results: ValidationResult, fix: bool = False, verbose: bool = False):
    """Check and optionally fix file permissions."""
    print("Checking file permissions...")
    
    # Directories that should be writable
    writable_dirs = [
        "static/exports",
        "static/audio",
        "logs",
    ]
    
    for dir_path in writable_dirs:
        path = Path(dir_path)
        if path.exists():
            if os.access(path, os.W_OK):
                results.add_pass(f"Directory '{dir_path}' is writable")
            else:
                if fix:
                    try:
                        os.chmod(path, 0o755)
                        results.add_pass(f"Fixed permissions for '{dir_path}'")
                    except Exception as e:
                        results.add_fail(f"Could not fix permissions for '{dir_path}': {e}")
                else:
                    results.add_warning(f"Directory '{dir_path}' may not be writable")
        else:
            if verbose:
                results.add_info(f"Directory '{dir_path}' does not exist (may be created on first use)")


def check_audio_devices(results: ValidationResult, verbose: bool = False):
    """Check for audio devices."""
    print("Checking audio devices...")
    
    # Check if audio is enabled in environment
    env_file = Path(".env")
    if env_file.exists():
        env_content = env_file.read_text()
        if "AUDIO_OUTPUT_ENABLED=false" in env_content:
            results.add_info("Audio output is disabled in configuration")
            return
    
    # Try to list audio devices via container
    code, stdout, stderr = run_command([
        "docker", "compose", "exec", "-T", "app",
        "aplay", "-l"
    ])
    
    if code == 0:
        if "card" in stdout.lower():
            results.add_pass("Audio devices detected")
            if verbose:
                results.add_info(f"Audio devices:\n{stdout}")
        else:
            results.add_warning("No audio devices found")
    else:
        results.add_info("Could not check audio devices (may not be configured)")


def check_log_files(results: ValidationResult, verbose: bool = False):
    """Check for recent errors in log files."""
    print("Checking logs for errors...")
    
    # Get recent logs from all services
    code, stdout, stderr = run_command([
        "docker", "compose", "logs", "--tail=100"
    ])
    
    if code == 0:
        # Look for common error patterns
        error_patterns = ["ERROR", "CRITICAL", "Exception", "Traceback"]
        errors_found = []
        
        for pattern in error_patterns:
            if pattern in stdout:
                errors_found.append(pattern)
        
        if errors_found:
            results.add_warning(f"Found error patterns in logs: {', '.join(set(errors_found))}")
            results.add_info("Review logs with: docker compose logs --tail=100")
        else:
            results.add_pass("No obvious errors in recent logs")
    else:
        results.add_warning("Could not retrieve Docker Compose logs")


def main():
    """Main validation routine."""
    parser = argparse.ArgumentParser(
        description="Validate EAS Station installation",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Show detailed information"
    )
    parser.add_argument(
        "--fix-permissions",
        action="store_true",
        help="Attempt to fix file permission issues"
    )
    parser.add_argument(
        "--skip-web",
        action="store_true",
        help="Skip web interface checks"
    )
    
    args = parser.parse_args()
    
    # Print header
    print(f"\n{Colors.BOLD}{Colors.BLUE}EAS Station Installation Validator{Colors.RESET}")
    print(f"{Colors.BLUE}{'=' * 50}{Colors.RESET}\n")
    
    results = ValidationResult()
    
    # Run validation checks
    try:
        check_docker_installed(results, args.verbose)
        check_services_running(results, args.verbose)
        check_environment_config(results, args.verbose)
        check_database_connection(results, args.verbose)
        
        if not args.skip_web:
            check_web_interface(results, args.verbose)
            check_health_endpoint(results, args.verbose)
        
        check_file_permissions(results, args.fix_permissions, args.verbose)
        check_audio_devices(results, args.verbose)
        check_log_files(results, args.verbose)
    
    except KeyboardInterrupt:
        print(f"\n{Colors.YELLOW}Validation interrupted by user{Colors.RESET}")
        sys.exit(130)
    
    except Exception as e:
        print(f"\n{Colors.RED}Unexpected error during validation: {e}{Colors.RESET}")
        sys.exit(1)
    
    # Print results
    results.print_summary()
    
    # Exit with appropriate code
    if results.has_failures():
        print(f"{Colors.RED}Validation failed. Please address the issues above.{Colors.RESET}\n")
        sys.exit(1)
    elif results.warnings:
        print(f"{Colors.YELLOW}Validation completed with warnings.{Colors.RESET}\n")
        sys.exit(0)
    else:
        print(f"{Colors.GREEN}All validation checks passed!{Colors.RESET}\n")
        sys.exit(0)


if __name__ == "__main__":
    main()
