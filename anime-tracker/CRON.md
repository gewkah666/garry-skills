# anime-tracker · cron 蓝图（M-2）

| 名字 | 时间 | 形式 | 入口 |
|---|---|---|---|
| `anime-track-and-fetch` | `30 2 * * *` | no-agent 脚本 | `~/.hermes/scripts/anime-track-and-fetch.sh` → `_skill_cron.sh` → `scripts/anime-track-and-fetch.sh` |

做什么：读 `~/.config/anime-tracker/watchlist.yaml` → Bangumi 判连载（bangumi-resolve）→ DMHY 搜磁力（dmhy-search）→ aria2 RPC（localhost:6800）提交 → 统计。代理不可达时由 `proxy_guard.sh` 清代理直连。
重建：`hermes cron create --name anime-track-and-fetch --script anime-track-and-fetch.sh --no-agent --deliver local "30 2 * * *"`
每次运行在 Phantom 事件库留一条 `cron:anime-track`。
