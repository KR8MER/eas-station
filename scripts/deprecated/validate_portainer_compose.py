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
Validate docker-compose files for Portainer compatibility.

This script checks that compose files don't reference .env files
which would cause deployment failures in Portainer.
"""

import sys
import yaml
from pathlib import Path


def check_compose_file(filepath):
    """Check a compose file for .env references."""
    print(f"\nChecking: {filepath}")

    with open(filepath, 'r') as f:
        content = f.read()

    # Check for literal .env references in the file
    issues = []

    for line_num, line in enumerate(content.split('\n'), 1):
        if 'env_file' in line:
            issues.append(f"  Line {line_num}: Found 'env_file' reference: {line.strip()}")
        if line.strip() == '- .env':
            issues.append(f"  Line {line_num}: Found '.env' file reference: {line.strip()}")

    if issues:
        print("❌ FAILED - Found .env references:")
        for issue in issues:
            print(issue)
        return False
    else:
        print("✅ PASSED - No .env references found")
        return True


def main():
    """Validate all Portainer compose files."""
    print("=" * 60)
    print("Portainer Docker Compose Validation")
    print("=" * 60)

    compose_files = [
        'docker-compose.yml',
        'docker-compose.embedded-db.yml'
    ]

    all_passed = True

    for filename in compose_files:
        filepath = Path(filename)
        if filepath.exists():
            if not check_compose_file(filepath):
                all_passed = False
        else:
            print(f"\n⚠️  WARNING: {filename} not found")
            all_passed = False

    print("\n" + "=" * 60)
    if all_passed:
        print("✅ All compose files are Portainer-compatible!")
        print("=" * 60)
        return 0
    else:
        print("❌ Some files have issues - fix before deploying to Portainer")
        print("=" * 60)
        return 1


if __name__ == '__main__':
    sys.exit(main())
