---
name: trip-guide
description: >
  旅行手册生成 skill。把一次行程做成一份可离线看的单文件 HTML 手册（手机优先，桌面有章节侧栏）：
  行程骨架直接从 trip-manager（Outlook 未来行程 / Notion 已归档行程）导入，agent 按章节做研究填 guide.json
  （每日行程 + 站点要点/时限/转场车程/手绘路线图、景点、美食、体验、购物、出发前清单、当地须知、语言），
  validate_guide 审计后 build_guide 渲染，可发布到 Hermes dashboards 公网访问。
  触发：御主说"做一份攻略 / 旅行手册 / guide / handbook"、"把川西行程整理成手册"。
---

# 旅行手册 trip-guide

```bash
G=~/Projects/garry-skills/trip-guide/scripts
S=~/Projects/garry-skills/trip-manager/scripts
source ~/.hermes/trip-env.sh          # NOTION_TOKEN / MS_GRAPH_CLIENT_ID / AMAP_API_KEY
```

产物：`trip-guide/output/<slug>/guide.json`（唯一数据源，agent 直接编辑）→ `guide.html`（单文件，数据内嵌，离线可看）。各卡 `source` 字段支持 markdown 链接（模板 srcHtml 渲染为可点 `<a target=_blank>`）——引用调研帖时把 `[♥赞数 标题](链接)` 附在 source 尾部，御主要求攻略必带来源原帖链接。

## 流程

```
1. 骨架   init_guide.py      行程 / 站点 / 坐标 / 转场车程 从 trip-manager 来，其余章节留空
2. 研究   agent 逐章填 guide.json（高德 MCP 查坐标营业信息，web 搜索查门票 / 管控 / 口碑，已有的 ~/xhs_trip 研究直接合并）
3. 审计   validate_guide.py  硬伤（缺字段 / 套话）退出码 1；--strict 把 ⚠️ 也当硬伤
4. 渲染   build_guide.py     guide.html；--open 本地预览；--serve-copy 复制到 trip-manager 的 travel-guide/ 手机局域网看
5. 发布   publish_guide.py   上传 Hermes dashboards plugin → 公网 URL
```

行程改了（Outlook 事件变动）只要 `init_guide.py --refresh-days`，其它章节内容保留。

反过来，在 guide.json 里改了行程（时间 / 加站 / 砍站）要回写日历：`python3 $G/sync_outlook.py output/<slug>/guide.json --project "川西 10.1-10.7" [--dry-run]`——先备份并删掉行程日期内的旧行程事件（权益活动不动），再按 `days[].stops[]` 逐站建事件（标题 `DayN-k: icon 名称`，body 写项目 / 起终点 / 交通 / 停留 / 要点 / 时限 / 费用）。之后 `trip_check.py` 照常能查。两边改完以 guide.json 为准，别在 Outlook 里手改再 --refresh-days 覆盖。

## 1. 骨架

```bash
# 从 trip-manager 已生成的 data.json（推荐：先 build_data.py --outlook … 再来）
python3 $G/init_guide.py --from-data ~/Projects/garry-skills/trip-manager/travel-guide/data.json \
    --slug chuanxi-2026 --title "川西 · 国庆自驾" --destination "川西（甘孜 / 阿坝）" --travelers "2 人 · 自驾" \
    --notes ~/xhs_trip/place_content.json          # 可选：按站点名合并已有研究（h2|/bul|/num| 行）

# 或直接从 Outlook / Notion
python3 $G/init_guide.py --outlook --start 2026-09-29 --end 2026-10-07 --region 四川省 --slug chuanxi-2026 --title "川西 · 国庆自驾"
python3 $G/init_guide.py --notion "川西 10.1-10.7" --region 四川省 --slug chuanxi-2026
```

骨架会：按 `days[].stops[]` 放好时间 / 地点 / 坐标 / 要点 / 时限；相邻两站有坐标就查高德驾车得到 `transfer`（分钟 / 公里）；`sights` 用行程里的景点预填名字和归属日（其它字段空）；`prep` 放通用清单种子；其余章节为空数组。

## 2. 研究与填写（agent 的工作）

内容规则见 `references/content-model.md`，要点：

- **只有 guide.json 是数据源**。不要另写 markdown、不要在对话里堆内容，直接改 JSON。
- **不编造**：地址、坐标、营业时间、门票、评分、价格、预约规则，查到才写，写就带 `source`；查不到写「待确认」并保留 `status: "pending"`，页面会标出来，不会卡住生成。
- **每站一条能改变现场动作的 `note`，一条 `guard`**（几点前到 / 排队上限 / 最晚离开），不要"注意安全、量力而行"这类套话，校验会拦。
- **有界研究**：景点 6–10 个、餐厅 4–8 家、小吃 4 个、体验 2–3 类每类 2 个、清单 ≥ 12 项、须知 5 折每折 3–4 条。够了就停，不为凑数加内容。
- **证据顺序**：官方（景区 / 政府 / 航司）> 平台（携程 / 大众点评 / 高德 POI）> 社区帖（小红书 / 马蜂窝，只用来找模式，不单独作为安全 / 开放状态依据）。
- 国内行程默认不生成「语言」章；出境才填 `language`。
- 已有的 `~/xhs_trip/place_content.json` 这类研究，用 `--notes` 合并进站点的 `details`，不要手抄。

