---
name: ride-notion
description: 记录运动数据到 Notion 阅览世界。手动输入或解析健身 App 截图（Apple Health / Apple Watch / Strava / 高驰 / 佳明），把骑行的距离、时长、心率、配速、爬升、消耗等数据写入 Notion 阅览世界数据库（类型=日常，状态=已记录，时间线=出发时间）。支持单次记录和批量补录。触发：用户说话"记录运动"/"今天骑车"/"记一次骑行"或粘贴健身截图。
version: 1.0.0
author: Hermes Agent
license: MIT
platforms: [macos, linux]
metadata:
  hermes:
    tags: [exercise, fitness, bike, ride, strava, garmin, notion, health]
---

# Ride Notion — 运动记录写入 Notion

## 概述

把骑车/跑步/游泳等户外运动数据写入 Notion **阅览世界**（`747e9f3b-0bbf-4f03-b678-7fc62a093790`），方便长周期追踪。

## 三种记录方式

### 1. 手动输入（最快）

```bash
~/.hermes/hermes-agent/venv/bin/python scripts/ride_log.py log \
  --distance 20.59 \
  --duration "1h13m44s" \
  --avg-speed 16.7 \
  --avg-hr 131 \
  --calories 440 \
  --elevation 33 \
  --activity "骑行" \
  --location "杭州" \
  --start-time "2026-08-04T22:02:00" \
  --note "夜骑绕西湖"
```

### 2. 解析截图（OCR）

```bash
# 截图保存到 ~/Desktop/ride.png
~/.hermes/hermes-agent/venv/bin/python scripts/ride_log.py screenshot --file ~/Desktop/ride.png
```

内部的 OCR 用系统命令行工具（Tesseract / macOS Vision via Swift）。

### 3. 解析 Apple Health Export

```bash
# 从 iPhone Health App 导出 XML
~/.hermes/hermes-agent/venv/bin/python scripts/ride_log.py healthxport --file ~/Downloads/export.xml
```

## 数据格式

Notion 阅览世界字段映射：

| 字段 | 值 | 示例 |
|------|---|------|
| 名字 | 类型 + 距离 + 时间 | `🚴 骑行 - 20.59 km - 1h13m` |
| 类型 | `日常` | 日常 |
| 状态 | `已记录` | 已记录 |
| 时间线 | 起止时间 | `2026-08-04T22:02-23:16` |
| 短评 | 关键数据 | `杭州 · 16.7 km/h · 131 bpm · 440 kcal` |
| 链接 | (可选) Strava 链接 | https://www.strava.com/... |

## 关键功能

### 1. 智能识别运动类型

| 关键词 | 推断 |
|--------|------|
| 骑行 / bike / 公路车 / 折叠车 | 骑行 |
| 跑步 / run / 慢跑 | 跑步 |
| 游泳 / swim | 游泳 |
| 徒步 / hike / 健走 | 徒步 |
| 健身 / gym / 力量 | 健身 |

### 2. 智能心率分析

```python
# 自动评估强度
def intensity(avg_hr, max_hr=190):
    pct = avg_hr / max_hr
    if pct < 0.6: return "热身"
    if pct < 0.7: return "燃脂"
    if pct < 0.8: return "有氧"
    if pct < 0.9: return "无氧"
    return "极限"
```

### 3. 段数据保留（如截图每段配速）

```bash
# 段数据写入页面正文（page content）
~/.hermes/hermes-agent/venv/bin/python scripts/ride_log.py log --segments '[{"speed":17.4,"hr":124,"time":17.11},{"speed":15.8,"hr":127,"time":18.52}]'
```

### 4. 周报 / 月报

```bash
~/.hermes/hermes-agent/venv/bin/python scripts/ride_log.py report --period weekly
~/.hermes/hermes-agent/venv/bin/python scripts/ride_log.py report --period monthly
```

## 依赖

- `requests` — Notion API
- `Pillow` + `pytesseract` — OCR（可选）
- `~/.hermes/.env` 或 `~/.garry-skills/.env` — 含 `NOTION_API_KEY`

## 安装

```bash
# 1. 复制到 garry-skills（已 symlink）
ln -sfnv ~/Projects/garry-skills/ride-notion \
    ~/.hermes/skills/smart-home/ride-notion

# 2. 装依赖
pip install requests Pillow pytesseract

# 3. macOS 还需要 tesseract
brew install tesseract

# 4. 测试
~/.hermes/hermes-agent/venv/bin/python scripts/ride_log.py test   # 注意：会真的写一条测试骑行到阅览世界，测完记得删
```

## 配置

修改 `scripts/config.py`:
- `NOTION_DIARY_DB_ID`: `747e9f3b-0bbf-4f03-b678-7fc62a093790`
- `NOTION_API_KEY`: 已有
- `DEFAULT_MAX_HR`: 190（计算心率区间）
