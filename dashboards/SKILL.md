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
python3 scripts/render.py \
  --query "上月各品类支出分布" \
  --notion-db <database_id>
```

内部流程：
1. LLM 解析 query → 数据需求（date range、metric、group_by、chart_type）
2. 调 Notion MCP 拉数据（mcp__notion__API_query_a_data_source）
3. 选模板或 LLM 生成 Python + Plotly 代码
4. 渲染 HTML → POST 到 plugin `/api/plugins/dashboards/upload`
5. 返回公网 URL

### 2. 录入数据到 Notion

用户：粘贴 CSV/JSON

```bash
python3 scripts/ingest.py \
  --notion-db <database_id> \
  --file ~/Desktop/expenses.csv
```

按 Notion schema 自动转换并写入。

### 3. 列出已有报表

```bash
python3 scripts/list.py
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
http://localhost:8000/api/plugins/dashboards/page/<id>
```

（经 phantom-proxy 暴露后：`https://公网域名/api/plugins/dashboards/page/<id>`

或列表页 `/api/plugins/dashboards/page/`）

## 依赖

- `requests` — HTTP 上传到 plugin
- `plotly` — 图表渲染
- `jinja2` — 模板
- Notion MCP（在 Hermes 会话内可用，无需 API key）

## 配置

`scripts/config.py`:
- `PLUGIN_URL`: 默认 `http://localhost:8000/api/plugins/dashboards`（Hermes 本地端口）
- `DASHBOARDS_DIR`: plugin 会写到这里，默认 `~/dashboards/`
- 模板目录：`templates/`

## 安装

```bash
ln -sfnv ~/Projects/garry-skills/dashboards ~/.claude/skills/dashboards
ln -sfnv ~/Projects/garry-skills/dashboards \
    ~/.hermes/skills/productivity/dashboards

pip install requests plotly jinja2
```

## 使用示例

```bash
# 1. 解析意图（dry-run，看 skill 怎么拆解需求）
python3 scripts/intent.py --query "上月各品类支出分布"

# 2. 拉数据 + 渲染 + 上传
python3 scripts/render.py \
  --query "上月各品类支出分布" \
  --notion-db 747e9f3b-0bbf-4f03-b678-7fc62a093790

# 3. 录入数据
python3 scripts/ingest.py --notion-db <id> --file data.csv

# 4. 列出所有报表
python3 scripts/list.py
```

## 与其他 skill / plugin 的关系

- **ride-notion**：可复用其 Notion 写入工具（共享 `~/.hermes/.env` 里的 `NOTION_API_KEY`）
- **dev-tasks**：Notion 任务管理，本 skill 不重叠
- **plugins/dashboards/**：本 skill 的服务层，必须安装并启用

## 已知限制

- v0.1 只支持单 data source；多源 join 待后续版本
- Plotly 图表大小受 CDN 影响，若 Hermes 内网访问可下载离线 Plotly.js 放到 templates/assets/
- 模板只覆盖常见图表，复杂可视化（地图、桑基图等）需 LLM 自由生成
