# finance-manager · 设计（2026-09-08 定稿 v1）

御主的个人财务：Notion「💸 财务」是唯一真相，Hermes `finance` plugin 是数据层和工具层，本 skill 是 agent 的行为规则。
两个仓库：plugin 独立 repo（`hermes-finance-plugin`，装到 `~/.hermes/plugins/finance`，和 dashboards 一样 submodule），skill 在本仓库。

## 1. 需求

| # | 需求 | 落点 |
|---|---|---|
| R1 | 文字 / 图片 / 语音记录、修改、删除、撤销收支明细 | skill 解析 + `finance_record` / `finance_update` / `finance_delete` |
| R2 | 每月 1 号出上月财务报告 | cron `finance-monthly-report` → dashboards HTML + 阅览世界页 + 飞书一句话 |
| R3 | 随时问财务状况 | `finance_status` / `finance_query`（SQLite 镜像，秒回） |
| R4 | 用 Hermes plugin 管 | `finance` plugin：工具、镜像、报表、校验 |
| R5 | 发余额 / 欠款截图 → 自动写一条调整明细把账面拉平 | `finance_reconcile` |
| R6 | 御主导出账单 CSV，skill 批量导入补空白 | `finance_cli.py import`（去重） |

## 2. 御主已拍板

1. 分类由我重排；二级分类用「两个 select」方案（见 §4）。
2. 转账分情况：**自己账户之间**互转 / 信用卡还款 → 两行（源账户「转账」负数 + 目标账户「转入」正数）；**转给外人** → 一行支出（人情 / 家庭 / 其他）。
3. 记账**不设金额阈值**，拿不准直接问；账户要从截图页面上认出来（§5 账户识别）。
4. 月报写进 Notion「阅览世界」，推送走飞书。
5. plugin 独立 repo，skill 在 garry-skills。
6. 空白由御主导出账单，我导入；**空白从 2026-06-09 起**（最后一条真实记录 2026-06-08）。2026-04（60 条）和 2026-06（35 条）明显偏少，建议导出范围从 **2026-04-01** 起，重叠部分靠去重。
7. 对账差额**直接写调整行**，不确认。

## 3. 现状（2026-09-08 拉取）

- 明细 8010 条，2020-12 → 2026-06-08。3 月 21 日一次性从记账 App 导入 7592 条，另一个集成写了 418 条（图片识别记账）。
- 「类型」当一级分类用，但混了脏值：`支付宝`(1066，其实是导入桶) / `收入`(944) / `餐饮美食`(210，= 餐饮) / `支出`(1) / `期初余额`(13) / 空(677，几乎全是转账)。
- 原 App 的二级分类落在「名称」里（晚餐 1015、午餐 997、饮料水果 347、停车费 242、投资理财 393、红包 257 …），部分带一级前缀（`餐饮-晚餐`、`居家-水电燃气`）。**回填二级分类可以直接从名称做。**
- 转账 668 条全是单行，备注格式固定 `账户互转 | A → B` / `信用还款 | A → B`，对手行可机械补。
- 2026-06-06 做过一轮「对账调整归零」，把 13 个账户余额强行清零，那批调整记成了收入 / 支出，会污染统计，要改成「调整」。
- 账户 20 个，`京东金融` 重复建了两个（120 条 + 2 条）要合并；`8877` 是记录最多的账户（2704 条）但名字只是尾号，需要御主确认是哪张卡；11 条明细没挂账户。

## 4. 分类模型

**Notion 上二级分类的四种做法评估：**

| 方案 | 优点 | 缺点 |
|---|---|---|
| A. 两个 select：一级「类型」+ 新增「子类」 | 录入 / 筛选 / 分组都顺手，API 写入一次请求，回填简单 | Notion 不校验「子类属于哪个一级」，靠 skill / plugin 校验 |
| B. 一个 select 写成「餐饮/晚餐」 | 最省字段 | 选项 60+ 条，按一级分组做不了 |
| C. 独立「分类」库 + relation + rollup | 真层级 | 每次写入先查分类页 id，多一次请求；表格里看着重；御主手工记要点关系 |
| D. 维持现状，二级放名称 | 不改结构 | 名称既是商户又是分类，统计靠字符串匹配 |

