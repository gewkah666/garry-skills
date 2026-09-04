---
name: trip-manager
description: >
  行程管理 skill。Master 创建未来行程（出发时间、地点、交通方式、描述）→ 写入 Outlook 日历；
  每日 07:00 自动把前一天的已发生行程聚合写入 Notion 「阅览世界 / 足迹」，然后删除 Outlook 事件，
  日历仅保留未来行程。Master 提及行程时未来行程修改 Outlook 日历，过去行程修改 Notion page。
---

# 行程管理 trip-manager

## 数据流

```
[输入] Master 行程请求（CLI/对话）
   ↓
trip-manager 创建 Outlook 日历事件
   ↓
[日历] 未来行程仅保存在 Outlook 日历

[每日 07:00 cron]
   ↓
查询 Outlook 前一天的 calendarView 事件
   ↓
按日聚合 → 写入 Notion「足迹」条目（1天=1条目，多段合并）
   ↓
删除 Outlook 上的对应事件（日历只留未来行程）

[Master 提及修改行程]
   ↓
智能路由：未来 → Outlook，过去 → Notion
```

## 配置

首次运行前必须设置环境变量：

```bash
# Master 已配置: ~/.hermes/trip-env.sh
# 包含: MS_GRAPH_CLIENT_ID, NOTION_TOKEN
```

## 用法

### 添加行程（创建到 Outlook 日历）

```bash
python3 ~/.hermes/skills/garry-skills/trip-manager/scripts/outlook_event.py create \
    --start "2026-09-01T08:00:00+08:00" \
    --end "2026-09-01T18:00:00+08:00" \
    --title "北京出差" \
    --location "首都国际机场" \
    --body "见客户张总" \
    --transport "✈️ 飞机" \
    --origin "上海" \
    --destination "北京"
```

### 查询指定日期范围行程

```bash
python3 ~/.hermes/skills/garry-skills/trip-manager/scripts/outlook_event.py list \
    --start "2026-08-25T00:00:00+08:00" \
    --end "2026-08-26T00:00:00+08:00"
```

### 智能修改行程（未来→Outlook，过去→Notion）

```bash
# 修改未来行程（Outlook 日历）
python3 ~/.hermes/skills/garry-skills/trip-manager/scripts/trip_modify.py "Day5" \
    --subject "Day5 - 甘孜（修改版）"

# 给过去行程打分（Notion）
python3 ~/.hermes/skills/garry-skills/trip-manager/scripts/trip_modify.py "Day3" \
    --score "⭐️⭐️⭐️⭐️⭐️" --review "色达震撼"

# 添加备注
python3 ~/.hermes/skills/garry-skills/trip-manager/scripts/trip_modify.py "Day2" \
    --body "返程时遇到暴雪，绕道走 G317"
```

### 手动归档昨日行程（支持多日游聚合）

```bash
# 单日归档
python3 ~/.hermes/skills/garry-skills/trip-manager/scripts/notion_sync.py archive-yesterday

# 多日游（如十一出行）
python3 ~/.hermes/skills/garry-skills/trip-manager/scripts/notion_sync.py archive-yesterday \
    --project "国庆川西 2026"
```

## Notion 写入字段映射

| 数据来源 | Notion 字段 |
|----------|------------|
| Outlook subject | 名字 (`Day2 - 四姑娘山→八美`) |
| 首个 emoji | icon (🏔/🪨/📸 等) |
| Outlook start.dateTime | 时间线 / 上映/发布时间 |
| Outlook locations（去重首末） | ⛱️起点 / 终点（relation） |
| 标题 emoji 检测 (🚗/🚞/✈️) | 交通方式 select |
| 行程段 | body bullet list |
| --project 参数 | 父项目 page + relation |

## cron 配置

每天 07:00 自动执行：

```bash
hermes cron create "0 7 * * *" \
    --name "trip-archive-yesterday" \
    --deliver local \
    --script "trip_archive.sh"
```

## 关键设计

- **按日聚合**：同一天多个事件合并为 1 个 Notion page
- **交通 emoji 检测**：从标题中提取 (🚗✈️🚞) 自动映射到 select 字段
- **父项目复用**：同名 project 自动复用，避免重复创建
- **智能路由**：未来/过去行程修改不同的目标系统