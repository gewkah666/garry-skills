---
name: daily-report
description: 每日科技 / 游戏日报。凌晨 1 点抓 Hacker News、GitHub Trending、IGN、Gematsu，用 DeepSeek（关思考）或 MiniMax 分类总结，写一页到 Notion 阅览世界（类型=新闻）。纯脚本，不经 agent；跑完在 Phantom 事件库留一行。
version: 1.1.0
author: Phantom
metadata:
  hermes:
    tags: [news, daily, notion, cron]
---

# 每日科技 / 游戏日报

`scripts/daily-report.sh` 就是全部：抓源 → LLM 归类（严格基于候选，不编）→ 写 Notion 阅览世界（`747e9f3b-…`，类型「新闻」；Phantom 回填时跳过这一类，日报是 Phantom 读的东西，不是御主做的事）。

- 模型：有 `DEEPSEEK_API_KEY` 先用 deepseek-v4-flash（**thinking 关闭** —— 2026-09-03/04 两晚思考把预算吃光、正文为空而失败），空回或出错回退 MiniMax-M3。
- 原始响应存 `~/.cache/anime-tracker/daily-report-raw-<日期>.json`，日志 `daily-report.log`。
- `scripts/fetch_news.py` 是独立的抓源模块（HN / 微博热搜 / GitHub / V2EX），目前日报没用它，留作数据源库。

## cron 蓝图

| 名字 | 时间 | 形式 | 入口 |
|---|---|---|---|
| `daily-tech-gaming-report` | `0 1 * * *` | no-agent 脚本 | `~/.hermes/scripts/daily-report.sh`（3 行包装 → `_skill_cron.sh` → 本 skill 脚本） |

重建：`hermes cron create --name daily-tech-gaming-report --script daily-report.sh --no-agent --deliver local "0 1 * * *"`

## 事件

每次运行 `_skill_cron.sh` 写一条 `cron:daily-report` 事件（完成 / 失败 + 最后一行），复盘和记忆能看到；失败时 salience 0.35，会进简报。
