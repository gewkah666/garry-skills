# trip-manager · cron 蓝图（M-2）

| 名字 | 时间 | 形式 | 入口 |
|---|---|---|---|
| `trip-archive-yesterday` | `0 7 * * *` | no-agent 脚本 | `~/.hermes/scripts/trip_archive.sh` → `_skill_cron.sh` → `scripts/trip_archive.sh` |

做什么：把昨天的 Outlook 行程（Graph，device-code 缓存 token `~/.cache/trip-manager/ms_token.json`）归档到 Notion。需要 `~/.hermes/trip-env.sh` 里的 `MS_GRAPH_CLIENT_ID`；token 过期要手动 `outlook_event.py list` 登一次。
重建：`hermes cron create --name trip-archive-yesterday --script trip_archive.sh --no-agent --deliver local "0 7 * * *"`
其他入口：`~/.hermes/scripts/amap_mcp.sh` 包装 → `scripts/amap_mcp.sh`（高德 MCP）；`scripts/serve_travel_guide.sh` 本地预览攻略。
每次运行在 Phantom 事件库留一条 `cron:trip-archive`。
