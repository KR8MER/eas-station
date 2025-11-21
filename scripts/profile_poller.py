#!/usr/bin/env python3
"""
Systematic profiler for cap_poller.py to identify CPU hotspots.

This script instruments the poller with timing measurements to identify
exactly where CPU time is being spent.
"""
import sys
import os
import time
import cProfile
import pstats
from io import StringIO

# Add project root to path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

# Set minimal environment for testing
os.environ['DATABASE_URL'] = os.getenv('DATABASE_URL', 'postgresql://postgres:postgres@localhost:5432/alerts')
os.environ['CAP_POLLER_DEBUG_RECORDS'] = '0'  # Ensure debug records are disabled

def profile_single_poll():
    """Profile a single poll cycle to see where time is spent."""
    from poller.cap_poller import CAPPoller
    
    print("=" * 80)
    print("PROFILING SINGLE POLL CYCLE")
    print("=" * 80)
    
    try:
        poller = CAPPoller(
            database_url=os.environ['DATABASE_URL'],
            led_sign_ip=None,
            enable_radio_captures=False
        )
        
        # Profile the poll_and_process method
        profiler = cProfile.Profile()
        profiler.enable()
        
        start_time = time.time()
        stats = poller.poll_and_process()
        elapsed = time.time() - start_time
        
        profiler.disable()
        
        print(f"\n✓ Poll completed in {elapsed:.3f} seconds")
        print(f"  Status: {stats.get('status')}")
        print(f"  Alerts fetched: {stats.get('alerts_fetched', 0)}")
        print(f"  Alerts accepted: {stats.get('alerts_accepted', 0)}")
        print(f"  Execution time (reported): {stats.get('execution_time_ms', 0)}ms")
        
        # Analyze profile results
        print("\n" + "=" * 80)
        print("TOP 20 FUNCTIONS BY CUMULATIVE TIME")
        print("=" * 80)
        
        s = StringIO()
        ps = pstats.Stats(profiler, stream=s)
        ps.strip_dirs()
        ps.sort_stats('cumulative')
        ps.print_stats(20)
        print(s.getvalue())
        
        print("\n" + "=" * 80)
        print("TOP 20 FUNCTIONS BY TOTAL TIME (SELF)")
        print("=" * 80)
        
        s = StringIO()
        ps = pstats.Stats(profiler, stream=s)
        ps.strip_dirs()
        ps.sort_stats('tottime')
        ps.print_stats(20)
        print(s.getvalue())
        
        poller.close()
        
        return elapsed
        
    except Exception as e:
        print(f"\n✗ Error during profiling: {e}")
        import traceback
        traceback.print_exc()
        return None

def check_for_loops():
    """Check for any tight loops or busy-wait patterns in the code."""
    print("\n" + "=" * 80)
    print("CHECKING FOR POTENTIAL INFINITE LOOPS")
    print("=" * 80)
    
    import subprocess
    
    # Check for while True without sleep
    result = subprocess.run(
        ['grep', '-n', 'while', os.path.join(project_root, 'poller', 'cap_poller.py')],
        capture_output=True,
        text=True
    )
    
    if result.stdout:
        print("\nFound 'while' statements:")
        for line in result.stdout.strip().split('\n'):
            print(f"  {line}")
    
    # Check for tight for loops
    result = subprocess.run(
        ['grep', '-n', 'for.*in.*range', os.path.join(project_root, 'poller', 'cap_poller.py')],
        capture_output=True,
        text=True
    )
    
    if result.stdout:
        print("\nFound 'for...range' loops:")
        for line in result.stdout.strip().split('\n'):
            if line.strip():
                print(f"  {line}")

def analyze_imports():
    """Check if any imports might be causing CPU usage on module load."""
    print("\n" + "=" * 80)
    print("ANALYZING MODULE IMPORTS")
    print("=" * 80)
    
    start = time.time()
    
    # Time each major import
    imports_to_test = [
        ('requests', 'import requests'),
        ('sqlalchemy', 'from sqlalchemy import create_engine'),
        ('geoalchemy2', 'from geoalchemy2 import Geometry'),
        ('shapely', 'from shapely.geometry import shape'),
    ]
    
    for name, import_stmt in imports_to_test:
        try:
            import_start = time.time()
            exec(import_stmt)
            import_time = time.time() - import_start
            print(f"  {name}: {import_time*1000:.1f}ms")
        except Exception as e:
            print(f"  {name}: Failed - {e}")
    
    total_time = time.time() - start
    print(f"\nTotal import time: {total_time*1000:.1f}ms")

if __name__ == '__main__':
    print("Cap Poller Systematic CPU Profiler")
    print("=" * 80)
    
    # Step 1: Analyze imports
    analyze_imports()
    
    # Step 2: Check for loops
    check_for_loops()
    
    # Step 3: Profile actual execution
    print("\n\nNOTE: This will attempt to connect to the database.")
    print("Make sure DATABASE_URL is set correctly.")
    input("Press Enter to continue with profiling, or Ctrl+C to abort...")
    
    elapsed = profile_single_poll()
    
    if elapsed:
        print("\n" + "=" * 80)
        print("ANALYSIS SUMMARY")
        print("=" * 80)
        print(f"Single poll took {elapsed:.3f} seconds")
        print(f"At 180s interval, CPU usage per cycle: {elapsed/180*100:.1f}%")
        print("\nIf CPU is constantly high, check:")
        print("  1. The TOP 20 functions above - are any taking excessive time?")
        print("  2. Database queries - are any slow or blocking?")
        print("  3. Network requests - are any timing out or slow?")
        print("  4. Any functions called repeatedly in a loop?")
