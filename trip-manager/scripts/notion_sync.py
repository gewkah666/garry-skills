#!/usr/bin/env python3
"""
notion_sync.py - 把 Outlook 上已发生的行程归档到 Notion「阅览世界 / 足迹」

逻辑:
  1. 拉取某一天（默认昨天）的 Outlook calendarView 事件
  2. 按日聚合为 1 个 Notion page（trip_common.aggregate_day）
       名字 = "Day2 - 四姑娘山→八美 (3站)"    icon = 首个非交通 emoji
       类型=足迹  状态=已完成  标签=[足迹, 行程]
       时间线 / 上映/发布时间 = 当天       交通方式 = 首个识别到的交通
       短评 = "路线：A → B → C | 交通：🚗 汽车"
       正文 = 「📋 当日行程」+ 每段一个 bullet，要点 / 时限 / 停留 作为子 bullet
  3. 父项目：事件 body 里写了 `项目：xxx` 就自动挂到同名父 page（没有则创建，一天也建）
     也可以用 --project 手动指定
  4. 归档成功后删除 Outlook 上的这些事件（日历只留未来）

用法:
  notion_sync.py archive-yesterday [--project 川西] [--dry-run]
  notion_sync.py archive --date 2026-10-01 [--keep-outlook]      # 补归档某一天
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import timedelta
from pathlib import Path
from typing import List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
from trip_common import (  # noqa: E402
    NOTION_DB_ID, aggregate_day, day_range, fetch_events, group_by_day, now_cn,
)
from outlook_event import graph_request  # noqa: E402

NOTION_API = "https://api.notion.com/v1"


def notion_token() -> str:
    tok = os.environ.get("NOTION_TOKEN")
    if not tok:
        print("❌ NOTION_TOKEN 未设置（source ~/.hermes/trip-env.sh）", file=sys.stderr)
        sys.exit(1)
    return tok


def notion(method: str, path: str, data: Optional[dict] = None) -> dict:
    req = urllib.request.Request(
        f"{NOTION_API}{path}",
        data=json.dumps(data, ensure_ascii=False).encode() if data is not None else None,
        method=method,
        headers={
            "Authorization": f"Bearer {notion_token()}",
            "Notion-Version": "2022-06-28",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


def _rt(text: str) -> list:
    return [{"type": "text", "text": {"content": text[:2000]}}]


def _bullet(text: str, children: Optional[list] = None) -> dict:
    block = {"object": "block", "type": "bulleted_list_item",
             "bulleted_list_item": {"rich_text": _rt(text)}}
    if children:
        block["bulleted_list_item"]["children"] = children
    return block


def page_title(page: dict) -> str:
    for prop in page.get("properties", {}).values():
        if prop.get("type") == "title":
            return "".join(t.get("plain_text", "") for t in prop.get("title", []))
    return ""


def find_page_by_title(title: str) -> Optional[str]:
    """在 Notion 里找标题完全相同的 page（复用父项目）"""
    try:
        data = notion("POST", "/search", {"query": title, "filter": {"value": "page", "property": "object"}})
    except urllib.error.HTTPError as e:
        print(f"  ⚠️  搜索失败: {e.read().decode()}", file=sys.stderr)
        return None
    for p in data.get("results", []):
        if page_title(p) == title and not p.get("archived"):
            return p["id"]
    return None


def ensure_project(title: str, day_key: str, dry_run: bool = False) -> Optional[str]:
    """同名父项目存在则复用；否则创建（时间线从这天开始，后续归档天数会把 end 往后推）"""
    pid = find_page_by_title(title)
    if pid:
        print(f"  📌 父项目复用: {title}")
        _extend_project_range(pid, day_key, dry_run)
        return pid
    if dry_run:
        print(f"  📌 [dry-run] 将创建父项目: {title}")
        return None
    page = notion("POST", "/pages", {
        "parent": {"database_id": NOTION_DB_ID},
        "properties": {
            "名字": {"title": _rt(title)},
            "类型": {"select": {"name": "足迹"}},
            "状态": {"select": {"name": "已完成"}},
            "标签": {"multi_select": [{"name": "足迹"}, {"name": "行程"}]},
            "上映/发布时间": {"date": {"start": day_key}},
            "时间线": {"date": {"start": day_key, "end": day_key}},
            "短评": {"rich_text": _rt("多日行程")},
        },
        "icon": {"type": "emoji", "emoji": "🧳"},
    })
    print(f"  📌 父项目创建: {title} ({page['id']})")
    return page["id"]


def _extend_project_range(pid: str, day_key: str, dry_run: bool):
    """把父项目的 时间线 扩到覆盖 day_key"""
    try:
        page = notion("GET", f"/pages/{pid}")
        cur = (page["properties"].get("时间线") or {}).get("date") or {}
        start, end = cur.get("start") or day_key, cur.get("end") or cur.get("start") or day_key
        new_start, new_end = min(start, day_key), max(end, day_key)
        if (new_start, new_end) != (start, end) and not dry_run:
            notion("PATCH", f"/pages/{pid}", {"properties": {"时间线": {"date": {"start": new_start, "end": new_end}}}})
    except Exception as e:  # noqa: BLE001
        print(f"  ⚠️  父项目时间线更新失败: {e}", file=sys.stderr)


def build_page(day: dict, parent_id: Optional[str]) -> dict:
    props = {
        "名字": {"title": _rt(day["title"])},
        "类型": {"select": {"name": "足迹"}},
        "状态": {"select": {"name": "已完成"}},
        "标签": {"multi_select": [{"name": "足迹"}, {"name": "行程"}]},
        "上映/发布时间": {"date": {"start": day["day_key"]}},
        "时间线": {"date": {"start": day["day_key"]}},
    }
    review = []
    if day["route"]:
        review.append("路线：" + " → ".join(day["route"]))
    if day["transport"]:
        review.append("交通：" + day["transport"])
        props["交通方式"] = {"select": {"name": day["transport"]}}
    if review:
        props["短评"] = {"rich_text": _rt(" | ".join(review))}
    if parent_id:
        props["上级 项目"] = {"relation": [{"id": parent_id}]}
    payload = {"parent": {"database_id": NOTION_DB_ID}, "properties": props}
    if day["icon"]:
        payload["icon"] = {"type": "emoji", "emoji": day["icon"]}
    return payload


def build_body(day: dict, parent_id: Optional[str]) -> list:
    blocks = [{"object": "block", "type": "heading_2",
               "heading_2": {"rich_text": _rt("📋 当日行程")}}]
    for s in day["stops"]:
        if s["is_transit"]:
            line = f"{s['icon']} {s['time']} {s['origin']}→{s['destination']}"
            if s["transport"]:
                line += f"（{s['transport']}）"
        else:
            where = s["location"] or s["place"]
            line = f"{s['icon']} {s['time']} {s['title']}"
            if where and where not in s["title"]:
                line += f" · {where}"
        children = []
        if s["dwell_min"] and not s["is_transit"]:
            children.append(_bullet(f"⏱ 停留 {s['dwell_min']} 分钟"))
        if s["note"]:
            children.append(_bullet(f"💡 要点：{s['note']}"))
        if s["guard"]:
            children.append(_bullet(f"⚠️ 时限：{s['guard']}"))
        if s["cost"]:
            children.append(_bullet(f"💰 费用：{s['cost']}"))
        for n in s["notes"]:
            children.append(_bullet(n))
        blocks.append(_bullet(line, children))
    if parent_id:
        blocks.append({"object": "block", "type": "paragraph", "paragraph": {"rich_text": [
            {"type": "text", "text": {"content": "属于父项目："}},
            {"type": "mention", "mention": {"type": "page", "page": {"id": parent_id}}},
        ]}})
    return blocks


def archive_day(day_key: str, stops: List[dict], project: Optional[str],
                dry_run: bool = False, keep_outlook: bool = False) -> bool:
    day = aggregate_day(day_key, stops)
    project = project or day["project"]
    print(f"📅 {day_key}: {day['title']}  ({len(stops)} 个事件 → 1 条足迹)")
    for s in stops:
        tag = f"{s['origin']}→{s['destination']}" if s["is_transit"] else (s["location"] or s["place"])
        print(f"   {s['icon']} {s['time']} {s['title']}  [{tag}]" + (f"  ⚠️ {s['guard']}" if s["guard"] else ""))

    parent_id = ensure_project(project, day_key, dry_run) if project else None
    payload, body = build_page(day, parent_id), build_body(day, parent_id)
    if dry_run:
        print("  [dry-run] 不写 Notion、不删 Outlook")
        print(json.dumps({"properties": list(payload["properties"]), "blocks": len(body)}, ensure_ascii=False))
        return True

    try:
        page = notion("POST", "/pages", payload)
    except urllib.error.HTTPError as e:
        print(f"  ❌ Notion 写入失败: {e.read().decode('utf-8', 'replace')}", file=sys.stderr)
        return False
    print(f"  ✓ Notion 创建: {page.get('url', page['id'])}")
    try:
        notion("PATCH", f"/blocks/{page['id']}/children", {"children": body})
        print(f"  ✓ 正文 {len(body)} blocks")
    except urllib.error.HTTPError as e:
        print(f"  ⚠️  正文写入失败: {e.read().decode('utf-8', 'replace')}", file=sys.stderr)

    if keep_outlook:
        print("  · 保留 Outlook 事件（--keep-outlook）")
        return True
    deleted = 0
    for s in stops:
        try:
            graph_request("DELETE", f"/me/events/{s['id']}")
            deleted += 1
        except Exception as e:  # noqa: BLE001
            print(f"  ⚠️  删除 Outlook 事件失败 {s['id'][:24]}…: {e}", file=sys.stderr)
    print(f"  ✓ Outlook 清理 {deleted}/{len(stops)}")
    return True


def archive_range(start_iso: str, end_iso: str, project: Optional[str], dry_run: bool, keep_outlook: bool):
    print(f"📅 查询行程: {start_iso} → {end_iso}")
    events = fetch_events(start_iso, end_iso)
    if not events:
        print("📭 无行程")
        return
    by_day = group_by_day(events)
    print(f"📦 {len(events)} 个事件，聚合为 {len(by_day)} 天\n")
    ok = 0
    for day_key, stops in by_day.items():
        try:
            ok += archive_day(day_key, stops, project, dry_run, keep_outlook)
        except Exception as e:  # noqa: BLE001
            print(f"❌ 归档 {day_key} 失败: {e}", file=sys.stderr)
        print()
    print(f"✓ 已归档 {ok}/{len(by_day)} 天")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="action", required=True)

    def common(p):
        p.add_argument("--project", help="父项目标题（覆盖事件 body 里的 项目：）")
        p.add_argument("--dry-run", action="store_true", help="只打印聚合结果，不写 Notion / 不删 Outlook")
        p.add_argument("--keep-outlook", action="store_true", help="归档后不删除 Outlook 事件")

    p1 = sub.add_parser("archive-yesterday", help="归档昨天（cron 用）")
    common(p1)
    p2 = sub.add_parser("archive", help="归档指定日期或区间")
    p2.add_argument("--date", help="YYYY-MM-DD")
    p2.add_argument("--start", help="YYYY-MM-DD（区间起，含）")
    p2.add_argument("--end", help="YYYY-MM-DD（区间止，含）")
    common(p2)
    args = ap.parse_args()

    if args.action == "archive-yesterday":
        y = (now_cn() - timedelta(days=1)).strftime("%Y-%m-%d")
        s, e = day_range(y)
    else:
        if args.date:
            s, e = day_range(args.date)
        elif args.start and args.end:
            s, _ = day_range(args.start)
            _, e = day_range(args.end)
        else:
            ap.error("archive 需要 --date 或 --start/--end")
    archive_range(s, e, args.project, args.dry_run, args.keep_outlook)


if __name__ == "__main__":
    main()
