"""Test to verify that buffer warning messages include the mount identifier."""

import sys
from pathlib import Path

def test_buffer_warnings_include_mount():
    """Verify that all buffer-related log messages include the mount identifier."""
    
    # Read the icecast_output.py file
    icecast_file = Path(__file__).parent.parent / 'app_core' / 'audio' / 'icecast_output.py'
    
    if not icecast_file.exists():
        print(f"ERROR: Could not find {icecast_file}")
        return False
    
    content = icecast_file.read_text()
    
    # Check for buffer warning messages that should include mount identifier
    checks = [
        {
            'pattern': 'Icecast buffer running low for mount',
            'description': 'Buffer running low warning includes mount',
        },
        {
            'pattern': 'Icecast buffer completely empty for mount',
            'description': 'Buffer empty error includes mount',
        },
        {
            'pattern': 'Pre-buffer complete for mount',
            'description': 'Pre-buffer complete info includes mount',
        },
        {
            'pattern': 'Pre-buffer timeout for mount',
            'description': 'Pre-buffer timeout error includes mount',
        },
        {
            'pattern': 'Audio source for mount',
            'description': 'Audio source diagnostics include mount',
        },
    ]
    
    print("=" * 80)
    print("Testing Buffer Warning Messages Include Mount Identifier")
    print("=" * 80)
    print()
    
    all_passed = True
    
    for check in checks:
        pattern = check['pattern']
        description = check['description']
        found = pattern in content
        status = '✓' if found else '✗'
        
        print(f"{status} {description}")
        if not found:
            print(f"   ERROR: Could not find '{pattern}'")
            all_passed = False
    
    print()
    print("=" * 80)
    
    if all_passed:
        print("✅ ALL MOUNT IDENTIFIER CHECKS PASSED")
        return True
    else:
        print("✗ SOME CHECKS FAILED")
        return False


if __name__ == '__main__':
    success = test_buffer_warnings_include_mount()
    sys.exit(0 if success else 1)
