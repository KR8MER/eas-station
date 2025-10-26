#!/bin/bash
# Simple script to check API endpoints.

set -euo pipefail

API_BASE_URL=${API_BASE_URL:-http://app:5000}

printf "Checking endpoints on %s\n" "$API_BASE_URL"

curl -s -o /dev/null -w "HTTP Status: %{http_code}\n" "$API_BASE_URL/api/system_status"
curl -s -o /dev/null -w "HTTP Status: %{http_code}\n" "$API_BASE_URL/api/alerts"
curl -s -o /dev/null -w "HTTP Status: %{http_code}\n" "$API_BASE_URL/api/boundaries"

echo "\nSample output for debugging:"

curl -s "$API_BASE_URL/api/system_status" | python3 -m json.tool 2>/dev/null || echo "Not valid JSON or error"
curl -s "$API_BASE_URL/api/alerts" | python3 -m json.tool 2>/dev/null || echo "Not valid JSON or error"
curl -s "$API_BASE_URL/api/boundaries" | python3 -m json.tool 2>/dev/null || echo "Not valid JSON or error"
