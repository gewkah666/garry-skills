---
name: daily-report
description: 每日科技 / 游戏日报。凌晨 1 点抓 Hacker News、GitHub Trending、IGN、Gematsu，用 DeepSeek（关思考）或 MiniMax 分类总结，写一页到 Notion 阅览世界（类型=新闻）。纯脚本，不经 agent；跑完在 Phantom 事件库留一行。
version: 1.2.0
author: Phantom
metadata:
  hermes:
    tags: [news, daily, notion, cron, qq]
---

# 每日科技 / 游戏日报

每天凌晨 1 点抓 Hacker News、GitHub Trending、IGN、Gematsu，LLM 归类（严格基于候选，不编）→ 写 Notion 阅览世界（`747e9f3b-…`，类型「新闻」）→ QQ 简报推送（OneBot `send_private_msg` 发 admin_qq，含两页 Notion 链接；凭据复用 moss-home.json 的 `onebot_http`/`onebot_token`/`admin_qq`，**不要**走 moss_home.py 的 report——那是家居事件专用，带免打扰/220 字/音箱播报）。纯脚本，不经 agent。

- 模型链：`DEEPSEEK_API_KEY` 先用 deepseek-v4-flash（**thinking 关闭** —— 2026-09-03/04 两晚思考把预算吃光、正文为空而失败），空回或出错回退 MiniMax-M3，再回退 GLM（`glm-5.3-flash`，OpenAI 兼容，`GLM_API_KEY`/`GLM_BASE_URL`）。
- 原始响应存 `~/.cache/anime-tracker/daily-report-raw-<日期>.json`，日志 `daily-report.log`。

## moss profile（WSL）部署适配

- 部署副本：`/home/garry/.hermes/profiles/moss/scripts/daily-report.sh`（cron 从 profile scripts 目录解析），改动后要 `cp` 回 skill 的 `scripts/` 保持同步。
- 网络：本机外网**必须走环境代理** `http://127.0.0.1:7900`，直连外网 TLS 握手全部超时。脚本头部做代理 TCP 存活检查，不通才清空变量直连；Python 内**禁止** `install_opener(ProxyHandler({}))` 强制直连（macOS 旧版遗留，在本机必然全挂）。本地服务（OneBot 127.0.0.1:3100）靠 no_proxy 豁免。
- 凭据：Notion 用 `NOTION_TOKEN`，回退 `NOTION_API_KEY`（`~/.hermes/.env`）；`DEEPSEEK_API_KEY` 只在 agent 进程环境里，不在 .env 文件里。
- date：GNU 语法 `date -d yesterday` 优先，BSD `-v-1d` 回退（macOS 版脚本原本只有后者）。
- 本机没有 `_skill_cron.sh` / `proxy_guard.sh`，也不写 Phantom 事件行；失败排查看 `hermes cron list` 和 `daily-report.log`。
- `scripts/fetch_news.py` 是独立的抓源模块（HN / 微博热搜 / GitHub / V2EX），目前日报没用它，留作数据源库。
- QQ 简报偶发 `[Errno 104] Connection reset by peer` = NapCat 瞬时半死态（moss-home 技能有同源记录），几十秒内自愈。send_qq_digest 已内置 3 次重试（间隔 15s/30s，2026-11-08 加入）。若仍失败：NapCat 健康探针 `POST /get_login_info`（凭据 moss-home.json，本地调用绕代理）；确认恢复后从存档 `~/.cache/anime-tracker/daily-report-raw-<昨日>.json` 取 `choices[0].message.content` 按脚本原逻辑重建简报补发，并用 `get_friend_msg_history` 核验送达。抓取/LLM/Notion 都成功、仅 QQ 失败时 exit 1，但成果不丢。

## cron 蓝图

| 名字 | 时间 | 形式 | 入口 |
|---|---|---|---|
| `daily-tech-gaming-report` | `0 1 * * *` | no-agent 脚本 | profile `scripts/daily-report.sh` |

moss profile 已部署（job `59788ee22c52`，Asia/Shanghai）：

```
hermes cron create --name daily-tech-gaming-report --script daily-report.sh --no-agent --deliver local --failure-deliver local --timezone Asia/Shanghai "0 1 * * *"
```

## 事件

默认 profile 的 `_skill_cron.sh` 会写 `cron:daily-report` 事件（失败 salience 0.35 进简报）；moss profile 未部署该包装，运行状态以 `hermes cron list` / `daily-report.log` 为准。
