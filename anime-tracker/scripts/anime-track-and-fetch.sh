#!/usr/bin/env bash
# Hermes cron job: 每天凌晨 2:30 跑一次
# 读取 ~/.config/anime-tracker/watchlist.yaml
# Bangumi 判定连载中 → DMHY 搜磁力 → aria2 RPC 提交
# 日志保存到 ~/.cache/anime-tracker/

set -e

LOG_DIR="$HOME/.cache/anime-tracker"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/last-run.log"

# 代理免疫：系统代理端口不可达时清空代理变量（避免 Connection refused）
source "$HOME/.hermes/scripts/proxy_guard.sh"

echo "=== anime-tracker @ $(date '+%Y-%m-%d %H:%M:%S') ===" | tee "$LOG_FILE"

python3 ~/.hermes/skills/anime-tracker/scripts/anime-tracker.py 2>&1 | tee -a "$LOG_FILE"

echo "" | tee -a "$LOG_FILE"
echo "=== aria2 任务统计 ===" | tee -a "$LOG_FILE"
curl -s -X POST http://localhost:6800/jsonrpc \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"aria2.getGlobalStat","params":["token:hermes_rpc_2026"]}' \
  | tee -a "$LOG_FILE"
echo "" | tee -a "$LOG_FILE"

echo "=== END @ $(date '+%Y-%m-%d %H:%M:%S') ===" | tee -a "$LOG_FILE"