#!/bin/bash
# Debug script to test if poller script can execute

echo "=========================================="
echo "POLLER DEBUG TEST"
echo "=========================================="
echo "Working directory: $(pwd)"
echo "Python version: $(python --version)"
echo "Python path: $(which python)"
echo ""
echo "Checking if cap_poller.py exists:"
ls -lh poller/cap_poller.py || echo "FILE NOT FOUND!"
echo ""
echo "Attempting to run Python syntax check:"
python -m py_compile poller/cap_poller.py && echo "✅ Syntax OK" || echo "❌ Syntax error!"
echo ""
echo "Attempting to run cap_poller.py with python -v (verbose import):"
python -v poller/cap_poller.py --help 2>&1 | head -50
echo ""
echo "=========================================="
echo "END DEBUG TEST"
echo "=========================================="
