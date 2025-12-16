#!/usr/bin/env bash
# Test helper to exercise the HTTP params server
# Usage examples:
#   # Local test (targeting localhost):
#   SERVER=127.0.0.1 ./tools/test_server.sh
#
#   # Target a specific robot on LAN:
#   SERVER=192.168.10.212 ./tools/test_server.sh
#
# The script defaults to SERVER=127.0.0.1 and PORT=8080.

set -e

SERVER=${SERVER:-127.0.0.1}
PORT=${PORT:-8080}

echo "=== 1. Testing GET /params ==="
curl -s http://${SERVER}:${PORT}/params | python -m json.tool || echo "Failed to connect"

echo ""
echo "=== 2. Testing POST update (roi_h_start -> 0.25) ==="
curl -s -X POST http://${SERVER}:${PORT}/params -H 'Content-Type: application/json' -d '{"roi_h_start": 0.25}' | python -m json.tool || echo "Failed to post"

echo ""
echo "=== 3. Testing GET /params after change ==="
curl -s http://${SERVER}:${PORT}/params | python -m json.tool

echo ""
echo "=== 4. Checking local config.json file (if it exists) ==="
if [ -f config.json ]; then
    cat config.json
else
    echo "config.json not found in current directory."
fi
