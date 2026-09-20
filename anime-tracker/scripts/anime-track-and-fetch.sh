#!/usr/bin/env bash
# Hermes cron job: 每天凌晨 2:30 跑一次
# 读取 ~/.config/anime-tracker/watchlist.yaml
# Bangumi 判定连载中 → DMHY 搜磁力 → NAS qBittorrent 提交（默认）
# 日志保存到 ~/.cache/anime-tracker/

set -e

LOG_DIR="$HOME/.cache/anime-tracker"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/last-run.log"

# 代理免疫：系统代理端口不可达时清空代理变量（避免 Connection refused）
source "$HOME/.hermes/scripts/proxy_guard.sh"

echo "=== anime-tracker @ $(date '+%Y-%m-%d %H:%M:%S') ===" | tee "$LOG_FILE"

python3 ~/.hermes/skills/anime-tracker/scripts/anime-tracker.py 2>&1 | tee -a "$LOG_FILE" || true

# === NAS qBittorrent 任务统计（Bearer 认证，凭据在 ~/.hermes/.env） ===
QB_HOST="$(grep -E '^QBT_UR[LY]=' "$HOME/.hermes/.env" | cut -d= -f2-)"
QB_BEARER="$(grep -E '^QBT_API_KE[XY]=' "$HOME/.hermes/.env" | cut -d= -f2-)"
echo "" | tee -a "$LOG_FILE"
echo "=== qb 任务统计 ===" | tee -a "$LOG_FILE"
curl -s -H "Authorization: Bearer $QB_BEARER" "$QB_HOST/api/v2/torrents/info?filter=downloading" \
  | python3 -c "
import json, sys
try:
    ts = json.load(sys.stdin)
except Exception:
    print('  (qb API 无响应)'); sys.exit(0)
if not ts:
    print('  (无进行中任务)')
for t in ts:
    print(f\"  {t['name'][:60]} {t['progress']*100:.0f}%\")
" | tee -a "$LOG_FILE"

echo "=== END @ $(date '+%Y-%m-%d %H:%M:%S') ===" | tee -a "$LOG_FILE"
