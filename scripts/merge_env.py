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
.env File Merger

Merges new configuration variables from .env.example into existing .env file
while preserving user customizations.

Problem:
- update.sh preserves existing .env file (good)
- But new config variables in .env.example are never added (bad)
- Users end up with incomplete .env files missing new features

Solution:
- Read .env.example to get all available config variables
- Read existing .env to preserve user settings
- Merge them together, keeping user values where they exist
- Add new variables with default values from .env.example
- Preserve comments and structure from .env.example

Usage:
    python3 scripts/merge_env.py [--install-dir /opt/eas-station] [--dry-run] [--backup]
"""

import os
import sys
import argparse
import re
import shutil
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Tuple, Optional

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

def parse_env_line(line: str) -> Tuple[Optional[str], Optional[str], bool]:
    """
    Parse a line from an env file.
    
    Returns:
        (key, value, is_comment) tuple
        - key: variable name or None
        - value: variable value or None
        - is_comment: True if this is a comment line
    """
    line = line.rstrip()
    
    # Empty line
    if not line:
        return (None, None, False)
    
    # Comment line
    if line.startswith('#'):
        return (None, None, True)
    
    # Variable line: KEY=value
    match = re.match(r'^([A-Z_][A-Z0-9_]*)=(.*)$', line)
    if match:
        key = match.group(1)
        value = match.group(2)
        return (key, value, False)
    
    # Malformed line
    return (None, None, False)

def read_env_file_structured(file_path: Path) -> Tuple[Dict[str, str], List[str]]:
    """
    Read an env file and return both variables and all lines.
    
    Returns:
        (variables dict, all lines list)
    """
    variables = {}
    lines = []
    
    if not file_path.exists():
        return (variables, lines)
    
    with open(file_path, 'r', encoding='utf-8') as f:
        for line in f:
            lines.append(line.rstrip())
            key, value, is_comment = parse_env_line(line)
            if key:
                variables[key] = value
    
    return (variables, lines)

def merge_env_files(
    example_vars: Dict[str, str],
    example_lines: List[str],
    existing_vars: Dict[str, str]
) -> List[str]:
    """
    Merge .env.example structure with existing .env values.
    
    Strategy:
    - Use .env.example as the structure template (preserves comments, sections)
    - Replace variable values with user's existing values where they exist
    - Keep new variables from .env.example with their default values
    
    Args:
        example_vars: Variables from .env.example
        example_lines: All lines from .env.example (including comments)
        existing_vars: Variables from existing .env
    
    Returns:
        List of merged lines
    """
    merged_lines = []
    used_keys = set()
    
    for line in example_lines:
        key, value, is_comment = parse_env_line(line)
        
        if key:
            # This is a variable line
            if key in existing_vars:
                # Use existing user value
                merged_lines.append(f"{key}={existing_vars[key]}")
                used_keys.add(key)
            else:
                # New variable - use example value
                merged_lines.append(f"{key}={value}")
                used_keys.add(key)
        else:
            # Comment or empty line - preserve as-is
            merged_lines.append(line)
    
    # Add any variables from existing .env that aren't in .env.example
    # (user-added custom variables)
    custom_vars = set(existing_vars.keys()) - used_keys
    if custom_vars:
        merged_lines.append("")
        merged_lines.append("# =============================================================================")
        merged_lines.append("# CUSTOM VARIABLES (not in .env.example)")
        merged_lines.append("# =============================================================================")
        merged_lines.append("")
        for key in sorted(custom_vars):
            merged_lines.append(f"{key}={existing_vars[key]}")
    
    return merged_lines

def create_backup(file_path: Path) -> Path:
    """Create a timestamped backup of a file."""
    if not file_path.exists():
        return None
    
    timestamp = datetime.now().strftime('%Y%m%d-%H%M%S')
    backup_path = file_path.parent / f"{file_path.name}.{timestamp}.backup"
    shutil.copy2(file_path, backup_path)
    return backup_path

def main():
    parser = argparse.ArgumentParser(
        description='Merge new variables from .env.example into existing .env file',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Dry run (show what would be done)
  python3 scripts/merge_env.py --dry-run
  
  # Merge with backup (recommended)
  python3 scripts/merge_env.py --backup
  
  # Merge for specific installation
  python3 scripts/merge_env.py --install-dir /opt/eas-station
        """
    )
    parser.add_argument('--dry-run', action='store_true',
                        help='Show what would be done without making changes')
    parser.add_argument('--backup', action='store_true',
                        help='Create timestamped backup before making changes')
    parser.add_argument('--install-dir', default='/opt/eas-station',
                        help='Installation directory (default: /opt/eas-station)')
    parser.add_argument('--force', action='store_true',
                        help='Create .env from .env.example if .env does not exist')
    
    args = parser.parse_args()
    
    install_dir = Path(args.install_dir)
    env_example = install_dir / '.env.example'
    env_file = install_dir / '.env'
    
    echo_header("🔄 EAS Station .env File Merger")
    
    if args.dry_run:
        echo_warning("DRY RUN MODE - No changes will be made")
        print()
    
    # Check if .env.example exists
    if not env_example.exists():
        echo_error(f".env.example not found: {env_example}")
        sys.exit(1)
    
    echo_success(f"Found .env.example: {env_example}")
    
    # Read .env.example
    echo_info("Reading .env.example...")
    example_vars, example_lines = read_env_file_structured(env_example)
    echo_success(f"Loaded {len(example_vars)} variables from .env.example")
    
    # Check if .env exists
    if not env_file.exists():
        if args.force:
            echo_warning(f".env not found - will create from .env.example")
            existing_vars = {}
            existing_lines = []
        else:
            echo_error(f".env not found: {env_file}")
            echo_info("Use --force to create .env from .env.example")
            sys.exit(1)
    else:
        echo_success(f"Found existing .env: {env_file}")
        
        # Read existing .env
        echo_info("Reading existing .env...")
        existing_vars, existing_lines = read_env_file_structured(env_file)
        echo_success(f"Loaded {len(existing_vars)} variables from existing .env")
    
    # Analyze differences
    echo_info("Analyzing configuration...")
    
    new_vars = set(example_vars.keys()) - set(existing_vars.keys())
    custom_vars = set(existing_vars.keys()) - set(example_vars.keys())
    common_vars = set(example_vars.keys()) & set(existing_vars.keys())
    
    # Check for value differences in common variables
    changed_defaults = []
    for key in common_vars:
        if example_vars[key] != existing_vars[key]:
            changed_defaults.append(key)
    
    print()
    echo_info(f"Configuration Analysis:")
    print(f"  Variables in .env.example:  {len(example_vars)}")
    print(f"  Variables in existing .env: {len(existing_vars)}")
    print(f"  New variables to add:       {Colors.GREEN}{len(new_vars)}{Colors.NC}")
    print(f"  Custom variables (kept):    {Colors.CYAN}{len(custom_vars)}{Colors.NC}")
    print(f"  User-customized values:     {Colors.YELLOW}{len(changed_defaults)}{Colors.NC}")
    
    if new_vars:
        print(f"\n{Colors.GREEN}New variables that will be added:{Colors.NC}")
        for key in sorted(new_vars):
            # Mask sensitive default values
            display_value = example_vars[key]
            if any(secret in key.lower() for secret in ['password', 'key', 'secret', 'token']):
                if display_value and display_value not in ['', 'change-me', 'replace-with-a-long-random-string']:
                    display_value = '***'
            print(f"  + {key}={display_value}")
    
    if custom_vars:
        print(f"\n{Colors.CYAN}Custom variables that will be preserved:{Colors.NC}")
        for key in sorted(custom_vars):
            print(f"  • {key}")
    
    # Merge
    echo_info("Merging configurations...")
    merged_lines = merge_env_files(example_vars, example_lines, existing_vars)
    
    # Show sample of merged output
    if args.dry_run:
        print(f"\n{Colors.BOLD}Sample of merged output (first 20 lines):{Colors.NC}")
        print(f"{Colors.CYAN}{'─' * 70}{Colors.NC}")
        for line in merged_lines[:20]:
            print(f"  {line}")
        if len(merged_lines) > 20:
            print(f"  ... ({len(merged_lines) - 20} more lines)")
        print(f"{Colors.CYAN}{'─' * 70}{Colors.NC}")
    
    # Create backup if requested
    if args.backup and not args.dry_run and env_file.exists():
        echo_info("Creating backup...")
        backup_path = create_backup(env_file)
        if backup_path:
            echo_success(f"Backup created: {backup_path}")
    
    # Write merged file
    if not args.dry_run:
        echo_info(f"Writing merged configuration to {env_file}...")
        
        with open(env_file, 'w', encoding='utf-8') as f:
            for line in merged_lines:
                f.write(f"{line}\n")
        
        # Set correct permissions
        os.chmod(env_file, 0o640)
        
        echo_success(f"Merged configuration written to {env_file}")
    else:
        echo_info("Would write merged configuration to {env_file}")
    
    # Summary
    print()
    echo_header("✅ Merge Summary")
    
    print(f"Total variables in merged file: {len(example_vars) + len(custom_vars)}")
    print(f"New variables added:            {len(new_vars)}")
    print(f"User customizations preserved:  {len(changed_defaults)}")
    print(f"Custom variables preserved:     {len(custom_vars)}")
    
    if args.dry_run:
        print(f"\n{Colors.YELLOW}This was a dry run. No changes were made.{Colors.NC}")
        print(f"Run without --dry-run to apply changes.")
    else:
        print(f"\n{Colors.GREEN}Merge complete!{Colors.NC}")
        print(f"\n{Colors.BOLD}Next steps:{Colors.NC}")
        print(f"1. Review the merged .env file: {env_file}")
        print(f"2. Update any new variables with your specific values")
        print(f"3. Restart services if configuration changed:")
        print(f"   {Colors.CYAN}sudo systemctl restart eas-station.target{Colors.NC}")
        
        if args.backup:
            print(f"\n{Colors.CYAN}Backup available if you need to restore:{Colors.NC}")
            print(f"   {backup_path}")
    
    print()

if __name__ == '__main__':
    main()
