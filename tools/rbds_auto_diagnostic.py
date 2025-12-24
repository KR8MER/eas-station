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
RBDS Automatic Diagnostic Tool

After 35+ pull requests fixing RBDS issues, this script automatically detects
common problems with the RBDS demodulation implementation.

This should have been created much earlier to catch issues before they hit production.

Usage:
    python3 tools/rbds_auto_diagnostic.py                    # Check code
    python3 tools/rbds_auto_diagnostic.py --logs <file>      # Analyze logs
    python3 tools/rbds_auto_diagnostic.py --live             # Monitor live logs
    python3 tools/rbds_auto_diagnostic.py --all              # Run all checks

Categories of checks:
1. DSP Processing Order - M&M must come before Costas
2. Differential Decoding - Must use modulo formula, not !=
3. Bit Buffer Management - Must use index-based, not pop(0)
4. Register Handling - Must reset after processing blocks
5. Polarity Handling - Must check both normal and inverted
6. CRC Logic - Must match python-radio reference
7. Presync Spacing - Must retain blocks on mismatch
8. Common Anti-Patterns - Various bugs from 35+ PRs
"""

import argparse
import re
import sys
from pathlib import Path
from typing import List, Dict, Tuple, Optional
from dataclasses import dataclass
from enum import Enum


class Severity(Enum):
    """Severity levels for diagnostic findings."""
    CRITICAL = "🔴 CRITICAL"
    ERROR = "🟠 ERROR"
    WARNING = "🟡 WARNING"
    INFO = "🟢 INFO"
    PASS = "✅ PASS"


@dataclass
class Finding:
    """A diagnostic finding."""
    category: str
    severity: Severity
    issue: str
    line_num: Optional[int] = None
    code_snippet: Optional[str] = None
    fix: Optional[str] = None
    reference: Optional[str] = None


class RBDSDiagnostic:
    """Automatic RBDS diagnostic tool."""
    
    def __init__(self, demod_file: Path):
        """Initialize diagnostic with path to demodulation.py."""
        self.demod_file = demod_file
        self.findings: List[Finding] = []
        self.code_lines: List[str] = []
        
        if demod_file.exists():
            with open(demod_file, 'r') as f:
                self.code_lines = f.readlines()
    
    def run_all_checks(self) -> List[Finding]:
        """Run all diagnostic checks."""
        print("=" * 80)
        print("RBDS AUTOMATIC DIAGNOSTIC - Analyzing Implementation")
        print("=" * 80)
        print()
        
        if not self.code_lines:
            self.findings.append(Finding(
                category="File Access",
                severity=Severity.CRITICAL,
                issue=f"Cannot read {self.demod_file}",
                fix="Ensure demodulation.py exists and is readable"
            ))
            return self.findings
        
        # Run all checks
        self.check_dsp_processing_order()
        self.check_differential_decoding()
        self.check_bit_buffer_management()
        self.check_register_reset()
        self.check_polarity_handling()
        self.check_crc_logic()
        self.check_presync_spacing()
        self.check_common_antipatterns()
        
        return self.findings
    
    def check_dsp_processing_order(self):
        """Check that M&M timing recovery comes before Costas phase correction.
        
        Issue: v2.44.9 swapped order (Costas → M&M) which broke symbol detection.
        Fix: v2.44.11 restored correct order (M&M → Costas → BPSK).
        Reference: PySDR standard, python-radio reference.
        """
        print("1. Checking DSP Processing Order...")
        
        # Find the RBDS processing section
        mm_line = None
        costas_line = None
        bpsk_line = None
        
        for i, line in enumerate(self.code_lines):
            if "M&M" in line or "Mueller" in line or "timing" in line.lower():
                if "# Step" in line or "_mm_timing" in line:
                    if mm_line is None:
                        mm_line = i
            
            if "Costas" in line or "phase" in line.lower():
                if "# Step" in line or "_costas" in line:
                    if costas_line is None and mm_line is not None:
                        costas_line = i
            
            if "BPSK" in line and "demod" in line.lower():
                if "# Step" in line or "bits_raw" in line:
                    if bpsk_line is None and costas_line is not None:
                        bpsk_line = i
        
        # Check order
        if mm_line and costas_line and bpsk_line:
            if mm_line < costas_line < bpsk_line:
                self.findings.append(Finding(
                    category="DSP Processing Order",
                    severity=Severity.PASS,
                    issue="Correct order: M&M → Costas → BPSK",
                    line_num=mm_line,
                    reference="PySDR standard, fixes v2.44.11"
                ))
            else:
                self.findings.append(Finding(
                    category="DSP Processing Order",
                    severity=Severity.CRITICAL,
                    issue=f"WRONG ORDER: M&M at line {mm_line}, Costas at {costas_line}, BPSK at {bpsk_line}",
                    fix="M&M must come BEFORE Costas. Costas distorts symbol transitions needed by M&M.",
                    reference="v2.44.9 experimental swap broke this"
                ))
        else:
            self.findings.append(Finding(
                category="DSP Processing Order",
                severity=Severity.WARNING,
                issue="Could not locate DSP processing steps",
                fix="Ensure M&M, Costas, and BPSK steps are clearly marked"
            ))
        
        # Check for experimental comments
        for i, line in enumerate(self.code_lines):
            if "experimental" in line.lower() and "rbds" in line.lower():
                self.findings.append(Finding(
                    category="DSP Processing Order",
                    severity=Severity.WARNING,
                    issue="Experimental code still present",
                    line_num=i + 1,
                    code_snippet=line.strip(),
                    fix="Remove experimental code or clearly document why it's needed"
                ))
        
        print(f"   Found {len([f for f in self.findings if f.category == 'DSP Processing Order'])} issues")
        print()
    
    def check_differential_decoding(self):
        """Check differential decoding formula.
        
        Issue: Used != operator which doesn't handle phase ambiguity correctly.
        Fix: v2.44.10 changed to modulo arithmetic: (bits[1:] - bits[0:-1]) % 2
        Reference: python-radio decoder.py line 210
        """
        print("2. Checking Differential Decoding Formula...")
        
        found_correct = False
        found_wrong = False
        
        for i, line in enumerate(self.code_lines):
            # Look for differential decoding
            if "!=" in line and ("symbol" in line or "bits" in line):
                if "diff" in line or "differential" in self.code_lines[max(0, i-5):i+1]:
                    found_wrong = True
                    self.findings.append(Finding(
                        category="Differential Decoding",
                        severity=Severity.CRITICAL,
                        issue="Using != operator for differential decoding",
                        line_num=i + 1,
                        code_snippet=line.strip(),
                        fix="Change to: diff = (all_symbols[1:] - all_symbols[:-1]) % 2",
                        reference="python-radio decoder.py:210, v2.44.10 fix"
                    ))
            
            if "% 2" in line and ("-" in line or "subtract" in line.lower()):
                if "diff" in line or "all_symbols" in line:
                    found_correct = True
                    # Check for python-radio reference
                    has_reference = False
                    for j in range(max(0, i-10), min(len(self.code_lines), i+3)):
                        if "python-radio" in self.code_lines[j]:
                            has_reference = True
                            break
                    
                    self.findings.append(Finding(
                        category="Differential Decoding",
                        severity=Severity.PASS,
                        issue="Correct modulo arithmetic formula",
                        line_num=i + 1,
                        reference="python-radio reference " + ("found" if has_reference else "MISSING")
                    ))
        
        if not found_correct and not found_wrong:
            self.findings.append(Finding(
                category="Differential Decoding",
                severity=Severity.ERROR,
                issue="Could not locate differential decoding code",
                fix="Ensure differential decoding is implemented"
            ))
        
        print(f"   Found {len([f for f in self.findings if f.category == 'Differential Decoding'])} issues")
        print()
    
    def check_bit_buffer_management(self):
        """Check bit buffer management strategy.
        
        Issue: Using pop(0) discards bits needed for presync retries.
        Fix: v2.43.8 and later use index-based processing.
        """
        print("3. Checking Bit Buffer Management...")
        
        uses_pop = False
        uses_index = False
        
        for i, line in enumerate(self.code_lines):
            if "rbds" in line.lower() or "bit" in line.lower():
                if ".pop(0)" in line:
                    uses_pop = True
                    self.findings.append(Finding(
                        category="Bit Buffer Management",
                        severity=Severity.CRITICAL,
                        issue="Using pop(0) loses bits on presync retry",
                        line_num=i + 1,
                        code_snippet=line.strip(),
                        fix="Use index-based processing: self._rbds_buffer_index",
                        reference="v2.43.8 presync fix"
                    ))
                
                if "_rbds_buffer_index" in line:
                    uses_index = True
        
        if uses_index and not uses_pop:
            self.findings.append(Finding(
                category="Bit Buffer Management",
                severity=Severity.PASS,
                issue="Using index-based buffer processing",
                reference="Preserves bits for presync retry"
            ))
        elif not uses_index:
            self.findings.append(Finding(
                category="Bit Buffer Management",
                severity=Severity.WARNING,
                issue="Could not verify buffer management strategy",
                fix="Should use index-based processing (_rbds_buffer_index)"
            ))
        
        print(f"   Found {len([f for f in self.findings if f.category == 'Bit Buffer Management'])} issues")
        print()
    
    def check_register_reset(self):
        """Check that register is reset after processing blocks in synced mode.
        
        Issue: v2.44.7 and earlier didn't reset register, causing bits from previous
               block to contaminate next block → 100% CRC failures.
        Fix: v2.44.8 added _rbds_reg = 0 after processing each block.
        """
        print("4. Checking Register Reset After Block Processing...")
        
        found_resets = []
        in_synced_block = False
        
        for i, line in enumerate(self.code_lines):
            # Track if we're in synced block processing
            if "SYNCED:" in line or "synced mode" in line.lower():
                in_synced_block = True
            
            if in_synced_block:
                # Look for block processing completion
                if "store" in line.lower() or "group_data" in line:
                    # Check next 10 lines for register reset
                    for j in range(i, min(len(self.code_lines), i + 10)):
                        if "_rbds_reg = 0" in self.code_lines[j]:
                            found_resets.append(j + 1)
                            break
        
        if found_resets:
            self.findings.append(Finding(
                category="Register Reset",
                severity=Severity.PASS,
                issue=f"Register reset found at {len(found_resets)} location(s)",
                line_num=found_resets[0],
                reference="v2.44.8 fix for 100% CRC failures"
            ))
        else:
            self.findings.append(Finding(
                category="Register Reset",
                severity=Severity.CRITICAL,
                issue="No register reset after block processing",
                fix="Add _rbds_reg = 0 after storing each block in synced mode",
                reference="v2.44.8 fix - prevents bit contamination between blocks"
            ))
        
        print(f"   Found {len([f for f in self.findings if f.category == 'Register Reset'])} issues")
        print()
    
    def check_polarity_handling(self):
        """Check that both normal and inverted polarity are handled.
        
        Issue: Costas loop can lock with 180° phase ambiguity, need to check both.
        Fix: All recent versions check both polarities.
        """
        print("5. Checking Polarity Handling...")
        
        checks_inverted = False
        checks_normal = False
        
        for i, line in enumerate(self.code_lines):
            if "rbds" in line.lower():
                if "invert" in line.lower() or "^ 0x3FFFFFF" in line:
                    checks_inverted = True
                
                if "normal" in line.lower() and "polarity" in line.lower():
                    checks_normal = True
        
        if checks_inverted and checks_normal:
            self.findings.append(Finding(
                category="Polarity Handling",
                severity=Severity.PASS,
                issue="Checks both normal and inverted polarity",
                reference="Handles Costas 180° phase ambiguity"
            ))
        elif not checks_inverted:
            self.findings.append(Finding(
                category="Polarity Handling",
                severity=Severity.ERROR,
                issue="Does not check inverted polarity",
                fix="Must check both normal and inverted (XOR with 0x3FFFFFF)",
                reference="Costas loop can lock either way"
            ))
        
        print(f"   Found {len([f for f in self.findings if f.category == 'Polarity Handling'])} issues")
        print()
    
    def check_crc_logic(self):
        """Check CRC calculation and verification logic.
        
        Issue: Various CRC bugs in 30+ PRs.
        Fix: Must match python-radio reference exactly.
        """
        print("6. Checking CRC Logic...")
        
        has_calc_syndrome = False
        syndrome_lines = []
        
        for i, line in enumerate(self.code_lines):
            if "_calc_syndrome" in line:
                has_calc_syndrome = True
                syndrome_lines.append(i + 1)
        
        if has_calc_syndrome:
            self.findings.append(Finding(
                category="CRC Logic",
                severity=Severity.PASS,
                issue=f"CRC calculation function exists ({len(syndrome_lines)} uses)",
                reference="Ensure it matches python-radio polynomial"
            ))
        else:
            self.findings.append(Finding(
                category="CRC Logic",
                severity=Severity.CRITICAL,
                issue="No CRC calculation function found",
                fix="Implement _calc_syndrome() matching python-radio",
                reference="python-radio decoder.py"
            ))
        
        # Check for offset words
        has_offset_words = False
        for i, line in enumerate(self.code_lines):
            if "offset_word" in line and "[252, 408, 360, 436, 848]" in line:
                has_offset_words = True
                self.findings.append(Finding(
                    category="CRC Logic",
                    severity=Severity.PASS,
                    issue="Correct offset words defined",
                    line_num=i + 1,
                    reference="python-radio standard"
                ))
                break
        
        if not has_offset_words:
            self.findings.append(Finding(
                category="CRC Logic",
                severity=Severity.ERROR,
                issue="Offset words not found or incorrect",
                fix="Must use: [252, 408, 360, 436, 848] for A, B, C, D, C'",
                reference="python-radio reference"
            ))
        
        print(f"   Found {len([f for f in self.findings if f.category == 'CRC Logic'])} issues")
        print()
    
    def check_presync_spacing(self):
        """Check presync spacing mismatch handling.
        
        Issue: v2.43.7 and earlier discarded current block on spacing mismatch.
        Fix: v2.43.8 retains current block as new first block candidate.
        """
        print("7. Checking Presync Spacing Logic...")
        
        handles_spacing_correctly = False
        
        for i, line in enumerate(self.code_lines):
            if "spacing" in line.lower() and "mismatch" in line.lower():
                # Check next 10 lines for correct handling
                for j in range(i, min(len(self.code_lines), i + 10)):
                    if "_rbds_lastseen_offset = j" in self.code_lines[j] or "self._rbds_lastseen_offset = j" in self.code_lines[j]:
                        handles_spacing_correctly = True
                        self.findings.append(Finding(
                            category="Presync Spacing",
                            severity=Severity.PASS,
                            issue="Correctly retains block on spacing mismatch",
                            line_num=j + 1,
                            reference="v2.43.8 presync fix"
                        ))
                        break
                
                if not handles_spacing_correctly:
                    # Check if it wrongly resets presync
                    for j in range(i, min(len(self.code_lines), i + 10)):
                        if "_rbds_presync = False" in self.code_lines[j]:
                            self.findings.append(Finding(
                                category="Presync Spacing",
                                severity=Severity.CRITICAL,
                                issue="Discards block on spacing mismatch (resets presync)",
                                line_num=j + 1,
                                fix="Should retain current block: _rbds_lastseen_offset = j",
                                reference="v2.43.8 presync fix"
                            ))
                            break
        
        if not handles_spacing_correctly:
            self.findings.append(Finding(
                category="Presync Spacing",
                severity=Severity.WARNING,
                issue="Could not verify presync spacing logic",
                fix="Ensure spacing mismatches retain current block as new candidate"
            ))
        
        print(f"   Found {len([f for f in self.findings if f.category == 'Presync Spacing'])} issues")
        print()
    
    def check_common_antipatterns(self):
        """Check for common anti-patterns from 35+ PRs."""
        print("8. Checking Common Anti-Patterns...")
        
        antipatterns = [
            (r"logger\.getLogger\(__name__\)", "Creating new logger instance", 
             "Use existing logger from module scope"),
            
            (r"except\s*:", "Bare except clause",
             "Catch specific exceptions"),
            
            (r"#.*TODO.*RBDS", "TODO comments in RBDS code",
             "Should be resolved before merging"),
            
            (r"#.*FIXME.*RBDS", "FIXME comments in RBDS code",
             "Should be resolved before merging"),
            
            (r"#.*HACK.*RBDS", "HACK comments in RBDS code",
             "Find proper solution"),
            
            (r"time\.sleep.*#.*RBDS", "Sleep in RBDS processing",
             "Blocks audio processing - remove or move to worker thread"),
        ]
        
        for i, line in enumerate(self.code_lines):
            for pattern, issue, fix in antipatterns:
                if re.search(pattern, line, re.IGNORECASE):
                    self.findings.append(Finding(
                        category="Anti-Patterns",
                        severity=Severity.WARNING,
                        issue=issue,
                        line_num=i + 1,
                        code_snippet=line.strip(),
                        fix=fix
                    ))
        
        print(f"   Found {len([f for f in self.findings if f.category == 'Anti-Patterns'])} issues")
        print()
    
    def print_summary(self):
        """Print summary of findings."""
        print()
        print("=" * 80)
        print("DIAGNOSTIC SUMMARY")
        print("=" * 80)
        print()
        
        # Count by severity
        counts = {
            Severity.CRITICAL: 0,
            Severity.ERROR: 0,
            Severity.WARNING: 0,
            Severity.INFO: 0,
            Severity.PASS: 0
        }
        
        for finding in self.findings:
            counts[finding.severity] += 1
        
        print(f"Total Findings: {len(self.findings)}")
        print(f"  {Severity.CRITICAL.value}: {counts[Severity.CRITICAL]}")
        print(f"  {Severity.ERROR.value}: {counts[Severity.ERROR]}")
        print(f"  {Severity.WARNING.value}: {counts[Severity.WARNING]}")
        print(f"  {Severity.INFO.value}: {counts[Severity.INFO]}")
        print(f"  {Severity.PASS.value}: {counts[Severity.PASS]}")
        print()
        
        # Print detailed findings by category
        categories = {}
        for finding in self.findings:
            if finding.category not in categories:
                categories[finding.category] = []
            categories[finding.category].append(finding)
        
        for category, findings in sorted(categories.items()):
            print(f"\n{category}:")
            print("-" * 80)
            for finding in findings:
                print(f"\n  {finding.severity.value}")
                print(f"  Issue: {finding.issue}")
                if finding.line_num:
                    print(f"  Line: {finding.line_num}")
                if finding.code_snippet:
                    print(f"  Code: {finding.code_snippet}")
                if finding.fix:
                    print(f"  Fix: {finding.fix}")
                if finding.reference:
                    print(f"  Reference: {finding.reference}")
        
        print()
        print("=" * 80)
        
        # Return exit code based on severity
        if counts[Severity.CRITICAL] > 0:
            print("❌ CRITICAL issues found - RBDS will NOT work")
            return 2
        elif counts[Severity.ERROR] > 0:
            print("⚠️  ERROR issues found - RBDS may not work correctly")
            return 1
        elif counts[Severity.WARNING] > 0:
            print("⚠️  WARNING issues found - review recommended")
            return 0
        else:
            print("✅ All checks passed - RBDS implementation looks good")
            return 0


def analyze_logs(log_file: Optional[Path] = None):
    """Analyze RBDS logs for runtime issues."""
    print("=" * 80)
    print("RBDS LOG ANALYSIS")
    print("=" * 80)
    print()
    
    if log_file:
        try:
            with open(log_file, 'r') as f:
                lines = f.readlines()
        except Exception as e:
            print(f"Error reading log file: {e}")
            return 1
    else:
        # Read from stdin
        print("Reading from stdin (paste logs or pipe from journalctl)...")
        print("Press Ctrl+D when done.")
        print()
        lines = sys.stdin.readlines()
    
    # Analyze patterns
    sync_achieved = 0
    sync_lost = 0
    groups_decoded = 0
    crc_fails = 0
    presync_attempts = 0
    
    for line in lines:
        if "RBDS SYNCHRONIZED" in line:
            sync_achieved += 1
        if "RBDS SYNC LOST" in line:
            sync_lost += 1
        if "RBDS group:" in line:
            groups_decoded += 1
        if "FAILED CRC" in line:
            crc_fails += 1
        if "RBDS presync:" in line:
            presync_attempts += 1
    
    print(f"Synchronization Events: {sync_achieved}")
    print(f"Sync Lost Events: {sync_lost}")
    print(f"Groups Decoded: {groups_decoded}")
    print(f"CRC Failures: {crc_fails}")
    print(f"Presync Attempts: {presync_attempts}")
    print()
    
    # Diagnosis
    if sync_achieved == 0:
        print("❌ PROBLEM: Never achieved synchronization")
        print("   Possible causes:")
        print("   - DSP processing order wrong (M&M must be before Costas)")
        print("   - Differential decoding formula wrong")
        print("   - No RBDS signal present")
        print("   - Signal too weak")
        return 1
    
    if sync_achieved > 0 and groups_decoded == 0:
        print("❌ PROBLEM: Synchronized but no groups decoded")
        print("   Possible causes:")
        print("   - Register not reset after block processing")
        print("   - CRC logic incorrect")
        print("   - Polarity not handled correctly")
        return 1
    
    if sync_lost > sync_achieved * 2:
        print("⚠️  WARNING: Frequent sync loss")
        print("   Possible causes:")
        print("   - Weak signal")
        print("   - Presync spacing logic discarding blocks")
        print("   - Register corruption")
        return 0
    
    if groups_decoded > 0:
        print("✅ GOOD: Successfully decoding RBDS groups")
        if crc_fails > groups_decoded * 10:
            print("⚠️  High CRC failure rate - signal quality may be poor")
        return 0
    
    return 0


def main():
    parser = argparse.ArgumentParser(
        description="RBDS Automatic Diagnostic Tool - Should have existed from the start!",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Check code implementation
  python3 tools/rbds_auto_diagnostic.py
  
  # Analyze log file
  python3 tools/rbds_auto_diagnostic.py --logs /var/log/rbds.log
  
  # Analyze live logs
  journalctl -u eas-station-audio.service -n 1000 | python3 tools/rbds_auto_diagnostic.py --logs -
  
  # Run all checks
  python3 tools/rbds_auto_diagnostic.py --all
        """
    )
    
    parser.add_argument(
        '--logs',
        type=str,
        metavar='FILE',
        help='Analyze log file (use - for stdin)'
    )
    
    parser.add_argument(
        '--all',
        action='store_true',
        help='Run both code and log analysis'
    )
    
    parser.add_argument(
        '--demod-file',
        type=Path,
        default=Path(__file__).parent.parent / 'app_core' / 'radio' / 'demodulation.py',
        help='Path to demodulation.py (default: auto-detect)'
    )
    
    args = parser.parse_args()
    
    exit_code = 0
    
    # Run code analysis
    if not args.logs or args.all:
        diag = RBDSDiagnostic(args.demod_file)
        diag.run_all_checks()
        code_exit = diag.print_summary()
        exit_code = max(exit_code, code_exit)
    
    # Run log analysis
    if args.logs or args.all:
        if args.logs and args.logs != '-':
            log_exit = analyze_logs(Path(args.logs))
        else:
            log_exit = analyze_logs(None)
        exit_code = max(exit_code, log_exit)
    
    return exit_code


if __name__ == '__main__':
    sys.exit(main())
