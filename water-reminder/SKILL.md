---
name: water-reminder
description: Smart water-drinking reminder for the user who forgets to drink water. Runs as a cron job every 2 hours during the day, sends a TTS announcement to 书房 mini (via miloco-tts) AND a 飞书 (Feishu) message with confirmation required. Escalates if not confirmed within 15 minutes, then 30 minutes. Integrates with Notion calendar to skip reminders during meetings / focus blocks, and miloco camera to skip when user is not at home. User replies via 飞书 ("ok" / "喝了" / "暂停" / etc.) to control the flow. Tracks daily intake (200ml per cup, target 8 cups) and reports at end of day.
version: 1.0.0
author: Hermes Agent
license: MIT
platforms: [macos, linux]
metadata:
  hermes:
    tags: [health, reminder, water, hydration, miloco, feishu, notion]
---

# Water Reminder (智能喝水提醒)

## 概述

用户**不爱喝水** + 容易忘。需要**多通道强制提醒 + 必须确认 + 持续升级**。

## 触发

- **Cron**：每 2 小时（9:00 / 11:00 / 13:00 / 15:00 / 17:00 / 19:00 / 21:00）
- **手动**：用户说"喝一杯"、"加一杯"立即记
- **智能感知**：miloco 检测到打开水杯/冰箱自动记

## 工作流程

### 1. 提醒前检查

```
当前时间 → 加载 .env → 查 Notion 日程
       ↓
   在家吗？ (miloco)
       ↓
   在会议/专注块？ (Notion)
       ↓
   暂停状态？ (本地 state.json)
       ↓
   今日已喝 ≥ 8 杯？ → 跳过
       ↓
   进入提醒流程
```

### 2. 提醒（多通道）

```
Step 1: TTS 朗读 (书房 mini)
  对书房说 喝口水，别等渴了才喝
  
Step 2: 飞书发消息
  🚰 喝水时间！
  当前: 3/8 杯 (600ml)
  ⏰ 15 分钟内回 "ok" 确认
  
Step 3: 等 15 分钟
  - 收到 "ok" / "喝了" / "ok" / "喝" → 记录 +1
  - 收不到 → 进入 Step 4
```

### 3. 升级机制

```
Step 4: 第一次升级（15 分钟没确认）
  飞书: 🚨 15 分钟没喝水，2 小时了
  TTS: 还没喝水吗？
  ⏰ 30 分钟内回复
  
Step 5: 严重警告（30 分钟还没）
  飞书: 🚨🚨 2 次提醒都没回！快去喝水！
  TTS: 现在，立刻，喝水
  蜂鸣 5 秒
  ⏰ 持续提醒到 22:00
  
Step 6: 22:00 收工汇报
  飞书: 今日饮水汇总
  6 杯 / 1200ml / 75% 目标
```

### 4. 用户控制命令（飞书）

| 飞书消息 | 效果 |
|----------|------|
| `ok` / `喝了` / `喝` / `👌` | 确认本次 |
| `加一杯` | 主动记录 +1 |
| `暂停` / `开会` | 暂停 2 小时 |
| `今天不提醒` | 整天关闭 |
| `几点了` / `进度` | 报当前进度 |
| `重置` | 清零今日计数 |
| `明天 8 点开始` | 调整开始时间 |
| `以后每 3 小时` | 调整频率 |

## 集成

### Notion（避开会议）

```python
# 查当前时间段日程
events = notion.databases.query(
    database_id=CALENDAR_DB_ID,
    filter={"and": [
        {"property": "Start", "date": {"on_or_after": now}},
        {"property": "Start", "date": {"before": now + 30min}}
    ]}
)
if events and "focus" in events[0].title.lower():
    return "skip_focus_block"
```

### miloco（在家感知）

```python
# 检测最近 5 分钟是否有人
recent = miloco.perception.get_recent(minutes=5)
if not recent.has("person"):
    return "skip_not_home"
```

### 书房 mini TTS

调用 `miloco_tts.py`（已有 skill）

### 飞书消息

通过 hermes `send -t feishu` 命令

## 数据存储

`~/.hermes/miloco/water_state.json`:
```json
{
  "date": "2026-08-01",
  "cups": 3,
  "last_remind": "2026-08-01T11:00:00",
  "last_confirm": "2026-08-01T11:15:00",
  "paused_until": null,
  "skip_today": false
}
```

## 依赖

- `miloco-tts` skill（已装）
- `notion` skill（已装）
- `miloco` 后端（已跑）
- `MINIMAX_API_KEY` / `NOTION_API_KEY` 在 .env
- `hermes send` CLI（飞书消息）
- 书房 mini 在线

## 安装

```bash
# 1. 复制 skill 到 garry-skills
ln -sfnv ~/Projects/garry-skills/water-reminder ~/.claude/skills/water-reminder
ln -sfnv ~/Projects/garry-skills/water-reminder \
    ~/.hermes/skills/smart-home/water-reminder

# 2. 装依赖（用 hermes Python）
~/.local/share/uv/tools/hermes-agent-cn/bin/python -m pip install requests

# 3. 加 cron
hermes cron add "0 9,11,13,15,17,19,21 * * *" \
    "cd ~/Projects/garry-skills/water-reminder && python3 scripts/check_and_remind.py"
```

## 配置

修改 `scripts/config.py`:
- `NOTION_CALENDAR_DB_ID`: Notion 日程数据库 ID
- `TTS_DEVICE`: 默认 `书房`
- `DAILY_TARGET_CUPS`: 默认 8
- `REMIND_FREQUENCY_HOURS`: 默认 2
- `ACTIVE_HOURS`: 默认 `9:00-22:00` (工作日) / `10:00-23:00` (周末)
