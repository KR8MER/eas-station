#!/usr/bin/env python3
"""
RBDS Complete System Validation

This script performs a comprehensive end-to-end validation of the RBDS system
to ensure all components are properly configured and working together.

Run after deploying RBDS fixes to verify everything is correct.
"""

import sys
from pathlib import Path

# Colors for output
class Colors:
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    BLUE = '\033[94m'
    BOLD = '\033[1m'
    END = '\033[0m'

def print_section(title):
    print(f"\n{Colors.BOLD}{Colors.BLUE}{'='*80}{Colors.END}")
    print(f"{Colors.BOLD}{Colors.BLUE}{title}{Colors.END}")
    print(f"{Colors.BOLD}{Colors.BLUE}{'='*80}{Colors.END}\n")

def print_pass(msg):
    print(f"  {Colors.GREEN}✅ PASS{Colors.END}: {msg}")

def print_warn(msg):
    print(f"  {Colors.YELLOW}⚠️  WARN{Colors.END}: {msg}")

def print_fail(msg):
    print(f"  {Colors.RED}❌ FAIL{Colors.END}: {msg}")

def print_info(msg):
    print(f"  {Colors.BLUE}ℹ️  INFO{Colors.END}: {msg}")


def check_code_fix():
    """Verify the register reset fix is present."""
    print_section("1. Verifying Code Fix")
    
    demod_file = Path("app_core/radio/demodulation.py")
    if not demod_file.exists():
        print_fail(f"Cannot find {demod_file}")
        return False
    
    with open(demod_file, 'r') as f:
        lines = f.readlines()
    
    # Check for register reset after block processing
    found_reset = False
    found_counter_reset = False
    in_sync_block = False
    
    for i, line in enumerate(lines):
        if "SYNCED MODE" in line or "synced mode" in line.lower():
            in_sync_block = True
        
        if in_sync_block:
            if "_rbds_block_bit_counter = 0" in line:
                found_counter_reset = True
                # Check next 10 lines for register reset
                for j in range(i+1, min(len(lines), i+10)):
                    if "_rbds_reg = 0" in lines[j]:
                        found_reset = True
                        print_pass(f"Register reset found at line {j+1} (after block counter reset at line {i+1})")
                        break
                break
    
    if not found_counter_reset:
        print_fail("Could not find block counter reset in synced mode")
        return False
    
    if not found_reset:
        print_fail("CRITICAL: Register reset missing after block processing!")
        print_info("This is the bug that causes 100% CRC failures")
        print_info("Expected: self._rbds_reg = 0 after self._rbds_block_bit_counter = 0")
        return False
    
    # Check for DSP processing order
    mm_line = None
    costas_line = None
    bpsk_line = None
    
    for i, line in enumerate(lines):
        if "_mm_timing" in line and "x = " in line:
            mm_line = i + 1
        if "_costas" in line and "x = " in line and mm_line:
            costas_line = i + 1
        if "bits_raw" in line and "np.real(x) > 0" in line and costas_line:
            bpsk_line = i + 1
            break
    
    if mm_line and costas_line and bpsk_line:
        if mm_line < costas_line < bpsk_line:
            print_pass(f"DSP order correct: M&M (line {mm_line}) → Costas (line {costas_line}) → BPSK (line {bpsk_line})")
        else:
            print_fail(f"DSP order wrong: M&M={mm_line}, Costas={costas_line}, BPSK={bpsk_line}")
            return False
    else:
        print_warn("Could not verify DSP processing order")
    
    # Check for differential decoding
    diff_decode_found = False
    for line in lines:
        if "% 2" in line and ("[1:]" in line or "[:-1]" in line):
            diff_decode_found = True
            print_pass("Differential decoding uses modulo arithmetic formula")
            break
    
    if not diff_decode_found:
        print_warn("Could not verify differential decoding formula")
    
    return True


def check_requirements():
    """Check Python package requirements."""
    print_section("2. Checking Python Requirements")
    
    try:
        import numpy as np
        print_pass(f"NumPy {np.__version__} installed")
    except ImportError:
        print_fail("NumPy not installed - REQUIRED for RBDS")
        return False
    
    try:
        import scipy
        print_pass(f"SciPy {scipy.__version__} installed (for high-quality resampling)")
    except ImportError:
        print_warn("SciPy not installed - will use fallback resampling (lower quality)")
    
    try:
        import numba
        print_pass(f"Numba {numba.__version__} installed (10-100x speedup for RBDS)")
    except ImportError:
        print_warn("Numba not installed - RBDS will be VERY slow (pure Python)")
        print_info("Install with: pip install numba==0.60.0")
    
    return True


def check_configuration_files():
    """Check configuration and documentation files."""
    print_section("3. Checking Configuration Files")
    
    files_to_check = [
        ("requirements.txt", True, "Python dependencies"),
        ("app_core/models.py", True, "Database models (RadioReceiver.enable_rbds)"),
        ("webapp/routes_settings_radio.py", True, "Radio settings API routes"),
        ("templates/admin/radio.html", True, "Radio settings UI"),
        ("RBDS_DIAGNOSTIC_REPORT.md", True, "Diagnostic report (just created)"),
    ]
    
    all_found = True
    for file_path, required, description in files_to_check:
        path = Path(file_path)
        if path.exists():
            print_pass(f"{file_path} exists ({description})")
        else:
            if required:
                print_fail(f"{file_path} missing ({description})")
                all_found = False
            else:
                print_warn(f"{file_path} missing ({description})")
    
    # Check requirements.txt for numba
    req_file = Path("requirements.txt")
    if req_file.exists():
        with open(req_file, 'r') as f:
            content = f.read()
        if "numba" in content:
            print_pass("Numba is in requirements.txt")
        else:
            print_warn("Numba not in requirements.txt")
    
    return all_found


