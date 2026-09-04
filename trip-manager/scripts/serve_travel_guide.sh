#!/usr/bin/env bash
# serve_travel_guide.sh - 在 http://localhost:8765 启动 travel-guide 静态服务
cd "$(dirname "$0")" || exit 1

PORT=${PORT:-8765}
echo "🚀 Travel Guide 服务器: http://localhost:$PORT/"
echo "📂 目录: $(pwd)"
echo "🛑 停止: Ctrl+C"

python3 -m http.server "$PORT"