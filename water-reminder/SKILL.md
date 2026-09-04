---
name: water-reminder
description: 智能喝水提醒，跑在 Hermes 上。每 2 小时（9–21 点）由 cron 触发：先过 Phantom 的打扰预算（睡觉 / 开会 / 不在家自动跳过），今天够 8 杯就不提，否则用 phantom_escalate 坚持提醒到御主确认（飞书 → Bark 升级）。御主在飞书回「喝了 / ok」即确认并记一杯；说「喝一杯 / 加一杯」随时记；22:00 汇总当天。状态只在 Phantom 的事件库里，没有第二份真相。
version: 2.0.0
author: Phantom
license: MIT
metadata:
  hermes:
    tags: [health, reminder, water, hydration, phantom]
    related_skills: [phantom-escalate, phantom-consolidation]
---

# 喝水提醒（Hermes / Phantom 版）

御主不爱喝水、容易忘。要多通道、必须确认、持续升级 —— 这三件事 Phantom 已经有现成的机制，这个 skill 只是把它们接起来，**不自己维护状态、不自己发消息、不自己判断在不在家**。

## 真相在哪

- **喝了几杯**：事件库。每喝一杯写一条 `phantom_event_write`：`source=agent:water`，`observation=御主喝了一杯水`，`kind=health`，`salience=0.2`。查今天的杯数：`phantom_event_query source=agent:water since=today`。
- **提醒有没有被确认**：`phantom_escalate` 自己记。御主回「喝了 / ok / 喝 / 👌」，Phantom 的确认钩子会把它对上（你会在上下文看到 `[Phantom 确认]`）。
- **能不能打扰**：`phantom_budget_check`。睡眠时段、会议中、不在家、静音期、当天额度用完，预算会替你推迟或降级。**不要自己查日程、不要自己看摄像头** —— 这些是 P2-6 信号层的事。

## 定时任务（已创建）

| 名字 | 时间 | 做什么 |
|---|---|---|
| `water-reminder` | 9 / 11 / 13 / 15 / 17 / 19 / 21 点整 | 下面的「提醒流程」 |
| `water-report` | 22:00 | 下面的「收工汇报」 |

## 提醒流程（cron `water-reminder` 的 prompt 就是这段）

1. `phantom_event_query source=agent:water since=today` → 数今天有几条。≥ 8 杯：回 `[SILENT]`，结束。
2. `phantom_escalate action=list`（或看简报里的活跃提醒）：已经有一条「喝水」在坚持提醒中 → `[SILENT]`，别叠加。
3. 否则 `phantom_escalate action=start`：
   - `what`：`喝一杯水（今天第 N 杯）`；`message`：短、直接，不解释系统，如「该喝水了，今天第 3 杯。喝了回我一个字。」
   - `level`：`L1`（飞书）；`ladder`：`[{after:"15m", level:"L2"}, {after:"30m", level:"L2"}]`（15 分钟没回升 Bark，再 15 分钟再推一次）
   - `expires`：`60m`；`confirm_keywords`：`["喝了","ok","喝","👌"]`；`kind`：`water`；`home_only`：true
4. 回 `[SILENT]`。提醒本身由 escalate 送达，你不用再说话。

## 御主说话时

| 御主说 | 做 |
|---|---|
| 喝了 / ok / 喝 / 👌（提醒之后） | 确认由钩子处理；**你补一条** `phantom_event_write`（一杯），回一句「第 N 杯，记了」 |
| 喝一杯 / 加一杯 / 刚喝了两杯 | 写对应条数的事件，回杯数 |
| 暂停 / 开会 / 别烦 | `phantom_budget_quiet`（预算静音，默认 2 小时）；有活跃提醒就 `phantom_escalate action=cancel` |
| 今天不提醒 | `phantom_budget_quiet until=today 23:59` |
| 进度 / 喝了几杯 | 查事件库，回「N / 8 杯，约 N×200 ml」 |
| 重置 | 不删事件；写一条 `observation=御主要求今日饮水计数清零`，之后以它为起点数 |

## 收工汇报（cron `water-report` 的 prompt）

1. 查今天的 `agent:water` 事件，数杯数。
2. `phantom_notify level=L1 kind=health`：「今日饮水 N / 8 杯（约 N×200 ml），达成 X%。」一句话，不点评。0 杯也报，报的是事实。

## 迁移说明

旧的 `water_reminder.py`（自己查 Notion 日程、自己看 miloco、自己维护 `water_state.json`、自己发飞书、自己升级）已移到 `legacy/`，**不要再跑**：它的每一块现在都有 Phantom 的正式实现（预算、信号、事件库、escalate、reach）。两套状态等于没有状态。
