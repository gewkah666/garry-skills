---
name: phantom-consolidation
description: Use for phantom-consolidate runs and backfill passes.
version: 1.0.0
author: Raphael (Phantom)
license: MIT
metadata:
  hermes:
    tags: [phantom, memory, consolidation]
    related_skills: [miloco-home-profile]
---

# Phantom 记忆固化（episodic → semantic）

## When to Use

- phantom-consolidate 定时任务触发，或御主要求「固化记忆 / 补读历史事件 / 把事件库沉淀成长期事实」。
- 事件库刚回填了历史（pending 数百条）需要分批通读时。

Phantom 的事件库（episodic）需要周期性固化为长期事实（semantic）。工具为 deferred MCP tools，先 `tool_describe` 再 `tool_call`：`phantom_consolidate`（review/commit/status）与 `phantom_remember`。

## 主循环（严格按序，勿跳步）

1. `phantom_consolidate action=review` — 返回最老在前的未固化事件批（默认 ~120 条）、`through_ts`（本批水位终点）、`pending`/`remaining`。
2. pending=0 → 什么都不写，回复「无新事件」结束。
3. 把这批事件当作**一段连续的生活**来读。判据只有一条：**这条结论下个月还成立吗？**
   - 值得记：作息规律、偏好口味、常去的地方、家庭成员与宠物、设备固有习性、在做什么项目、反复求助的事。
   - 不值得记：单次事件、随时可从事件库查回的细节、未经断言的推测。
4. 每条结论调 `phantom_remember`，**必须给 entities**（中文文本自动抽不出实体；无 entities 的事实等于丢失）。类别用 `user_pref`（习惯偏好）/ `project` / `tool` / `general`，附 `source_note`（时间跨度+来源）。
5. 写完 `phantom_consolidate action=commit`，传 review 的 `through_ts` 和**实际写入条数**。一条没写也要 commit（facts_written=0），前提是真读完了这批。
6. 循环 review→commit 直到 pending=0。补读多年历史时约每批 100+ 条、分多批推进。
7. 收尾报告：读了多少条（时间跨度）、记住哪几条（逐条列）。

## 回填历史（backfill）的写法

事件跨度可能好几年，结论要写成**跨时间仍成立的形式**并带时间锚，例如「2021 年前后集中看番剧」而非逐条罗列单次观看。同一条事实只写一次，后续批次遇到相同模式不重复 remember——但不同维度（如项目形态 vs 硬件迁移）可分条。

## 铁律与坑

- **身份臆测禁令**：涉及人只写事件里**确实被断言过**的名字。摄像头日志的「有人（未识别）」就是未识别，永远不许猜是谁；「御主」= 用户本人。
- **凭据禁令**：事件流里可能出现用户粘贴的 API key / 密码 / token（对话类事件常见）。绝不把这些写进任何 fact；只记「用户配置过 X 服务」这类不含密钥的形态。
- **commit 是推进水位的唯一手段**：review 后中途放弃会导致该段被静默跳过、日志丢失——要么读完并 commit，要么别 commit。
- **fact 措辞会被实体链接改写**（工具会把 entities 词插入 content），属正常现象，不必重试。
- 判断「设备固有习性 vs 一次性故障」：同类现象跨多日重复出现（如感知误报、深夜电视常开）才算习性；单次断网/失败不记。
- 只陈述事件支持的观察，不做因果脑补（灯 23:40 亮 ≠ 他在熬夜工作）。

## 事件来源速查

- `notion:阅览世界` — 足迹（分段行程，含交通方式）、运动/饮水打卡
- `notion:tasks` — 任务开始/完成（含项目名、优先级、用时）→ 项目在做什么、夜型作息等
- `miloco:camera:*` / `miloco:rule` — 在场识别（who 字段有名字才算断言）、宠物、设备状态
- `agent:conversation:*` — 用户原话 → 偏好、约定、设施信息（注意凭据过滤）
- `cron:*` — 定时任务成败 → 只记反复出现的模式，不记单次失败
