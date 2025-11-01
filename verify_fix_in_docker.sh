#!/bin/bash
# Verify the fix is in the Docker container

CONTAINER="eas-station-app-1"

echo "Checking if fixes are in Docker container..."
echo ""

echo "1. Checking C_pattern (should have parity bit = 1):"
docker exec "$CONTAINER" grep "C_pattern = " app_utils/eas_decode.py
echo ""

echo "2. Checking for preamble skip code:"
docker exec "$CONTAINER" grep -A 2 "Skip the preamble" app_utils/eas_decode.py
echo ""

echo "3. Running actual decoder test:"
docker exec "$CONTAINER" python3 <<'EOF'
from app_utils.eas_decode import decode_same_audio

result = decode_same_audio('samples/malformed.wav')
if result.headers:
    print(f"Header: {result.headers[0].header}")
    if "03913715" in result.headers[0].header:
        print("STILL CORRUPTED!")
    else:
        print("FIXED!")
EOF