**选 A。** 校验表放 `references/categories.md`，plugin 写入前校验，不在表里的组合拒绝并让 agent 问御主。

**一级 → 二级（支出）**

| 一级 | 二级 |
|---|---|
| 餐饮 | 早餐 / 午餐 / 晚餐 / 饮料水果 / 零食 / 聚餐宴请 |
| 交通 | 打车 / 地铁公交 / 共享单车 / 停车费 / 加油 / 过路过桥 / 飞机火车 / 车款车贷 / 车辆保养 |
| 购物 | 日用百货 / 服饰鞋包 / 电子数码 / 家居家电 / 书籍文具 / 其他购物 |
| 居家 | 房款房贷 / 住宿房租 / 水电燃气 / 话费网费 / 物业 / 快递 / 装修 / 会员订阅 / 美发美容 |
| 娱乐 | 运动健身 / 网游电玩 / 影视会员 / 文化休闲 / 旅游度假 |
| 医疗 | 挂号门诊 / 药品 / 体检 |
| 教育 | 课程培训 / 书籍资料 |
| 人情 | 礼金红包 / 转账红包 / 请客送礼 / 借出 |
| 家庭 | 父母养老 / 亲友代付 / 子女 |
| 金融 | 保险 / 利息手续费 / 缴税 / 年费 |
| 投资 | 基金 / 股票 / 理财 |
| 生意 | 营业支出 |
| 其他 | 漏记款 / 未分类 |

**一级 → 二级（收入）**

| 一级 | 二级 |
|---|---|
| 薪酬 | 工资 / 奖金 / 福利补贴 / 公积金 |
| 投资收益 | 理财 / 基金 / 股票 / 利息 |
| 人情收入 | 红包 / 转账红包 / 借入 |
| 退款报销 | 退款返款 / 报销款 / 退税 |
| 生意收入 | 营业收入 |
| 其他收入 | 漏记款 / 未分类 |

**转账 / 调整**：一级「转账」二级「账户互转 / 信用卡还款」；一级「对账」二级「余额调整 / 期初余额」。

**旧值映射**（M4 回填）：`餐饮美食→餐饮`；`支付宝` 桶按名称重判；`收入` 桶按名称拆到收入一级；`医教` 按名称拆 医疗 / 教育；`汽车→交通`；`装修→居家/装修`；`缴税→金融/缴税`；`父母养老→家庭/父母养老`；`亲友代付→家庭/亲友代付`；`酒店旅游→娱乐/旅游度假`；`信用卡`(转账)→`转账/信用卡还款`；`期初余额→对账/期初余额`；`其他`+对账调整→`对账/余额调整`。

## 5. Notion 结构改动

明细库：
- 「类型」select 选项重排为 §4 的一级；「子类」新增 select。
- 「收支类型」加选项 **调整**。统计口径：收入 = 收支类型∈{收入}，支出 = {支出}，转账 / 转入 / 调整只影响账户余额。
- 「指纹」新增 rich_text：`sha1(日期到分钟|金额|账户|名称前 20 字)`，去重用；导入和截图记账都算。
- 「来源」新增 select：`文字 / 截图 / 语音 / 导入 / 对账 / 手工`。

账户库：
- 新增「别名」rich_text（逗号分隔，如 `中信,蚂蚁宝藏卡,中信信用卡`）和「尾号」rich_text（`5571,8877`）。截图识别到「尾号 5571」或「蚂蚁宝藏卡」就能落到账户，识别表在 Notion 里，御主自己能改。
- 合并两个「京东金融」；确认 `8877` 是哪张卡并改名。
- 「余额」公式保留给 Notion 页面看，程序一律用镜像算。

