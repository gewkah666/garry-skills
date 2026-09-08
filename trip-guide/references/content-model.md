# guide.json 内容模型

改编自 personalized-travel-guide-skill 的八章模型，去掉了对个人行程没用的部分（图片流水线、Google 评分探测、英语备用版）。
所有文本用中文；名称里可带当地语言。`status: "pending"` 表示待确认，页面会显示标记但不阻塞生成。

## 顶层

```jsonc
{
  "meta": {
    "title": "川西 · 国庆自驾",        // 封面第一行，中文，不重复日期 / 人数
    "kicker": "ITINERARY",             // 封面第二行，固定
    "destination": "川西（甘孜 / 阿坝）",
    "start": "2026-09-29", "end": "2026-10-07",
    "travelers": "2 人 · 自驾", "pace": "紧凑 / 适中 / 松弛", "vehicle": "大众揽境四驱（一嗨）",
    "cover": "",                        // 可选：封面图 URL 或相对路径
    "sources": ["…"],                   // 全局来源；卡片级来源写在各自的 source
    "generated_at": "2026-09-07 17:00"
  },
  "legs": [ … ], "stays": [ … ],
  "days": [ … ],
  "sights": [ … ], "food": { … }, "experiences": [ … ], "shopping": [ … ],
  "prep": { "essentials": [ … ], "confirm": [ … ] },
  "notes": { "weather": [ … ], "culture": [ … ], "transport": [ … ], "safety": [ … ], "payment": [ … ] },
  "language": [ … ]
}
```

## 出行框架（不编号）

```jsonc
"legs": [{ "type": "✈️ 飞机", "from": "杭州萧山", "to": "成都双流", "depart": "2026-09-29T20:50", "arrive": "2026-09-29T23:55",
           "ref": "CA4567", "status": "confirmed | pending", "note": "落地取车，一嗨 T2 门店" }],
"stays": [{ "from": "2026-09-30", "to": "2026-10-01", "name": "四姑娘山觅宿酒店", "area": "四姑娘山镇", "address": "…",
            "status": "confirmed | pending", "note": "海拔 3200m，含氧" }]
```

没有预订信息就留 `status: "pending"`，卡片显示「待确认」。

## 01 每日行程 `days[]`

由 `init_guide.py` 从 trip-manager 生成，agent 只补 `summary / photo / fallback` 和站点的 `note / guard / details`。

```jsonc
{
  "day": "Day2", "date": "2026-10-01", "icon": "🏔", "title": "双桥沟→八美镇",
  "area": "四姑娘山 → 丹巴 → 道孚",                 // 一天一个区域
  "summary": "上午 4 小时速通双桥沟精华段，下午甲居藏寨压缩到 1.5h，天黑前到八美。",  // 按实际顺序写清转场理由
  "transport": "🚗 汽车", "route": ["双桥沟", "甲居藏寨", "八美镇"],
  "stops": [{
    "time": "08:30", "end_time": "12:30", "name": "四姑娘山·双桥沟", "icon": "🏔", "is_transit": false,
    "place": "双桥沟", "coords": { "lng": 102.7697, "lat": 30.9801 },     // 没坐标 → 去掉 coords 并加 "status": "pending"
    "dwell_min": 240, "cost": "门票 80 + 观光车 70",
    "note": "观光车直达红杉林自上而下玩；布达拉峰→珠噶纳措往返 2km 必须走到湖边",   // 改变现场动作的一条
    "guard": "12:30 前出沟，否则甲居藏寨来不及",                                       // 最晚离开 / 排队上限 / 换乘缓冲
    "transfer": { "minutes": 175, "km": 118.6 },                                       // 到下一站的驾车（init 自动算）
    "details": ["h2|⏱ 4h 速通动线", "bul|观光车直达最高点**红杉林** → 自上而下玩", "num|…"],   // 展开详情，h2|/bul|/num| 行，**粗体**
    "source": "四姑娘山景区官方公众号 2026-08"
  }],
  "photo": [{ "when": "08:40 观光车上山", "where": "红杉林站下车往回看", "how": "逆光拍雪山剪影，长焦压缩" }],  // 每天 2–3 条，各天不同
  "fallback": "若双桥沟限流：改长坪沟入口徒步 2h，13:30 前必须出发去甲居"
}
```

