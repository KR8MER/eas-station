#!/usr/bin/env python3
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

"""
Environment Variable Migration Utility

This script helps migrate environment variables from systemd service files
to the .env configuration file, eliminating conflicts and confusion.

Problem:
- Settings in systemd service files (Environment=) override .env file
- Users update settings in web UI → writes to .env
- But systemd env vars take precedence → changes don't appear to work

Solution:
- Extract environment variables from systemd service files
- Merge them into .env file with proper precedence
- Remove redundant Environment= lines from systemd files
- Restart services to pick up new configuration

Usage:
    sudo python3 scripts/migrate_env.py [--dry-run] [--backup]
"""

import os
import sys
import argparse
import re
import shutil
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Tuple, Set

# ANSI color codes
class Colors:
    BLUE = '\033[0;34m'
    GREEN = '\033[0;32m'
    YELLOW = '\033[1;33m'
    RED = '\033[0;31m'
    CYAN = '\033[0;36m'
    BOLD = '\033[1m'
    NC = '\033[0m'  # No Color

def echo_info(msg: str):
    print(f"{Colors.BLUE}ℹ️  [INFO]{Colors.NC} {msg}")

def echo_success(msg: str):
    print(f"{Colors.GREEN}✓  [SUCCESS]{Colors.NC} {msg}")

def echo_warning(msg: str):
    print(f"{Colors.YELLOW}⚠️  [WARNING]{Colors.NC} {msg}")

def echo_error(msg: str):
    print(f"{Colors.RED}✗  [ERROR]{Colors.NC} {msg}")

def echo_header(msg: str):
    print(f"\n{Colors.BOLD}{Colors.CYAN}{msg}{Colors.NC}\n")

# Configuration variables that should be migrated from systemd to .env
MIGRATABLE_VARS = {
    'NOAA_USER_AGENT',
    'IPAWS_CAP_FEED_URLS',
    'CAP_ENDPOINTS',
    'POLL_INTERVAL_SEC',
    'CONFIG_PATH',
    'LOG_LEVEL',
    'POSTGRES_HOST',
    'POSTGRES_PORT',
    'POSTGRES_DB',
    'POSTGRES_USER',
    'POSTGRES_PASSWORD',
    'DATABASE_URL',
    'REDIS_URL',
    'REDIS_HOST',
    'REDIS_PORT',
}

# Variables that should stay in systemd (system-level config)
SYSTEMD_ONLY_VARS = {
    'PATH',
    'PYTHONUNBUFFERED',
    'PYTHONPATH',
    'HOME',
    'USER',
    'LOGNAME',
}

def find_systemd_service_files(systemd_dir: Path) -> List[Path]:
    """Find all systemd service files in the given directory."""
    if not systemd_dir.exists():
        return []
    return list(systemd_dir.glob('*.service'))

def extract_env_vars_from_service(service_file: Path) -> Dict[str, str]:
    """Extract Environment= variables from a systemd service file."""
    env_vars = {}
    
    with open(service_file, 'r') as f:
        for line in f:
            line = line.strip()
            # Match Environment="KEY=value" or Environment=KEY=value
            match = re.match(r'^Environment=(?:")?([A-Z_][A-Z0-9_]*)=(.*)(?:")?$', line)
            if match:
                key = match.group(1)
                value = match.group(2).strip('"')
                env_vars[key] = value
    
    return env_vars

def read_env_file(env_file: Path) -> Dict[str, str]:
    """Read variables from .env file."""
    env_vars = {}
    
    if not env_file.exists():
        return env_vars
    
    with open(env_file, 'r') as f:
        for line in f:
            line = line.strip()
            # Skip comments and empty lines
            if not line or line.startswith('#'):
                continue
            # Match KEY=value
            match = re.match(r'^([A-Z_][A-Z0-9_]*)=(.*)$', line)
            if match:
                key = match.group(1)
                value = match.group(2)
                env_vars[key] = value
    
    return env_vars