## 6. plugin `finance`（`~/.hermes/plugins/finance`）

```
plugin.yaml            kind: standalone, requires_env: NOTION_TOKEN
__init__.py            register: tools + pre_llm_call 不要；只注册工具和一个 hook 占位（Hermes 要求至少一个 hook）
ledger.py              SQLite ~/.hermes/finance.db：detail / account / sync_state；增量同步按 last_edited_time，夜间全量
notion.py              Notion REST（2025-09-03 data_source 接口），带重试和限速
rules.py               分类校验、账户解析（名称 / 别名 / 尾号）、转账拆行、指纹
reconcile.py           截图对账：账面余额（截至截图时刻）→ 差额 → 调整行
report.py              月报聚合 + Jinja2 渲染（模板在 skill 的 templates/）+ dashboards 上传 + 阅览世界写页
tools_record.py        finance_record / finance_update / finance_delete
tools_query.py         finance_query / finance_status
tools_report.py        finance_report
tools_reconcile.py     finance_reconcile
tools_sync.py          finance_sync
tests/
```

工具契约：

| 工具 | 入参 | 行为 |
|---|---|---|
| `finance_record` | `items[]`: {date, amount(正数), io(收入/支出/转账), category, subcategory, account, to_account?, name, note?, source} | 校验 → 指纹去重（命中返回已有 id，不重复写）→ 转账且 to_account 是自己账户则写两行 → 写 Notion → 更新镜像 → 返回 id 列表和一句话摘要 |
| `finance_update` | `id` 或 `locate`: {recent: N, text} + `patch` | 定位（多条候选返回让 agent 问）→ patch Notion → 镜像 |
| `finance_delete` | `id` / `locate` | Notion 归档（可恢复）→ 镜像标记；返回可撤销 id |
| `finance_query` | `from, to, io?, category?, subcategory?, account?, keyword?, limit?` | 镜像查询，返回明细 + 合计 |
| `finance_status` | `month?` | 本月至今收入 / 支出 / 结余、各账户余额、和上月同期比、Top 5 分类 |
| `finance_reconcile` | `account, target_balance, at, evidence?` | 信用卡欠款由 agent 换成负数再传；差额 ≠ 0 写一行「调整」；返回账面 / 实际 / 差额，附该账户最近 5 笔供 agent 提示 |
| `finance_report` | `month` | 聚合 → HTML → dashboards → 阅览世界页 → 返回两个链接 |
| `finance_sync` | `full?` | 同步 + 体检（不成对的转账、不在白名单的分类、没账户的明细） |

## 7. skill `finance-manager`（本目录）

```
SKILL.md                    触发词、解析规则、什么时候问、回话格式
CRON.md                     finance-monthly-report 蓝图
DESIGN.md                   本文
references/categories.md    §4 白名单 + 旧值映射
references/accounts.md      账户识别线索（App 名 / 卡面 / 尾号）→ 账户
references/parse-examples.md  文字 / 截图 → items[] 样例（支付宝账单页、微信账单页、银行 App 明细、信用卡账单、余额页）
scripts/finance_cli.py      record / query / status / report / sync / import / reconcile；Claude Code 与 cron 用，直接 import plugin 模块
scripts/monthly_report.sh   cron 入口（经 _skill_cron.sh）
（月报模板在 plugin 仓库 templates/monthly.html.tmpl，渲染器和模板放一起）
```

行为规则要点：
- 文字：「午饭 28 支付宝」→ 支出 / 餐饮 / 午餐 / 支付宝 / 今天。没说账户 → 问；没说分类但能从商户判断 → 直接记。
- 截图：先判页面类型（账单列表 / 单笔详情 / 余额页 / 信用卡账单），列表页一次出多条；余额页走 `finance_reconcile`。
- 语音：网关 STT 已转文字，同文字。
- 修改：「刚才那笔」= 本会话最近一次 record 的 id；「昨天加油那笔」= locate。
- 写完回一句：`记了：午餐 ¥28 · 支付宝 · 餐饮/午餐`。多条回列表加合计。
- 每次写入顺手 `phantom_event_write source=agent:finance salience=0.1`。

