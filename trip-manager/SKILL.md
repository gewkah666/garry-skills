---
name: trip-manager
description: >
  行程管理 skill。未来行程存 Outlook 日历（每段一个事件，body 里写结构化元数据：起点/终点/交通/项目/停留/要点/时限），
  出发前用 trip_check 查重叠、赶不及、没留午饭；build_data + server 生成手机「行程模式」页（日 tab、站点卡、一键高德/Apple 导航）
  和桌面交互地图；每日 07:00 cron 把前一天的事件按日聚合归档到 Notion「阅览世界 / 足迹」（自动挂父项目）并删掉 Outlook 事件。
  Master 提及行程时：未来 → 改 Outlook，过去 → 改 Notion。高德 MCP / CLI 负责查景点、算距离、看天气。
---

# 行程管理 trip-manager

```bash
S=~/Projects/garry-skills/trip-manager/scripts      # 下文所有命令的脚本目录
source ~/.hermes/trip-env.sh                        # MS_GRAPH_CLIENT_ID / NOTION_TOKEN / AMAP_API_KEY / AMAP_JS_API_KEY
```

## 数据流

```
规划（高德 MCP 查景点 / 距离 / 天气）
   ↓ outlook_event.py create        ── 每段行程一个事件，body 写元数据
[Outlook 日历] 只放未来行程
   ↓ trip_check.py                  ── 出发前：重叠 / 赶不及 / 跨度 / 午饭 / 缺要点
   ↓ build_data.py --outlook        ── data.json
   ↓ server.py                      ── 手机行程模式 + 桌面地图（局域网访问）
[每日 07:00 cron] notion_sync.py archive-yesterday
   ↓ 按日聚合 → Notion 足迹（1 天 1 页，自动挂父项目）→ 删 Outlook 事件
[Notion 阅览世界 / 足迹] 只放已发生行程（打分 / 短评 / 复盘）
   ↓ build_data.py --notion "项目名"   ── 旅行结束后回看地图
```

Master 提到某段行程时用 `trip_modify.py 关键词 …`：未来（Outlook 里能找到）改 Outlook，否则改 Notion。

## 行程契约（Outlook 事件怎么写）

一个事件 = 一个站点或一段交通。**标题**建议 `Day2-1: 🏔 双桥沟`（`DayN` 前缀用于归档聚合与地图 tab，首个 emoji 变成 Notion icon）。
**body** 里的 `键：值` 行是 Outlook ↔ Notion ↔ 地图之间唯一的结构化数据（`trip_common.parse_meta`），其余行是自由描述：

| 键 | 含义 | 例子 | 谁用 |
|---|---|---|---|
| `项目` | 多日行程名，归档时自动挂到同名父页（没有就建） | 川西 10.1-10.7 | 归档、地图标题 |
| `起点` / `终点` | 两个都填 = 交通段（标题里 `A→B` 也算） | 四姑娘山 / 甲居藏寨 | 路线、导航、检查 |
| `交通` | 飞机 / 高铁 / 汽车 / 船 / 步行（自动加 emoji，同时写 category） | 汽车 | Notion select |
| `停留` | 计划停留（`90` / `1.5h`），缺省 = 事件时长 | 1.5h | 站点卡 |
| `要点` | 到了现场要照做的**一条**，借自 travel-guide 的 practical_note | 7:00 前到沟口抢早班观光车 | 站点卡 💡 |
| `时限` | 最晚离开 / 排队上限 / 换乘缓冲，借自 time_guard | 14:00 前必须出沟，否则到不了八美 | 站点卡 ⚠️、检查汇总 |
| `费用` | 预计花费 | 门票 150 + 观光车 70 | 站点卡 |

写事件时的规矩（从 personalized-travel-guide 借来的、对个人行程有用的部分）：

- **不编造**：坐标、车程、营业时间要么用高德工具查到，要么写「待确认」，不要凭印象填。
- **交通段必须有起终点**（元数据或 `A→B` 标题），否则检查脚本会把它当景点算车程；「前往 X / 去 X」开头的标题会被自动识别为交通段。
- **每个景点站至少一条 要点 或 时限**，写"改变现场动作"的话（几点前到、走哪条沟、票在哪买），不写"注意安全、量力而行"。
- **节奏**：一天一个区域一个锚点 + 1–2 个顺路点；11:00–14:30 留 ≥40 分钟吃饭；到达日 / 离开日比中间天轻；同类景点一天 ≤2 个。
- 一本日历上还有 activity-manager 的「💰 权益活动」事件，行程脚本一律按 category 过滤掉，不归档、不检查、不上图。

## 用法

### 1. 规划：查景点 / 距离 / 天气

高德 MCP（`~/.hermes/scripts/amap_mcp.sh`，工具 `amap_geocode / amap_poi_search / amap_route_plan / amap_weather / amap_plan_trip`）或 CLI，见 `amap-tools/SKILL.md`。

### 2. 建行程（Outlook）

