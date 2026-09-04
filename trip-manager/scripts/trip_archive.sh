#!/usr/bin/env bash
# cron 入口: 每天 07:00 把昨天的 Outlook 行程归档到 Notion
set -e

SKILL_DIR="$HOME/.hermes/skills/garry-skills/trip-manager"
LOG_DIR="$HOME/.cache/anime-tracker"
mkdir -p "$LOG_DIR"

# 加载环境变量
if [ -f "$HOME/.hermes/trip-env.sh" ]; then
    source "$HOME/.hermes/trip-env.sh"
fi

# 代理免疫：系统代理端口不可达时清空代理变量（避免 Connection refused）
source "$HOME/.hermes/scripts/proxy_guard.sh"

# device_code 流只需要 MS_GRAPH_CLIENT_ID（不需要 secret/tenant）
# token 通过 device code 流程缓存到 ~/.cache/trip-manager/ms_token.json
if [ -z "$MS_GRAPH_CLIENT_ID" ]; then
    echo "[$(date '+%F %T')] ❌ MS_GRAPH_CLIENT_ID 未设置" >> "$LOG_DIR/trip-archive.log"
    exit 1
fi

# 强制清除 client_credentials 路径（MSA 必须走 device code）
unset MS_GRAPH_CLIENT_SECRET MS_GRAPH_TENANT_ID

# 检查 token 是否存在,不存在则报错（cron 不会触发交互登录）
if [ ! -f "$HOME/.cache/trip-manager/ms_token.json" ]; then
    echo "[$(date '+%F %T')] ❌ 未找到 cached token,请先手动运行 outlook_event.py list 登录一次" >> "$LOG_DIR/trip-archive.log"
    exit 1
fi

MS_GRAPH_CLIENT_ID="$MS_GRAPH_CLIENT_ID" python3 "$SKILL_DIR/scripts/notion_sync.py" archive-yesterday >> "$LOG_DIR/trip-archive.log" 2>&1