def write_env_file(env_file: Path, env_vars: Dict[str, str], header_comment: str = None):
    """Write variables to .env file, preserving structure."""
    # Read existing file to preserve comments and structure
    existing_lines = []
    existing_keys = set()
    
    if env_file.exists():
        with open(env_file, 'r') as f:
            for line in f:
                existing_lines.append(line.rstrip())
                # Track which keys are already in the file
                match = re.match(r'^([A-Z_][A-Z0-9_]*)=', line.strip())
                if match:
                    existing_keys.add(match.group(1))
    
    # Write updated file
    with open(env_file, 'w') as f:
        # Write header comment if provided
        if header_comment:
            f.write(f"# {header_comment}\n")
            f.write(f"# Updated: {datetime.now().isoformat()}\n\n")
        
        # Write existing lines, updating values where needed
        for line in existing_lines:
            match = re.match(r'^([A-Z_][A-Z0-9_]*)=', line.strip())
            if match and match.group(1) in env_vars:
                key = match.group(1)
                f.write(f"{key}={env_vars[key]}\n")
                # Remove from dict so we don't add it again
                del env_vars[key]
            else:
                f.write(f"{line}\n")
        
        # Add any new variables that weren't in the file
        if env_vars:
            f.write("\n# Variables migrated from systemd service files\n")
            for key, value in sorted(env_vars.items()):
                f.write(f"{key}={value}\n")

def remove_env_vars_from_service(service_file: Path, keys_to_remove: Set[str], dry_run: bool = False) -> int:
    """Remove Environment= lines from systemd service file."""
    if dry_run:
        return 0
    
    lines = []
    removed_count = 0
    
    with open(service_file, 'r') as f:
        for line in f:
            # Check if this is an Environment= line for a key we're migrating
            match = re.match(r'^Environment=(?:")?([A-Z_][A-Z0-9_]*)=', line.strip())
            if match and match.group(1) in keys_to_remove:
                # Skip this line (remove it)
                removed_count += 1
                # Add comment showing it was migrated
                lines.append(f"# Migrated to .env: {line.strip()}\n")
            else:
                lines.append(line)
    
    # Write back to file
    with open(service_file, 'w') as f:
        f.writelines(lines)
    
    return removed_count

def create_backup(file_path: Path, backup_dir: Path):
    """Create a timestamped backup of a file."""
    backup_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime('%Y%m%d-%H%M%S')
    backup_name = f"{file_path.name}.{timestamp}.backup"
    backup_path = backup_dir / backup_name
    shutil.copy2(file_path, backup_path)
    return backup_path