```bash
python3 $S/outlook_event.py create \
    --start 2026-10-01T08:30 --end 2026-10-01T12:30 \
    --title "Day2-1: 🏔 四姑娘山·双桥沟" --location "双桥沟" \
    --project "川西 10.1-10.7" --dwell 4h --transport 汽车 \
    --note "7:00 前到沟口抢早班观光车；布达拉峰→珠噶纳措要徒步" \
    --guard "12:30 前出沟，否则甲居藏寨来不及" --cost "门票 80 + 观光车 70"

# 交通段：填起点 + 终点
python3 $S/outlook_event.py create --start 2026-10-01T13:00 --end 2026-10-01T15:30 \
    --title "Day2-2: 🚗 四姑娘山→甲居藏寨" --origin 四姑娘山 --destination 甲居藏寨 --transport 汽车 --project "川西 10.1-10.7"

python3 $S/outlook_event.py list --start 2026-10-01T00:00:00+08:00 --end 2026-10-08T00:00:00+08:00 [--json]
python3 $S/outlook_event.py delete --id <event id>
```

时间不带时区按北京时间；`--dry-run` 只打印将提交的 JSON。

### 3. 出发前检查

```bash
python3 $S/trip_check.py --start 2026-09-29 --end 2026-10-07 --region 四川省
python3 $S/trip_check.py --next 30 --no-route          # 不查高德车程
```

⛔ 重叠 / 赶不及（高德驾车耗时 > 两站之间留出的时间 + 10 分钟）为硬伤，退出码 1；⚠️ 跨度 > 13 小时、站点 > 6、没留午饭、到达/离开日过满；💡 缺地点、缺要点/时限；末尾汇总每天的 ⏰ 时限。`--region` 是地理编码前缀（消歧义）。

### 4. 手机行程模式 / 桌面地图

```bash
python3 $S/build_data.py --outlook --start 2026-09-29 --end 2026-10-07 --title "川西 10.1-10.7" --region 四川省
python3 $S/build_data.py --notion "川西 10.1-10.7" --region 四川省      # 已归档的行程（按父项目 relation 找子页）
python3 $S/build_data.py --notion --pages <id1>,<id2>                   # 直接给 Day 页 id
python3 $S/server.py            # http://localhost:8899/ ；同时打印手机（同一 Wi-Fi）地址 …/?mode=trip
```

- `?mode=trip`（手机默认）：日 tab（今天高亮）、总览、按时间排的站点卡（停留 / 💡 要点 / ⚠️ 时限 / 费用）、🧭 高德 / 🍎 Apple 一键导航、「✓ 到了」本地打勾。
- 地图模式：高德 JS（key 由 `server.py` 的 `/api/config` 注入，**不写进 data.json**）驾车路线，失败回退 Leaflet + 高德瓦片；点站点看周边 POI。
- 坐标：景点名走高德 POI 搜索，行政区 / 机场 / 酒店走地址编码，互为兜底；缓存在 `~/.cache/trip-manager/geocode.json`，歧义地名（如"甘孜"命中州府）直接改缓存或 `build_data.py` 里的 `AMBIGUOUS_MAP`。查不到就标「无坐标」，不猜。

### 5. 归档到 Notion（cron 或手动）

```bash
python3 $S/notion_sync.py archive-yesterday [--dry-run]
python3 $S/notion_sync.py archive --date 2026-10-01 [--keep-outlook]        # 补归档 / 只写不删
python3 $S/notion_sync.py archive --start 2026-10-01 --end 2026-10-07 --project "川西 10.1-10.7"
```

父项目来自事件的 `项目：`（或 `--project`），同名复用，时间线随归档天数自动延展。

### 6. 修改行程（自动路由）

```bash
python3 $S/trip_modify.py "Day5" --subject "Day5 - 甘孜（改）" --start 2026-10-04T09:00     # 未来 → Outlook
python3 $S/trip_modify.py "Day3" --score "⭐️⭐️⭐️⭐️⭐️" --review "色达震撼"                  # 过去 → Notion
python3 $S/trip_modify.py "Day2" --body "返程遇暴雪，绕道 G317"                              # Notion 追加备注
```

## Notion 写入字段映射

| 来源 | Notion 字段 |
|---|---|
| 聚合标题 `Day2 - 四姑娘山→八美 (3站)` | 名字 |
| 首个非交通 emoji | icon |
| 当天日期 | 时间线 / 上映/发布时间 |
| 路线（起终点 + 地点去重） | 短评 `路线：A → B → C \| 交通：🚗 汽车` |
| 交通（元数据 / category / emoji） | 交通方式 select |
| 每段：`🏔 08:30 双桥沟 · 四姑娘山` + 子项 ⏱ 停留 / 💡 要点 / ⚠️ 时限 / 💰 费用 / 自由描述 | 正文 bullet |
| `项目：` | 父页（类型=足迹）+ 「上级 项目」relation + 正文 mention |

## cron

`trip-archive-yesterday`，每天 07:00，见 `CRON.md`。token 用 device-code 缓存在 `~/.cache/trip-manager/ms_token.json`，过期后手动跑一次 `outlook_event.py list` 登录；日志 `~/.cache/trip-manager/trip-archive.log`。

## 文件

```
scripts/trip_common.py     时区 / body 元数据契约 / 事件抓取与按日聚合 / 高德地理编码缓存（其它脚本共用）
scripts/outlook_event.py   Graph 认证 + create / list / delete
scripts/trip_check.py      出发前一致性检查
scripts/build_data.py      Outlook 或 Notion → travel-guide/data.json
scripts/server.py          静态服务 + /api/poi + /api/config（JS key）
scripts/notion_sync.py     归档到 Notion
scripts/trip_modify.py     未来 / 过去自动路由修改
scripts/amap.py            高德 CLI      scripts/amap_mcp.py  高德 MCP（stdio）
travel-guide/index.html    行程模式 + 地图      travel-guide/data.json  build_data 输出
```