def check_ui_configuration():
    """Check UI configuration for RBDS settings."""
    print_section("4. Checking UI Configuration")
    
    radio_html = Path("templates/admin/radio.html")
    if not radio_html.exists():
        print_fail("templates/admin/radio.html not found")
        return False
    
    with open(radio_html, 'r') as f:
        content = f.read()
    
    # Check for RBDS checkbox
    if 'id="receiverRBDS"' in content:
        print_pass("RBDS checkbox exists in radio settings UI")
    else:
        print_fail("RBDS checkbox not found in UI")
        return False
    
    # Check for proper input type (should be checkbox, not text)
    if 'type="checkbox" id="receiverRBDS"' in content:
        print_pass("RBDS uses checkbox (correct - not text input)")
    else:
        print_warn("RBDS input type might not be checkbox")
    
    # Check for enable_rbds in form submission
    if 'enable_rbds' in content:
        print_pass("enable_rbds handled in form submission")
    else:
        print_warn("enable_rbds might not be properly handled")
    
    return True


def check_database_models():
    """Check database model definition."""
    print_section("5. Checking Database Models")
    
    models_file = Path("app_core/models.py")
    if not models_file.exists():
        print_fail("app_core/models.py not found")
        return False
    
    with open(models_file, 'r') as f:
        content = f.read()
    
    # Check for enable_rbds column
    if "enable_rbds" in content and "db.Column" in content:
        print_pass("RadioReceiver.enable_rbds column exists in database model")
    else:
        print_fail("RadioReceiver.enable_rbds column not found")
        return False
    
    # Check for to_config method
    if "def to_config" in content:
        print_pass("RadioReceiver.to_config() method exists")
    else:
        print_warn("RadioReceiver.to_config() method might be missing")
    
    return True


def print_deployment_checklist():
    """Print deployment checklist."""
    print_section("DEPLOYMENT CHECKLIST")
    
    print(f"{Colors.BOLD}After deploying this fix:{Colors.END}\n")
    
    checklist = [
        ("Restart audio service", "systemctl restart eas-station-audio.service"),
        ("Check service status", "systemctl status eas-station-audio.service"),
        ("Monitor logs for RBDS", "journalctl -u eas-station-audio.service -f | grep -i rbds"),
        ("Run diagnostic tool", "python3 tools/rbds_auto_diagnostic.py"),
        ("Validate config", "python3 tools/validate_rbds_stereo_config.py"),
    ]
    
    for step, command in checklist:
        print(f"  [ ] {Colors.BOLD}{step}{Colors.END}")
        print(f"      {Colors.BLUE}${Colors.END} {command}")
        print()
    
    print(f"{Colors.BOLD}What to look for in logs:{Colors.END}\n")
    
    log_patterns = [
        ("RBDS ENABLED", "RBDSWorker thread started"),
        ("RBDS SYNCHRONIZED", "Decoder found correct bit alignment"),
        ("RBDS group: PI=", "Decoded group (station info)"),
        ("RBDS decoded: PS=", "Station name decoded"),
    ]
    
    for pattern, description in log_patterns:
        print(f"  {Colors.GREEN}✅{Colors.END} {Colors.BOLD}{pattern}{Colors.END}: {description}")
    
    print(f"\n{Colors.BOLD}Web UI verification:{Colors.END}\n")
    print(f"  1. Admin → Radio Settings")
    print(f"     - Check 'Extract RBDS/RDS' checkbox")
    print(f"     - Verify sample rate ≥ 114000 Hz")
    print(f"     - Modulation must be FM or WFM (not NFM)")
    print(f"  2. Audio Monitoring page")
    print(f"     - Look for 'FM Stereo / RBDS Information' section")
    print(f"     - Should show: Station Name (PS), PI Code, Radio Text")


def main():
    print(f"\n{Colors.BOLD}RBDS Complete System Validation{Colors.END}")
    print(f"Verifying RBDS fix and configuration...\n")
    
    all_passed = True
    
    all_passed &= check_code_fix()
    all_passed &= check_requirements()
    all_passed &= check_configuration_files()
    all_passed &= check_ui_configuration()
    all_passed &= check_database_models()
    
    print_deployment_checklist()
    
    print_section("VALIDATION SUMMARY")
    
    if all_passed:
        print(f"{Colors.GREEN}{Colors.BOLD}✅ ALL CHECKS PASSED{Colors.END}")
        print(f"\nThe RBDS fix is properly applied and all components are present.")
        print(f"Deploy this code and follow the checklist above to verify RBDS works.")
        print(f"\nSee {Colors.BOLD}RBDS_DIAGNOSTIC_REPORT.md{Colors.END} for detailed information.\n")
        return 0
    else:
        print(f"{Colors.RED}{Colors.BOLD}❌ SOME CHECKS FAILED{Colors.END}")
        print(f"\nReview the failures above and fix them before deploying.")
        print(f"RBDS may not work correctly with the reported issues.\n")
        return 1


if __name__ == "__main__":
    sys.exit(main())