## 8. 对账（R5）规则

- 储蓄卡 / 支付宝 / 微信 / 公积金 / 投资：截图余额即目标。
- 信用卡：目标 = −当前总欠款；不用「本期应还」「可用额度」。
- 一图多账户（支付宝总资产页、银行首页）：拆成多个 reconcile 调用，逐个汇报。
- 账面余额算到截图时刻；差额 = 目标 − 账面；≠ 0 写「对账 / 余额调整」，日期取截图时刻，备注 `对账 · 截图 <时间> · 账面 X → 实际 Y · 差 Z`。
- 差额和该账户最近某笔金额相同 → 汇报里提一句，御主可选择改真实明细。
- 同一张图重发差额为 0，不写。

## 9. 月报（R2）

cron `finance-monthly-report`，`0 8 1 * *`，no-agent：`~/.hermes/scripts/finance-monthly-report.sh` → `_skill_cron.sh` → `scripts/monthly_report.sh` → `finance_cli.py report --month last`。
内容：收入 / 支出 / 结余、环比、分类占比（一级，可展开二级）、Top 商户、大额单笔 Top 10、各账户月初月末余额、未对账提示（30 天没 reconcile 的账户）。
落地：dashboards HTML（链接）+ 阅览世界一页（类型待定，建议新增「财务」）+ `phantom_notify level=L1 kind=finance` 一句话带链接。

## 10. 里程碑

| 期 | 内容 | 验收 |
|---|---|---|
| M0 | Notion 结构改动（§5）、账户别名 / 尾号补齐、确认 8877 | 御主在 Notion 看到新字段 |
| M1 | plugin 数据层 + `record / query / status / sync` + skill 文字记账 | 飞书说「午饭 28 支付宝」入库；问「这个月花了多少」秒回 |
| M2 | 截图 / 语音、`update / delete`、去重、`reconcile` | 发账单截图出多条；发余额截图账面拉平 |
| M3 | 月报 cron + 模板 + 阅览世界 + 飞书推送 | 10 月 1 日 08:00 收到 9 月报告 |
| M4 | 历史治理：分类回填、转账补对手行、6 月调整改「调整」、CSV 导入 | `finance_sync` 体检零告警 |

## 11. 待御主确认

- `8877` 是哪张卡。
- 阅览世界里月报用哪个「类型」值（现有值我没查，建议新增「财务」）。

## 11.5 录入口（2026-09-08 御主决定）

御主继续在钱迹 App 记账，本系统靠钱迹导出定期导入（`finance_cli.py import`，分钟 + 金额去重），等流程完备再切换到直接对话记账。飞书零星记账和截图记账照常可用，导入时不会重复。每月 1 号 07:30 提醒导出，08:00 出月报，导入后 force 重做。中信银行信用卡 2026-09-08 起已销户，账面已归零。

## 11.6 信用卡信息与日历提醒（2026-09-08）

账户库新增「额度 / 出账日 / 还款日 / 提醒系列」。`scripts/card_calendar.py sync` 为每张使用中的信用卡建 Outlook 月度重复事件（出账 09:00、还款 10:00，category「💳 信用卡」，trip-manager 的 `IGNORE_CATEGORY_WORDS` 已加「信用卡」）。已录：浦发银行信用卡 额度 100,000、出账 25 日（还款日待补）。其余五张卡的三个数待御主提供。

## 11.7 报告怎么送达（2026-09-08）

御主要 HTML 形式的报告。dashboards 的公网链接（9118）在 Phantom 门后，飞书里点开是 `no_token` 401，只有 Phantom App 能开。所以月报推送 = 飞书一句话 + 链接 + **HTML 文件**（`scripts/feishu_file.py`，用网关自己的飞书应用凭证上传 `im/v1/files` 再发 file 消息）。副本在 `~/.hermes/finance-reports/`。

