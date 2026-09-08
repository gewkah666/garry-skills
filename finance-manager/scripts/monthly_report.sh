#!/usr/bin/env bash
# cron 入口（每月 1 号 08:00）：上月财务月报 → dashboards + 阅览世界 + 飞书。
# 经 ~/.hermes/scripts/finance-monthly-report.sh → _skill_cron.sh 调用；也可手动: scripts/monthly_report.sh 2026-08
set -e
MONTH="${1:-last}"
LOG_DIR="$HOME/.cache/finance-manager"; mkdir -p "$LOG_DIR"
[ -f "$HOME/.hermes/scripts/proxy_guard.sh" ] && source "$HOME/.hermes/scripts/proxy_guard.sh"
OUT=$("$HOME/.hermes/hermes-agent/venv/bin/python" "$(dirname "$0")/finance_cli.py" report --month "$MONTH" 2>>"$LOG_DIR/monthly.log")
echo "$OUT" >> "$LOG_DIR/monthly.log"
# 最后一行给 _skill_cron.sh 写进 Phantom 事件库
"$HOME/.hermes/hermes-agent/venv/bin/python" - "$OUT" <<'PY'
import json, sys
o = json.loads(sys.argv[1])
print(("已有 " if o.get("already") else "") + (o.get("summary") or "") + " " + (o.get("url") or ""))
PY
