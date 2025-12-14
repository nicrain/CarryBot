#!/usr/bin/env bash
# Simple helper to POST parameters to param server
# Usage examples:
#   # Local test (use 127.0.0.1 to target local server):
#   SERVER=127.0.0.1 ./tools/set_param.sh '{"EDGE_THRESH":150}'
#
#   # Target a specific robot on LAN (default server is 0.0.0.0 for wide binding):
#   SERVER=192.168.10.212 ./tools/set_param.sh '{"EDGE_THRESH":150}'
#
# The script defaults to SERVER=0.0.0.0 and PORT=8000 but it's recommended to
# override SERVER with the actual reachable IP when invoking from another host.

if [ -z "$1" ]; then
  echo "Usage: $0 '{\"EDGE_THRESH\":150}'"
  exit 1
fi

# 默认服务器地址（可通过 SERVER 环境变量覆盖）
SERVER=${SERVER:-0.0.0.0}
PORT=${PORT:-8000}

curl -s -X POST http://${SERVER}:${PORT}/params -H 'Content-Type: application/json' -d "$1" -w '\n'