高德工具（trip-manager 的 MCP：`amap_poi_search / amap_geocode / amap_route_plan / amap_weather`）用来拿坐标、地址、电话、评分、车程；营业时间和门票走 web 搜索核对官方。

## 3. 审计

```bash
python3 $G/validate_guide.py output/chuanxi-2026/guide.json [--strict]
```

⛔ 缺标题 / 日期 / 站点、套话、转场时间比空档长；⚠️ 章节数量不足、站点无坐标且未标待确认、须知太短；💡 缺 source / 照片提示 / TODO。修到没有 ⛔ 再渲染。

## 4. 渲染与预览

```bash
python3 $G/build_guide.py output/chuanxi-2026/guide.json --open
python3 $G/build_guide.py output/chuanxi-2026/guide.json --serve-copy   # → trip-manager/travel-guide/guide.html，server.py 起来后手机访问 /guide.html
```

图片：`meta.cover` / `sights[].image` / `food.restaurants[].image` / `days[].stops[].image` 填 guide.json 旁的相对路径（如 `img/seda.jpg`，720px 宽 · JPEG q58 ≈ 40–80 KB 一张），`build_guide.py` 会转成 data URI 内嵌，单文件离线仍可看；同级 `image_credit` / `meta.cover_credit` 渲染为图注（Wikimedia Commons 的 CC 图必须写「作者 · 许可 · Wikimedia Commons」）。商用图库和小红书图不要用；找不到实景就留空，别用 AI 生成图冒充实景。

页面：封面 → 出行（航段 / 住宿：note + `alternatives[]` 备选酒店折叠清单）→ 01 每日行程（先是全程一览表：每天一行 路线 / 公里 / 驾驶 / 海拔 / 住宿，点行切日；再日 tab、summary 按句拆成短行、「今日红线」汇总各站 guard、站点卡：停留 / 💡 要点 / ⚠️ 时限 / 转场车程 / 展开详情 / 高德 & Apple 导航；`days[]` 可选 `km / alt / drive` 渲染为 🛣里程 / ⛰海拔 / 驾驶时长）→ 02 景点（已排进行程的只留一句话 + 折叠票务 + 「看 DayN」回链，避免与站点卡重复；备选才出完整卡）→ 03 美食 → 04 体验 → 05 购物 → 06 出发前（可勾选）→ 07 费用预算（可选章 `g.budget = {intro, lines:[{item,est,note,status}], total, source}`）→ 08 当地须知（5 折）→ 09 语言 → 来源。空章节自动隐藏；深色 / 浅色切换；可打印。

模板通用规则：所有 `source` 折叠在「来源」后面；正文里的裸 URL 自动缩成「域名 ↗」链接；文本里的 `(lng,lat)` 坐标串不显示；转场分钟数显示成「x 小时 y 分」；手绘路线 SVG 已去掉（日头的文字路线链足够）。

发布更新：`publish_guide.py guide.html --title … --update <dash_id>` 原地覆盖 ~/dashboards/<id>/index.html **链接不变**（id 在 output/<slug>/published.json）。公网页有 Phantom token 门，curl 直接验证会 401——以本地 ~/dashboards/<id>/index.html 与产物比对为准，别误判发布失败。

## 5. 发布

```bash
python3 $G/publish_guide.py output/chuanxi-2026/guide.html --title "川西 · 国庆自驾"
```

对外分享（不需要 Phantom 令牌）：`publish_guide.py output/<slug>/guide.html --title … --share [slug]` 把同一份 HTML 再放一份到云 VM，链接形如 `http://101.43.41.167/s/<slug>/?t=<token>`，微信 / Safari 直接打开；再跑一次 `--share` 是原地更新、链接不变；`--revoke-share` 撤销。底层是 `~/Projects/phantom/phantom-infra/share.sh`（nginx `/s/` + token→slug map），http 明文、令牌就在 URL 里，只给手册 / 报告这类内容用。分享记录写在 `published.json` 的 `share` 字段。

走 dashboards skill 的上传契约（`API_SERVER_KEY` → `/api/plugins/dashboards/upload`），返回公网 URL；最终答复要给成可点的链接。

## 文件

```
scripts/init_guide.py        骨架（复用 trip-manager/scripts 的 trip_common / build_data）
scripts/validate_guide.py    审计
scripts/build_guide.py       guide.json + assets/template.html → guide.html
scripts/publish_guide.py     上传 dashboards / --share 公网分享副本
scripts/sync_outlook.py      guide.json 的每日行程 → Outlook 事件（删旧建新，先备份）
assets/template.html         渲染模板（window.GUIDE 注入）
references/content-model.md  各章内容契约、字段说明、研究标准
output/<slug>/               guide.json / guide.html（个人数据，不必提交）
```
