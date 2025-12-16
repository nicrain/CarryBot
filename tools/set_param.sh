#!/usr/bin/env bash
# Simple helper to POST parameters to param server
# Usage examples:
#   # Local test (use 127.0.0.1 to target local server):
#   SERVER=127.0.0.1 ./tools/set_param.sh '{"wall_dist_th": 1.2}'
#
#   # Target a specific robot on LAN (default server is 127.0.0.1):
#   SERVER=192.168.10.212 ./tools/set_param.sh '{"roi_h_start": 0.3}'
#
# The script defaults to SERVER=127.0.0.1 and PORT=8080.

if [ -z "$1" ]; then
  echo "Usage: $0 '{\"parameter_name\": value}'"
  echo "Example: $0 '{\"roi_h_start\": 0.3, \"wall_dist_th\": 1.0}'"
  exit 1
fi

# 默认服务器地址（可通过 SERVER 环境变量覆盖）
SERVER=${SERVER:-127.0.0.1}
PORT=${PORT:-8080}

echo "Sending params to http://${SERVER}:${PORT}/params..."
curl -s -X POST http://${SERVER}:${PORT}/params -H 'Content-Type: application/json' -d "$1" -w '\n'
