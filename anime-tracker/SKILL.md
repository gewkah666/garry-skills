---
name: anime-tracker
description: >
  Automated anime tracking system that combines Bangumi metadata with DMHY magnet search,
  driven by a curated watchlist. Bangumi resolves completion status (subject_id overrides
  keyword search); DMHY finds the latest magnets; aria2 RPC submits downloads to a NAS path
  mounted under /Volumes/. Use when the user wants to track ongoing anime series and
  automatically fetch new episode magnets without manual checking.
---

# Anime Tracker

自动追剧流水线，整合 **Bangumi（状态判定）+ DMHY（磁力搜索）+ aria2（下载）**。

## 数据流

```
~/.config/anime-tracker/watchlist.yaml  (追剧清单)
   ↓
Bangumi API → subject_id → 连载中/完结判定
   ↓ (only if ongoing)
DMHY RSS → 关键词匹配最新磁力
   ↓
aria2 RPC → /Volumes/<NAS>/Anime/<剧名>/
   ↓
极空间 NAS → 极影视自动扫描入库
```

## 配置：追剧清单

`~/.config/anime-tracker/watchlist.yaml`

```yaml
- name_cn: 葬送的芙莉莲
  bangumi_id: 305429         # 可选:直接指定 Bangumi subject_id
  subdir: 葬送的芙莉莲       # 可选:覆盖默认目录名

- name_cn: 关于我转生变成史莱姆这档事 第四季
  bangumi_id: 515594        # 第4期(年番切 4 季度播放)
  subdir: 转生史莱姆S4

- name_cn: 进击的巨人
  # 不指定 bangumi_id → 用关键词搜 (eps==total 时跳过)
```

## 脚本

| 脚本 | 用途 |
|------|------|
| `scripts/anime-tracker.py` | 主入口: 读 watchlist → Bangumi → DMHY → aria2 |
| `scripts/setup-watchlist.py` | 交互式生成 watchlist.yaml |

## 使用

```bash
# 单次运行 (dry-run)
python ~/.hermes/skills/anime-tracker/scripts/anime-tracker.py --dry-run

# 真正下载
python ~/.hermes/skills/anime-tracker/scripts/anime-tracker.py

# 自定义 watchlist 路径
python ~/.hermes/skills/anime-tracker/scripts/anime-tracker.py --watchlist ~/my-watchlist.yaml
```

## 输出目录

默认: `/Volumes/sata11-157XXXX5549/电影&电视剧/Anime/<剧名>/`

## Cron 调度

每日凌晨 02:30 自动跑（由 Hermes cron job `anime-track-and-fetch` 触发）。

## 与其他 skill 的关系

- **bangumi-resolve**：被本 skill 复用（搜索/判定）
- **dmhy-search**：被本 skill 复用（RSS 抓取/磁力提取）
- **download-anything**：被本 skill 复用（aria2 RPC 调用）

## 已知限制

- DMHY RSS 仅返回最近 100 条，极冷门新番可能漏抓
- Bangumi 季级 subject 录入滞后 1-3 个月（2026 年新季度可能未收录）
- Bangumi `eps` 字段对年番切季度播放的作品（如转生史莱姆S4）数据不准确，
  推荐手动指定 bangumi_id 而非依赖关键词搜索