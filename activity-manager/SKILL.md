---
name: activity-manager
description: >
  权益活动日历提醒管理。登记优惠活动的周期规则与配额，建 Outlook 重复事件系列；当月用完即删剩余实例。
metadata:
  author: garry
  version: "2.0"
  tags: [calendar, credit-card, reminders]
  related_skills: [trip-manager, miloco-notify]
---

# 权益活动管理 activity-manager

## 何时使用

御主提到：优惠活动/满减/薅羊毛/信用卡权益（光大等）、"提醒我去付款"、"这单优惠用掉了/别再提醒"、发来活动宣传图要求登记时 → 激活本 skill。

管理各种"到点去薅羊毛"的活动（信用卡满减、支付渠道优惠等），核心是**Outlook 重复事件 + 配额控制**。

## 数据流

```
[登记] 御主口述活动规则 → assets/activities.json
   ↓
[建系列] refresh.py 为每个活动创建一个 Outlook 原生重复事件（每天/每周五，自动无限重复）
   ↓
[消耗] 御主说"这周500-50用掉了" → mark_used.py 记次 + 删除当月剩余实例
   ↓            （若年配额触顶 → 删除全年剩余实例；已删实例次月不影响，系列继续）
[查看] status.py 列出活动、配额余量、当月剩余提醒
```

## 设计要点

- **重复系列**：周期活动只建 Outlook series（`recurrence`），日历自动到点提醒，无需 cron 逐日排期。数据存 `series_id`（单系列=字符串；monthly 多日=字典 `{"10": id, "20": id}`）。
- **单事件原则（御主明令）**：每个场次只建一个事件，严禁为凑"多重提醒"建伴生事件——日历上会被视为重复创建。事件时长 30 分钟（10:00–10:30），提醒 = 活动开始时准点响（`reminderMinutesBeforeStart: 0`）。改提醒/时长直接调 `common.py` 的 `EVENT_MINUTES` / `REMINDER_MIN` 后 `refresh.py --clean && refresh.py` 重建。
- **Graph v1.0 限制**：`absoluteMonthly` 只支持**单个** `dayOfMonth`（复数 `daysOfMonth` 会 400 UnableToDeserializePostBody）。故 `{"freq":"monthly","days_of_month":[10,20]}` 会为每个日号各建一组系列。修改时长/提醒等属性无法增量生效时，用 `refresh.py --clean && refresh.py` 重建。
- **配额靠删实例**：Outlook 重复事件没有"每月只提醒 N 次"的原生能力 → 用完当月名额后 `mark_used.py` 通过 `/instances` 枚举并 DELETE 当月剩余实例。
- **月度重置无需操作**：只删了当月实例，下月实例由系列原生生成，配额账本按 `used.months["YYYY-MM"]` 独立计。
- **年配额触顶**：把到年底（或 valid_until）的所有未来实例一次删光；若活动跨年需御主确认后重建系列。
- 提醒频率≠活动频率：如充话费活动本身每天可做，但默认只在每月 10/20 号提醒；御主想临时提前用名额，说一声由助手处理即可。

## 用法

脚本目录：`~/.hermes/skills/garry-skills/activity-manager/scripts/`
数据文件：`assets/activities.json`

### 登记新活动

向 `assets/activities.json` 的 activities 数组追加：

```jsonc
{
  "id": "ceb-jd-500",
  "name": "光大×京东 满500减50",
  "bank": "光大银行",
  "rules": [{"freq": "weekly", "weekday": 5}],  // weekday: 1=周一..7=周日
  // 或 {"freq":"daily"}，或 {"freq":"monthly","days_of_month":[10,20]}（每日号一个系列）
  "time": "10:00",
  "quota": {"per": "month", "max": 1, "year": 2026, "year_max": 2},  // 不限次则 null
  "valid_until": "2026-12-31",     // 可选；决定系列 range.endDate
  "desc": "京东APP付款满500-50，每月1次，全年最多2次",
  "enabled": true,
  "used": {"months": {}, "years": {}},
  "series_id": null,               // refresh 维护
  "events": {}                     // （v1 遗留字段，可空）
}
```

### 建立/修复重复系列

```bash
source ~/.hermes/trip-env.sh
python3 scripts/refresh.py                 # 幂等：没有 series_id 的活动才建
python3 scripts/refresh.py --clean [--id xxx]   # 删除系列（+v1 一次性事件）
```

### 标记已使用

```bash
python3 scripts/mark_used.py --id ceb-jd-500                    # 记1次 + 删当月剩余实例
python3 scripts/mark_used.py --id ceb-zfb-recharge --count 2    # 本月2次全用完
python3 scripts/mark_used.py --id ceb-jd-500 --date 2026-09-04  # 补记历史日期
python3 scripts/mark_used.py --id xxx --dry-run                 # 预演，不写入
```

### 查看状态

```bash
python3 scripts/status.py                  # 含日历实例查询
python3 scripts/status.py --no-calendar    # 离线快查（只看账本）
```

## 约定与坑

- 事件标题 `💰 {活动名}`，category `💰 权益活动`，时区 China Standard Time。
- 依赖 trip-manager 的 Outlook 认证（`~/.hermes/trip-env.sh`、`scripts/outlook_event.py` 的 `graph_request`）。
- **Graph `/instances` 边界漂移**：查询窗口偶含前后一天的实例，`get_instances` 已做客户端日期过滤，勿删。
- 删除实例用实例自己的 id（DELETE /me/events/{instance_id} 合法）。
- 御主发来活动宣传图时：读图提取生效日期/门槛/时段，更新 json 的 desc/valid_until；规则变了先 `--clean --id` 再 `refresh.py` 重建系列。
- 提醒"以宣传图为准，日期待核"的活动，desc 中保留【待核】标记直至御主确认。