节奏规则：一天一个区域一个锚点 + 1–2 个顺路点；11:00–14:30 留 ≥ 40 分钟；到达 / 离开日轻；同类景点一天 ≤ 2；`transfer.minutes` 不能大于到下一站的空档（校验会拦）。

## 02 景点 `sights[]`

6–10 个首次到访值得的地方，分 `scheduled`（已排进行程）和 `optional`（备选）。

```jsonc
{ "name": "色达喇荣五明佛学院", "local_name": "ལ་རུང་སྒར་", "area": "色达县洛若镇", "day": "Day4", "status": "scheduled | optional",
  "hours": "观光车 9:00 / 10:15 两班；山顶限 60 分钟", "duration": "3h（含集合）", "best_time": "上午，坛城顺光",
  "ticket": "线下提前一天购票", "caution": "仅坛城转经筒区域开放，僧舍区禁行", "coords": { "lng": 100.4725, "lat": 32.1505 },
  "image": "", "source": "色达文旅公众号 2026-09 通告", "why": "为什么值得：一句话" }
```

## 03 美食 `food`

```jsonc
{ "primer": ["点菜：藏餐馆先问有没有『汉餐』菜单", "高原水 90℃ 沸，火锅要多煮", "…"],        // 3–6 条读菜单 / 点单常识
  "snacks": [{ "name": "牦牛酸奶", "what": "厚、酸、撒白糖", "where": "塔公路边摊", "how": "现舀现吃，10 元一碗" }],   // 恰好 4 个
  "restaurants": [{ "name": "…", "cuisine": "藏餐 / 川菜 / 火锅", "scene": "正餐 / 快餐 / 夜宵", "dishes": "…", "price": "60–90 / 人",
                    "hours": "…", "area": "…", "day": "Day3", "image": "", "source": "…" }],                     // ≥ 4 家，≥ 3 种菜系
  "chains": [{ "name": "…", "why": "…" }] }                                                                     // 2–4 个兜底连锁
```

## 04 体验 `experiences[]`

2–3 类，每类 2 个：`{ "category": "文化 / 户外 / 手作 / 泡汤", "name", "what", "where", "when", "cost", "book": "需预约 / 现场", "source" }`。凑不满就少写，不填充。

## 05 购物 `shopping[]`

`{ "name", "type": "市集 / 特产店 / 商场", "area", "what": "买什么", "note": "怎么挑 / 带回家注意", "source" }`，末尾可加 `"souvenir": true` 的伴手礼条目。

## 06 出发前 `prep`

两组各 ≥ 6 条，按目的地和实际行程写（高反、加油、现金、离线地图、证件、预约）：

```jsonc
{ "essentials": [{ "text": "便携氧 ×2 + 葡萄糖", "why": "Day4–6 连续 3900m+ 过夜" }],
  "confirm": [{ "text": "色达佛学院观光车票（提前一天线下）", "when": "Day3 晚" }] }
```

## 07 当地须知 `notes`

固定五折：`weather / culture / transport / safety / payment`，每折 3–4 条 `{ "title": "决策导向的小标题", "text": "两句：当地情况 + 动作 / 例外 / 兜底（≥ 34 字）" }`。禁止「提示 1 / 提示 2」。

## 08 语言 `language[]`（出境才填）

`{ "group": "点餐", "items": [{ "term": "…", "say": "读音", "meaning": "…" }] }`，每组 ≥ 5 条。

## 研究标准

- 不编造：地址、坐标、营业时间、门票、评分、价格、预约规则。查到才写并带 `source`；查不到写「待确认」+ `status: "pending"`。
- 证据顺序：官方 > 平台 > 社区帖。社区帖用于找模式（几点排队、哪条沟值得），不用于开放状态与安全结论。
- 拒绝套话：「注意安全 / 量力而行 / 合理安排时间 / 保持体力 / 提前规划」这类不改变动作的句子不要出现在 `note / guard / notes`。
- 每天的 `photo` 必须不同；不写「多拍照」。
- 内容够就停：达到各章下限后，不为「更多候选」继续研究。
