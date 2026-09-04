---
name: dashboards
description: 通用数据可视化 skill。从 Notion 拉数据 → 智能识别报表需求（天/周/月/年/对比/分布/趋势，不固定维度）→ 用 Plotly 生成交互式 HTML 报表 → 通过 Hermes dashboards plugin 上传，公网可访问。Notion 当数据库（用户录入，skill 转换）、Hermes dashboards plugin 当服务层负责托管和静态文件访问。触发：用户说"生成 X 报告"、"看看 Y 数据"、"做个 Z 可视化"或粘贴数据要求录入 Notion。
version: 0.1.0
author: Hermes Agent
license: MIT
platforms: [macos, linux]
metadata:
  hermes:
    tags: [visualization, dashboards, notion, plotly, reports, charts]
---

# Dashboards — 通用数据可视化

把任意结构化数据 → 交互式 HTML 报表。Notion 是数据源，Plotly 是渲染引擎，Hermes dashboards plugin 是托管层。

## 三种工作模式

### 1. 生成报表（最常见）

用户："看看上月各品类支出分布"

```bash
~/.hermes/hermes-agent/venv/bin/python scripts/render.py \
  --query "上月各品类支出分布" \
  --notion-db <database_id>
```

内部流程：
1. LLM 解析 query → 数据需求（date range、metric、group_by、chart_type）
2. 调 Notion MCP 拉数据（mcp__notion__API_query_a_data_source）
3. 选模板或 LLM 生成 Python + Plotly 代码
4. 渲染 HTML → 用 `API_SERVER_KEY` POST 到 plugin `/api/plugins/dashboards/upload`
5. 返回 `public_url`；最终答复必须把它写成可点击链接

### 2. 录入数据到 Notion

用户：粘贴 CSV/JSON

```bash
~/.hermes/hermes-agent/venv/bin/python scripts/ingest.py \
  --notion-db <database_id> \
  --file ~/Desktop/expenses.csv
```

按 Notion schema 自动转换并写入。

### 3. 列出已有报表

```bash
~/.hermes/hermes-agent/venv/bin/python scripts/list.py
```

调 plugin API 列出所有报表 + 链接。

## 智能解析

`scripts/intent.py` 把自然语言拆成结构化需求：

| 字段 | 说明 | 示例 |
|------|------|------|
| `metric` | 度量字段 | 金额、时长、心率 |
| `group_by` | 分组维度 | 品类、星期、项目 |
| `time_range` | 时间范围 | 上月、本周、Q3、过去 30 天 |
| `granularity` | 时间粒度 | 日 / 周 / 月 / 年 |
| `chart_type` | 图表类型 | pie / bar / line / scatter / table |
| `compare` | 是否对比 | 本月 vs 上月 |

简单需求走 `templates/` 预置模板，复杂需求 LLM 生成 Python 代码。

## 报告体验标准

报告主要在 Phantom 的手机 WebView 中阅读，生成或自由定制 Plotly figure 时必须遵守：

- 页面外壳始终使用 `templates/base.html.tmpl`，不要自行拼一个裸 Plotly 页面。
- 页面标题只出现一次；figure 的 `layout.title` 可以描述图表，但模板会移除与报告标题重复的顶层标题。
- 优先使用 Phantom 色板：紫 `#8b7cff`、绿 `#6bcb9f`、金 `#e0a458`、红 `#ff7b7b`，背景保持透明。
- 手机优先：避免固定宽度、横向溢出和过密刻度；多图报告在 390pt 宽度下仍应可读。
- 必须保留 hover/tap 数据提示；模板同时提供“图表 / 数据”切换，不能用静态截图代替交互图。
- 标题和描述写结论与范围，不写“端到端验收”“fixture”等内部测试术语，除非用户明确要求测试报告。
- 数据源、空状态、加载失败和长文本必须可读；不要依赖颜色作为唯一信息编码。

## 模板

`templates/` 目录：