## 12. 进度

- 2026-09-08 M0 完成：明细库加「子类 / 指纹 / 来源」，类型补齐新一级，收支类型加「调整」；账户库加「别名 / 尾号 / 状态」，`8877` 改名「广发银行信用卡(8877)」已销户，重复的「京东金融」合并；阅览世界「类型」加「财务」。
- 2026-09-08 M1 完成：plugin `~/Projects/hermes-finance-plugin`（→ `~/.hermes/plugins/finance`，已启用），七个工具全部可用，9 个单元测试通过；真实 Notion 全量同步 8010 条 97 秒，状况查询即时；记账 / 去重 / 改 / 转账成对 / 删 / 对账真实回归通过（测试行已归档）。skill 文件：SKILL.md、references/{categories,accounts,parse-examples}.md、scripts/finance_cli.py、CRON.md。
- 2026-09-08 M3 完成：`finance_report` 工具 + `finance_cli.py report`，模板在 plugin 仓库 `templates/monthly.html.tmpl`；cron `finance-monthly-report`（`0 8 1 * *`，下次 2026-10-01 08:00）已建；用 2026-05 真实数据跑通：dashboards 上传、阅览世界「2026-05 财务月报」页（类型=财务，47 个块）、飞书 L1 送达。历史月份的账户余额 / 净资产在 M4 回填前不可信（单行转账 + 6 月归零调整记成了收支）。
- 2026-09-08 M4 第一步完成：钱迹导出（2025-06 → 2026-09-08，1338 条）按 2026-04-01 起导入：新写 289 条（8 组转账成对），与 Notion 已有的 181 条按「分钟 + 金额」去重（4、5 月几乎全重复，证明 Notion 里那段本来就是钱迹来的），14 条钱迹「平账」跳过，3 条钱迹内部重复跳过。新建账户「浦发银行储蓄卡」（工资现在打这里）。映射表在 plugin `importers.py`；`finance_cli.py import --file X.xlsx [--apply]` 默认预演。
- 2026-09-08 M4 第二步（历史治理）跑批：plugin `backfill.py` + skill `scripts/backfill_m4.py`。三件事：① 8010 条按旧类型 + 名称 + 备注回填一级 / 子类（旧数据 7593 条只有日期没时间，分不出哪一餐的记「餐饮/其他餐饮」）；② 34 条期初余额 / 对账调整改「调整」类型；③ 旧导出把转入方记成了负数的「转账」（备注「转入←X」，324 条），翻正并改成「转入」，另 20 条「A → B」补对手行；所有对账锚点（期初余额 / 对账调整）按跑批前快照重新求解，锚点时刻的余额不变。最后把旧的「类型」选项从 Notion 里删掉。
- 2026-09-08 M4 跑批完成（三次重启，每步幂等）：7910 条分类改动、20 条对手行、34 个锚点重解、13 个旧「类型」选项删除；健康检查：旧分类 0、缺子类 0、不成对转账 0、无账户 16（11 条旧数据 + 5 条钱迹空账户）。核对：所有锚点时刻余额与求解目标一致，所有使用中账户的当前余额与跑批前完全相同（净资产差额只来自浦发信用卡对账）。代价：2026-03-22 的「期初余额」行吸收了历史转入方向错误，金额变成很大的负数（例如中国银行 −156 万），属于「调整」类型不进统计；6 月 6 日之前的账户余额历史本来就不可信，这次没有变得更差，也没有修好，只有 6 月 6 日之后可信。
- 待做：M2 截图流程实战验证（规则已写在 SKILL.md，需要御主发真实截图试）；M3 月报；M4 历史治理（分类回填 3013 条旧值、8010 条补子类、668 条转账补对手行、6 月调整改「调整」、CSV 导入）。
