---
name: dmhy-search
description: >
  Search magnet links on 動漫花園 (DMHY / share.dmhy.org). Use when the user wants to
  find BitTorrent magnet links for anime, manga, Japanese drama, or other ACG content.
  Supports keyword search, category filtering, and smart title parsing (season/episode
  /resolution/fin marker). Provides results as JSON so downstream tools (aria2 RPC,
  download-anything skill) can pick them up automatically.
---

# DMHY Search

搜索動漫花園資源網（`share.dmhy.org`）磁力链接的工具集。

## 数据源

- **主源**：DMHY 公开 RSS（无需账号、无需翻墙）
- **地址**：`https://share.dmhy.org/topics/rss/rss.xml`（约每 30 分钟更新）
- **覆盖**：动画 / 日剧 / 漫画 / 动漫音乐 / OVA / OAD / 完结动画 等

## 脚本

| 脚本 | 用途 |
|------|------|
| `scripts/dmhy_list.py` | 列表最新种子（可按分类筛选） |
| `scripts/dmhy_search.py` | 按关键词搜索（标题包含匹配） |
| `scripts/dmhy_pick.py` | 智能匹配剧名（含季/集/分辨率正则） |

## 决策表

| 想做什么 | 怎么用 |
|----------|--------|
| 看今天有什么新种 | `python scripts/dmhy_list.py --limit 20` |
| 只看动画类 | `python scripts/dmhy_list.py --category 动画 --limit 10` |
| 找某部剧的磁链 | `python scripts/dmhy_search.py "鬼灭之刃"` |
| 找第 X 季特定分辨率 | `python scripts/dmhy_pick.py "葬送的芙莉莲" --season 2 --resolution 1080p` |
| 找"Fin"标记的完结版 | `python scripts/dmhy_search.py "高木同学" --filter fin` |
| 把搜索结果喂给 aria2 RPC | 见"下游集成" |

## 分类 ID

| sort_id | 中文名 |
|---------|--------|
| 2 | 動畫 |
| 3 | 漫畫 |
| 4 | 動漫音樂 |
| 6 | 日劇 |
| 7 | ＲＡＷ |
| 8 | 遊戲 |
| 9 | ＴＶ剧 |
| 10 | 特攝 |
| 12 | 動畫（下載區） |
| 13 | 漫画（下载区） |

## 下游集成

输出 JSON 可直接管道到 aria2 RPC：

```bash
# 1. 搜索
python ~/.hermes/skills/dmhy-search/scripts/dmhy_pick.py "剧名" --season 1 --json \
  | jq '.magnet' -r \
  | xargs -I {} bash ~/zspace_skill/dl-to-nas.sh "{}" "TV/剧名"
```

## 已知限制

- 仅基于 RSS 缓存（约 30 分钟延迟）
- DMHY RSS 单次返回最近约 100 条
- 季/集判断依赖标题正则，可能误判（字幕组命名不统一）