def main():
    parser = argparse.ArgumentParser(
        description='Migrate environment variables from systemd service files to .env file',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Dry run (show what would be done without making changes)
  sudo python3 scripts/migrate_env.py --dry-run
  
  # Migrate with backups (recommended)
  sudo python3 scripts/migrate_env.py --backup
  
  # Migrate without backups
  sudo python3 scripts/migrate_env.py
        """
    )
    parser.add_argument('--dry-run', action='store_true',
                        help='Show what would be done without making changes')
    parser.add_argument('--backup', action='store_true',
                        help='Create timestamped backups before making changes')
    parser.add_argument('--install-dir', default='/opt/eas-station',
                        help='Installation directory (default: /opt/eas-station)')
    parser.add_argument('--systemd-dir', default='/etc/systemd/system',
                        help='Systemd directory (default: /etc/systemd/system)')
    
    args = parser.parse_args()
    
    # Check if running as root
    if os.geteuid() != 0 and not args.dry_run:
        echo_error("This script must be run as root (use sudo)")
        echo_info("Or use --dry-run to see what would be done")
        sys.exit(1)
    
    install_dir = Path(args.install_dir)
    systemd_dir = Path(args.systemd_dir)
    env_file = install_dir / '.env'
    backup_dir = install_dir / 'backups' / 'migration'
    
    echo_header("🔄 EAS Station Environment Variable Migration")
    
    if args.dry_run:
        echo_warning("DRY RUN MODE - No changes will be made")
        print()
    
    # Step 1: Find service files
    echo_info("Scanning systemd service files...")
    service_files = [f for f in find_systemd_service_files(systemd_dir) 
                     if 'eas-station' in f.name or 'eas-' in f.name]
    
    if not service_files:
        echo_warning("No EAS Station service files found")
        sys.exit(0)
    
    echo_success(f"Found {len(service_files)} service file(s)")
    for sf in service_files:
        print(f"  • {sf.name}")
    print()
    
    # Step 2: Extract environment variables from service files
    echo_info("Extracting environment variables from service files...")
    all_service_vars = {}
    service_vars_by_file = {}
    
    for service_file in service_files:
        vars_in_file = extract_env_vars_from_service(service_file)
        service_vars_by_file[service_file] = vars_in_file
        all_service_vars.update(vars_in_file)
    
    migratable_vars = {k: v for k, v in all_service_vars.items() 
                       if k in MIGRATABLE_VARS}
    
    if not migratable_vars:
        echo_success("No migratable environment variables found in service files")
        echo_info("Configuration is already properly managed through .env file")
        sys.exit(0)
    
    echo_success(f"Found {len(migratable_vars)} migratable variable(s):")
    for key, value in migratable_vars.items():
        # Mask sensitive values
        display_value = value
        if any(secret in key.lower() for secret in ['password', 'key', 'secret', 'token']):
            display_value = '***' if value else '(empty)'
        print(f"  • {key}={display_value}")
    print()
    
    # Step 3: Read current .env file
    echo_info("Reading current .env file...")
    current_env = read_env_file(env_file)
    
    # Step 4: Determine conflicts and merges
    echo_info("Analyzing configuration conflicts...")
    conflicts = []
    new_vars = []
    
    for key, service_value in migratable_vars.items():
        if key in current_env:
            if current_env[key] != service_value:
                conflicts.append((key, current_env[key], service_value))
        else:
            new_vars.append((key, service_value))
    
    if conflicts:
        echo_warning(f"Found {len(conflicts)} configuration conflict(s):")
        for key, env_val, svc_val in conflicts:
            print(f"  • {key}")
            print(f"    .env file:    {env_val}")
            print(f"    systemd:      {svc_val}")
            print(f"    {Colors.YELLOW}→ Will use systemd value (currently active){Colors.NC}")
        print()
    
    if new_vars:
        echo_info(f"Found {len(new_vars)} new variable(s) to add to .env:")
        for key, value in new_vars:
            # Mask sensitive values
            display_value = value
            if any(secret in key.lower() for secret in ['password', 'key', 'secret', 'token']):
                display_value = '***' if value else '(empty)'
            print(f"  • {key}={display_value}")
        print()
    
    # Step 5: Create backups if requested
    if args.backup and not args.dry_run:
        echo_info("Creating backups...")
        
        if env_file.exists():
            backup_path = create_backup(env_file, backup_dir)
            echo_success(f"Backed up .env to: {backup_path}")
        
        for service_file in service_files:
            if service_vars_by_file[service_file]:
                backup_path = create_backup(service_file, backup_dir)
                echo_success(f"Backed up {service_file.name} to: {backup_path}")
        print()
    
    # Step 6: Update .env file
    if not args.dry_run:
        echo_info("Updating .env file with migrated variables...")
        
        # Merge variables (systemd values take precedence)
        merged_env = current_env.copy()
        merged_env.update(migratable_vars)
        
        write_env_file(
            env_file,
            merged_env,
            header_comment="EAS Station Configuration (migrated from systemd)"
        )
        
        # Set correct permissions
        os.chmod(env_file, 0o640)
        
        echo_success("Updated .env file")
    else:
        echo_info("Would update .env file with migrated variables")
    
    # Step 7: Remove variables from systemd service files
    total_removed = 0
    for service_file in service_files:
        vars_in_file = service_vars_by_file[service_file]
        keys_to_remove = set(vars_in_file.keys()) & MIGRATABLE_VARS
        
        if keys_to_remove:
            removed = remove_env_vars_from_service(service_file, keys_to_remove, args.dry_run)
            total_removed += removed
            
            if args.dry_run:
                echo_info(f"Would remove {len(keys_to_remove)} variable(s) from {service_file.name}")
            else:
                echo_success(f"Removed {removed} variable(s) from {service_file.name}")
    
    # Step 8: Reload systemd
    if not args.dry_run and total_removed > 0:
        echo_info("Reloading systemd daemon...")
        os.system('systemctl daemon-reload')
        echo_success("Systemd daemon reloaded")
    
    # Summary
    print()
    echo_header("✅ Migration Summary")
    
    print(f"Variables migrated to .env:     {len(migratable_vars)}")
    print(f"Configuration conflicts:        {len(conflicts)}")
    print(f"New variables added:            {len(new_vars)}")
    print(f"Systemd lines removed:          {total_removed}")
    
    if args.dry_run:
        print(f"\n{Colors.YELLOW}This was a dry run. No changes were made.{Colors.NC}")
        print(f"Run without --dry-run to apply changes.")
    else:
        print(f"\n{Colors.GREEN}Migration complete!{Colors.NC}")
        print(f"\n{Colors.BOLD}Next steps:{Colors.NC}")
        print(f"1. Review the updated .env file: {env_file}")
        print(f"2. Restart services to pick up new configuration:")
        print(f"   {Colors.CYAN}sudo systemctl restart eas-station.target{Colors.NC}")
        
        if args.backup:
            print(f"3. Backups saved to: {backup_dir}")
            print(f"   (can be restored if needed)")
    
    print()

if __name__ == '__main__':
    main()
