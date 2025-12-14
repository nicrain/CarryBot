#!/usr/bin/env bash
# Test script for params server
set -e

#!/usr/bin/env bash
# Test helper to exercise the HTTP params server
# Usage examples:
#   # Local test (targeting localhost):
#   SERVER=127.0.0.1 ./tools/test_server.sh
#
#   # Target a specific robot on LAN:
#   SERVER=192.168.10.212 ./tools/test_server.sh
#
# Note: The server binds to 0.0.0.0 by default (listening on all interfaces),
# but for local testing prefer SERVER=127.0.0.1 to ensure the request reaches
# the local loopback interface.

echo "GET /params"
SERVER=${SERVER:-0.0.0.0}
PORT=${PORT:-8000}
curl -s http://${SERVER}:${PORT}/params | python -m json.tool || true

echo "POST update EDGE_THRESH -> 180"
curl -s -X POST http://${SERVER}:${PORT}/params -H 'Content-Type: application/json' -d '{"EDGE_THRESH":180}' | python -m json.tool || true

echo "GET /params after change"
curl -s http://${SERVER}:${PORT}/params | python -m json.tool || true

echo "Check config.json"
cat config.json

echo "Check param_changes.log"
tail -n 5 param_changes.log || true