| 模板 | 用途 |
|------|------|
| `pie_category.html.tmpl` | 分类占比饼图 |
| `bar_compare.html.tmpl` | 多系列对比柱状图 |
| `line_trend.html.tmpl` | 时间趋势折线 |
| `table_summary.html.tmpl` | 汇总表格 |
| `dashboard.html.tmpl` | 综合仪表盘（多图组合） |

模板用 Jinja2，Plotly 通过 CDN 引入（dashboards 是内网/受保护访问，不依赖外网也行）。

## 数据格式约定

skill → plugin 上传时统一用：

```json
{
  "title": "上月各品类支出",
  "description": "2026-07 各品类支出占比",
  "data_source": "notion://<database_id>",
  "chart": {
    "type": "pie",
    "labels": ["餐饮", "交通", "购物", ...],
    "values": [3200, 1500, 2800, ...]
  },
  "filters": {"date_range": "2026-07-01..2026-07-31"}
}
```

plugin 收到后渲染并保存为 `<DASHBOARDS_DIR>/<id>/index.html`，公网访问 URL 为：

```
http://localhost:9119/api/plugins/dashboards/page/<id>
```

（本机 Hermes 经 Phantom 入口暴露后：`http://101.43.41.167:9120/api/plugins/dashboards/page/<id>`

或列表页 `/api/plugins/dashboards/page/`）

## 依赖

- `requests` — HTTP 上传到 plugin
- `plotly` — 图表渲染
- `jinja2` — 模板
- Notion MCP（在 Hermes 会话内可用，无需 API key）

## 配置

`scripts/config.py`:
- `DASHBOARDS_PLUGIN_URL`: 默认 `http://localhost:9119/api/plugins/dashboards`（Hermes dashboard 端口）；dashboard 绑定 WireGuard 地址时设为 `http://10.66.0.5:9119/api/plugins/dashboards`
- `DASHBOARDS_PAGE_BASE`: 默认 `/api/plugins/dashboards/page`；本机 Hermes 给 Phantom 使用时设为 `http://101.43.41.167:9120/api/plugins/dashboards/page`
- 上传 token：优先 `HERMES_SESSION_TOKEN`，否则复用 gateway 已加载的 `API_SERVER_KEY`
- `DASHBOARDS_DIR`: plugin 会写到这里，默认 `~/dashboards/`
- 模板目录：`templates/`

## 安装

```bash
ln -sfnv ~/Projects/garry-skills/dashboards \
    ~/.hermes/skills/productivity/dashboards

pip install requests plotly jinja2
```

## 使用示例

```bash
# 1. 解析意图（dry-run，看 skill 怎么拆解需求）
~/.hermes/hermes-agent/venv/bin/python scripts/intent.py --query "上月各品类支出分布"

# 2. 拉数据 + 渲染 + 上传
~/.hermes/hermes-agent/venv/bin/python scripts/render.py \
  --query "上月各品类支出分布" \
  --notion-db 747e9f3b-0bbf-4f03-b678-7fc62a093790

# 3. 录入数据
~/.hermes/hermes-agent/venv/bin/python scripts/ingest.py --notion-db <id> --file data.csv

# 4. 列出所有报表
~/.hermes/hermes-agent/venv/bin/python scripts/list.py

# 5. 用最新版移动端模板重绘已有报告（保留原 Plotly 数据）
~/.hermes/hermes-agent/venv/bin/python scripts/restyle.py ~/dashboards/<id>/index.html \
  --title "报告标题" \
  --description "报告范围与一句话结论" \
  --created-at "2026-08-28 15:20" \
  --dashboard-id <id>
```

## 与其他 skill / plugin 的关系

- **ride-notion**：可复用其 Notion 写入工具（共享 `~/.hermes/.env` 里的 `NOTION_API_KEY`）
- **dev-tasks**：Notion 任务管理，本 skill 不重叠
- **plugins/dashboards/**：本 skill 的服务层，必须安装并启用

## 已知限制

- v0.1 只支持单 data source；多源 join 待后续版本
- Plotly 图表大小受 CDN 影响，若 Hermes 内网访问可下载离线 Plotly.js 放到 templates/assets/
- 模板只覆盖常见图表，复杂可视化（地图、桑基图等）需 LLM 自由生成
