#!/usr/bin/env bash
# serve_travel_guide.sh - 本地预览行程地图 / 手机行程模式（server.py 的薄包装）
# 用法: serve_travel_guide.sh [端口]   默认 8899；手机在同一 Wi-Fi 打开打印出的局域网地址
cd "$(dirname "$0")" || exit 1
[ -f "$HOME/.hermes/trip-env.sh" ] && source "$HOME/.hermes/trip-env.sh"
exec python3 server.py --port "${1:-${PORT:-8899}}"
