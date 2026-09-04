---
name: phantom-escalate
description: 坚持到确认为止的提醒（从 water-reminder 抽出）。参数化「提醒什么 / 起始与最高级别 / 多久升一级 / 怎么算确认」，每一步走 phantom_notify，受打扰预算约束。用于必须真的发生的事：喝水、吃药、出门赶车、下雨前关窗。
version: 1.0.0
author: Phantom
metadata:
  hermes:
    tags: [phantom, reminder, escalation, water, health]
    related_skills: [water-reminder, phantom-consolidation]
---

# Phantom 坚持提醒（escalate）

## 什么时候用

- 一件事**必须真的发生**，说一次不够：喝水、吃药、出门、关窗、关灯、复查。
- 御主说「提醒我 X，没回就再催」「盯着我做 Y」。
- 不用于「知道一下就行」的事 —— 那是一次 `phantom_notify`。

## 工具

只有一个：`phantom_escalate`。

```
action=start
  what              一行标题（也是去重键：同一件事只能有一条 active）
  message           提醒正文，一两句
  level             第一步级别，默认 L1（飞书）
  ladder            后续阶梯，默认 [{after:"15m", level:"L1"}, {after:"30m", level:"L2"}]
  confirm_keywords  御主说了就算确认的词，如 ["喝了","喝过了"]
  confirm_event     事件库里出现这段文字就算确认，如 "水杯"
  kind              反馈学习的类别：water / health / schedule / device …
  home_only         不在家就作废（喝水、家务）
  expires           最多坚持多久（"3h"），默认最后一步之后 6 小时
action=list        看正在坚持的
action=confirm id  御主明确做了
action=cancel  id  不用提醒了
```

## 它自己会做的事

- **立刻发第一步**，之后由 5 分钟一次的 `phantom-escalate-tick` 定时任务推进阶梯。你不用重发，也不要用 send_message 手动再催。
- **每一步都过预算**：睡眠、会议、御主说「别烦」时该步**推迟到抑制解除**，不是跳过，也不换通道绕过。当日 L2 超额会降到 L1。
- **确认三种来源**：御主接下来 2 小时内说了 `confirm_keywords` 里的词；或一句简短的「好的 / 收到 / 做了」；或事件库里出现 `confirm_event`。确认后最后一张票记为 useful，喂给采纳率反馈。
- **阶梯走完没确认 → expired**，会写 outcome；到 `expires` → expired；被预算 deny（比如 home_only 且不在家）→ cancelled 并写原因。
- 生活状态简报里会列出正在坚持的提醒（已提醒几次、下一步几级几点、说什么即确认）。

## 阶梯怎么定

| 场景 | 建议 |
|---|---|
| 喝水（默认） | L1 → 15m L1 → 30m L2，`home_only=true`，`kind=water` |
| 吃药 | L1 → 10m L2 → 20m L2 → 30m L3（健康才配 L3），`kind=health` |
| 出门赶车 | L2 → 5m L2 → 5m L3，`expires` 设到发车时刻 |
| 下雨前关窗 | L1 → 10m L2，`confirm_event` 可填传感器文本 |

L3 会穿透静音并在音箱播报，**只给健康与安全**。阶梯越短越好 —— 一条能催三次的提醒，第四次就是骚扰。

## water-reminder 的对应关系

原 skill 里「TTS 到书房 mini + 飞书 + 15 分钟未确认再提醒 + 30 分钟升级 + 不在家跳过 + 会议中跳过」现在全部由 escalate + 预算完成：

```
phantom_escalate action=start what="喝水" message="该喝水了，今天第 3 杯"
  confirm_keywords=["喝了","喝过了","ok"] kind=water home_only=true
```

每日饮水计数与日报仍由 water-reminder 自己维护；它只需把「催」这一段换成上面这一句。
