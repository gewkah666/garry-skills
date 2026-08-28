"""Render a dashboard report.

Usage:
    python3 scripts/render.py --query "上月各品类支出分布" --notion-db <id>

在 Hermes 会话内运行时，Notion 数据通过 Notion MCP 获取（无需 API key）。
独立运行（无 Notion MCP）时，可通过 --data-file 直接传 JSON。

整个流程：
  1. parse intent
  2. fetch data (Notion MCP / file)
  3. build Plotly figure
  4. render HTML from template
  5. POST to plugin /api/plugins/dashboards/upload
  6. print public URL
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

# 让脚本可独立 import
sys.path.insert(0, str(Path(__file__).resolve().parent))

import intent as intent_mod
from config import PAGE_BASE, PLUGIN_URL, TEMPLATES_DIR, upload_headers


# ---------- 数据获取 ----------

def fetch_from_notion(notion_db: str, intent_obj: intent_mod.Intent) -> list[dict[str, Any]]:
    """从 Notion 拉数据.

    在 Hermes 会话中运行时，应通过 Notion MCP（mcp__notion__API_query_a_data_source）
    获取数据；本函数仅作为占位/契约定义，实际数据由调用方（Hermes skill runtime）
    通过 --data-file 或 stdin 注入。
    """
    raise NotImplementedError(
        "Notion data fetching must happen via Notion MCP in Hermes session. "
        "Provide data via --data-file (JSON list of records) instead."
    )


def load_data_file(path: Path) -> list[dict[str, Any]]:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        raise ValueError(f"Data file must be a JSON array, got {type(data).__name__}")
    return data


# ---------- Plotly figure 构建 ----------

def build_figure(intent_obj: intent_mod.Intent, records: list[dict[str, Any]]) -> dict[str, Any]:
    """根据 intent 和原始 records 构建 Plotly figure dict.

    返回 dict 可以直接 json.dumps 后传给 Plotly.newPlot。
    """
    chart_type = intent_obj.chart_type
    if chart_type == "auto":
        # 兜底：没有 group_by → line（趋势）；有 group_by 且 metric 是累计 → pie
        if intent_obj.group_by:
            chart_type = "pie"
        else:
            chart_type = "line"

    # 简单聚合：按 group_by 字段分组，对 metric 字段求和
    metric_field = _find_field(records, intent_obj.metric) if intent_obj.metric else _find_first_numeric(records)
    group_field = _find_field(records, intent_obj.group_by) if intent_obj.group_by else None

    if chart_type == "pie":
        return _build_pie(records, group_field, metric_field, intent_obj)
    elif chart_type == "bar":
        return _build_bar(records, group_field, metric_field, intent_obj)
    elif chart_type == "line":
        return _build_line(records, group_field, metric_field, intent_obj)
    elif chart_type == "table":
        return _build_table(records, intent_obj)
    else:
        # 兜底
        return _build_bar(records, group_field, metric_field, intent_obj)


def _find_field(records: list[dict], hint: str) -> str:
    """根据 hint（中文关键词）找 records 里的字段名."""
    if not records:
        return ""
    keys = list(records[0].keys())
    # hint 直接命中
    for k in keys:
        if hint in k:
            return k
    # hint 关键词命中
    keywords = {
        "金额": ["金额", "钱", "花费", "支出", "收入", "cost", "price", "amount", "money"],
        "时长": ["时长", "时间", "耗时", "duration", "minutes", "hours"],
        "距离": ["距离", "公里", "km", "distance"],
        "数量": ["数量", "次数", "count", "qty"],
        "心率": ["心率", "hr", "bpm"],
        "卡路里": ["卡路里", "热量", "cal"],
        "品类": ["品类", "类别", "分类", "category", "type"],
        "星期": ["星期", "weekday"],
        "项目": ["项目", "任务", "project", "task"],
        "人": ["人", "用户", "user"],
        "地点": ["地点", "位置", "location", "城市"],
        "标签": ["标签", "tag"],
    }
    candidates = keywords.get(hint, [hint])
    for k in keys:
        for c in candidates:
            if c.lower() in k.lower():
                return k
    return ""


def _find_first_numeric(records: list[dict]) -> str:
    if not records:
        return ""
    for k, v in records[0].items():
        if isinstance(v, (int, float)):
            return k
    return ""


def _safe_number(v: Any) -> float:
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return float(str(v).replace(",", ""))
    except (ValueError, TypeError):
        return 0.0


def _aggregate_by_group(records: list[dict], group_field: str, metric_field: str) -> tuple[list[str], list[float]]:
    buckets: dict[str, float] = {}
    for r in records:
        g = str(r.get(group_field, "未分类"))
        m = _safe_number(r.get(metric_field, 0))
        buckets[g] = buckets.get(g, 0) + m
    # 按值降序
    items = sorted(buckets.items(), key=lambda x: x[1], reverse=True)
    labels = [k for k, _ in items]
    values = [v for _, v in items]
    return labels, values


def _build_pie(records, group_field, metric_field, intent_obj):
    if not group_field or not metric_field:
        raise ValueError("pie chart requires group_by + metric")
    labels, values = _aggregate_by_group(records, group_field, metric_field)
    return {
        "data": [{
            "type": "pie",
            "labels": labels,
            "values": values,
            "hole": 0.4,
            "textinfo": "label+percent",
            "marker": {
                "colors": ["#8b7cff", "#6bcb9f", "#e0a458", "#ff7b7b", "#78a9ff", "#c58cff"],
                "line": {"color": "#15171e", "width": 2},
            },
        }],
        "layout": {
            "title": {"text": intent_obj.query, "font": {"size": 18}},
            "showlegend": True,
        },
    }


def _build_bar(records, group_field, metric_field, intent_obj):
    if not metric_field:
        raise ValueError("bar chart requires metric")
    if group_field:
        labels, values = _aggregate_by_group(records, group_field, metric_field)
    else:
        labels = [str(r.get(_find_first_non_numeric(records), "")) for r in records]
        values = [_safe_number(r.get(metric_field, 0)) for r in records]
    return {
        "data": [{
            "type": "bar",
            "x": labels,
            "y": values,
            "marker": {"color": "#8b7cff"},
        }],
        "layout": {
            "title": {"text": intent_obj.query, "font": {"size": 18}},
            "xaxis": {"automargin": True},
            "yaxis": {"title": {"text": metric_field}},
        },
    }


def _build_line(records, group_field, metric_field, intent_obj):
    if not metric_field:
        raise ValueError("line chart requires metric")
    time_field = _find_time_field(records)
    if not time_field:
        # 没有时间字段就退化为按记录顺序的折线
        labels = [str(i) for i in range(len(records))]
        values = [_safe_number(r.get(metric_field, 0)) for r in records]
    else:
        # 按时间字段排序后画
        sorted_recs = sorted(records, key=lambda r: str(r.get(time_field, "")))
        labels = [str(r.get(time_field, "")) for r in sorted_recs]
        values = [_safe_number(r.get(metric_field, 0)) for r in sorted_recs]
    return {
        "data": [{
            "type": "scatter",
            "mode": "lines+markers",
            "x": labels,
            "y": values,
            "line": {"color": "#8b7cff", "width": 3},
            "marker": {"size": 7, "color": "#8b7cff", "line": {"color": "#15171e", "width": 2}},
        }],
        "layout": {
            "title": {"text": intent_obj.query, "font": {"size": 18}},
            "xaxis": {"title": {"text": time_field or "index"}},
            "yaxis": {"title": {"text": metric_field}},
        },
    }


def _build_table(records, intent_obj):
    if not records:
        return {"data": [], "layout": {}}
    keys = list(records[0].keys())
    values = [[str(r.get(k, "")) for k in keys] for r in records]
    return {
        "data": [{
            "type": "table",
            "header": {
                "values": [f"<b>{k}</b>" for k in keys],
                "fill": {"color": "#1e212b"},
                "font": {"color": "#ecedf1"},
                "line": {"color": "#262a35"},
            },
            "cells": {
                "values": list(zip(*values)) if values else [],
                "fill": {"color": "#15171e"},
                "font": {"color": "#8a90a0"},
                "line": {"color": "#262a35"},
            },
        }],
        "layout": {"title": {"text": intent_obj.query, "font": {"size": 18}}},
    }


def _find_first_non_numeric(records):
    if not records:
        return ""
    for k, v in records[0].items():
        if not isinstance(v, (int, float)):
            return k
    return ""


def _find_time_field(records):
    if not records:
        return ""
    time_keys = ["时间", "日期", "时间线", "date", "time", "datetime", "timestamp", "created"]
    for k in records[0].keys():
        for tk in time_keys:
            if tk in k.lower():
                return k
    return ""


# ---------- 模板渲染 ----------

def render_html(
    title: str,
    description: str,
    data_source: str,
    dashboard_id: str,
    created_at: str,
    figure: dict[str, Any],
    template_name: str = "base.html.tmpl",
) -> str:
    """用 Jinja2 模板渲染 HTML."""
    import jinja2

    env = jinja2.Environment(
        loader=jinja2.FileSystemLoader(str(TEMPLATES_DIR)),
        autoescape=False,  # 模板里要注入 plotly_json，不转义
    )
    tpl = env.get_template(template_name)
    return tpl.render(
        title=title,
        description=description,
        data_source=data_source,
        dashboard_id=dashboard_id,
        created_at=created_at,
        plotly_json=json.dumps(figure, ensure_ascii=False),
    )


# ---------- 上传到 plugin ----------

def upload(html: str, dashboard_meta: dict[str, Any]) -> dict[str, Any]:
    """POST 到 plugin API."""
    import requests

    payload = {
        "html": html,
        "meta": dashboard_meta,
    }
    # The dashboard is a local/WireGuard service. macOS system proxy settings
    # otherwise send 10.66.0.5 through the desktop HTTP proxy and return 502.
    session = requests.Session()
    session.trust_env = False
    resp = session.post(
        f"{PLUGIN_URL}/upload",
        json=payload,
        headers=upload_headers(),
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


# ---------- 主流程 ----------

def main() -> None:
    parser = argparse.ArgumentParser(description="Render a dashboard report.")
    parser.add_argument("--query", "-q", required=True, help="Natural language query")
    parser.add_argument("--notion-db", help="Notion database ID (informational only)")
    parser.add_argument("--data-file", help="JSON file with records (when Notion MCP unavailable)")
    parser.add_argument("--title", help="Override report title")
    parser.add_argument("--description", default="", help="Report description")
    parser.add_argument("--dry-run", action="store_true", help="Don't upload, just print HTML path")
    parser.add_argument("--template", default="base.html.tmpl", help="Template file name")
    args = parser.parse_args()

    # 1. parse intent
    intent_obj = intent_mod.parse(args.query)
    print(f"[intent] {json.dumps(intent_obj.to_dict(), ensure_ascii=False)}", file=sys.stderr)

    # 2. fetch data
    if args.data_file:
        records = load_data_file(Path(args.data_file))
    else:
        print("ERROR: no --data-file provided. In Hermes session, use Notion MCP and inject data.",
              file=sys.stderr)
        sys.exit(1)
    print(f"[data] {len(records)} records loaded", file=sys.stderr)

    # 3. build figure
    figure = build_figure(intent_obj, records)

    # 4. render html
    title = args.title or intent_obj.query
    dashboard_id = f"dash-{int(__import__('time').time())}"
    created_at = __import__('datetime').datetime.now().strftime("%Y-%m-%d %H:%M")
    html = render_html(
        title=title,
        description=args.description,
        data_source=f"notion://{args.notion_db}" if args.notion_db else "",
        dashboard_id=dashboard_id,
        created_at=created_at,
        figure=figure,
        template_name=args.template,
    )

    if args.dry_run:
        out = Path("/tmp") / f"{dashboard_id}.html"
        out.write_text(html, encoding="utf-8")
        print(f"[dry-run] HTML saved to {out}", file=sys.stderr)
        print(str(out))
        return

    # 5. upload
    meta = {
        "id": dashboard_id,
        "title": title,
        "description": args.description,
        "query": args.query,
        "intent": intent_obj.to_dict(),
        "data_source": f"notion://{args.notion_db}" if args.notion_db else "",
        "chart_type": figure["data"][0].get("type", "unknown") if figure.get("data") else "unknown",
        "record_count": len(records),
        "created_at": created_at,
    }
    try:
        result = upload(html, meta)
        # The plugin deliberately returns a deployment-neutral relative URL.
        # A configured public base lets Hermes hand Phantom a directly clickable
        # 9120 URL while preserving the report ID allocated by the plugin.
        if result.get("id") and PAGE_BASE:
            result["public_url"] = f"{PAGE_BASE.rstrip('/')}/{result['id']}"
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except Exception as e:
        # fallback: 写到本地
        out = Path.home() / "dashboards" / dashboard_id / "index.html"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(html, encoding="utf-8")
        meta_out = out.parent / "meta.json"
        meta_out.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Upload failed ({e}); saved locally to {out}", file=sys.stderr)
        print(json.dumps({"local_path": str(out), "public_url": None}, ensure_ascii=False))


if __name__ == "__main__":
    main()
