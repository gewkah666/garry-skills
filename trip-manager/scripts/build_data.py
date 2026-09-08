#!/usr/bin/env python3
"""
build_data.py - 生成 travel-guide/data.json（交互地图 + 手机行程模式 的数据源）

两种数据源：
  * 未来行程（还在 Outlook 日历里）:
      build_data.py --outlook --start 2026-10-01 --end 2026-10-07 --title "川西 10.1-10.7" --region 四川省
  * 已归档行程（Notion 足迹，按父项目找子页）:
      build_data.py --notion "川西 10.1-10.7" --region 四川省
      build_data.py --notion --pages id1,id2,...        # 直接给 page id

坐标：每个站点按自己的地名（终点 / 地点）走高德地理编码，带缓存
      ~/.cache/trip-manager/geocode.json —— 歧义地名（如"甘孜"命中州府）可手改这个文件
      查不到就不挂坐标（不猜），页面上显示"待确认"
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
from trip_common import (  # noqa: E402
    NOTION_DB_ID, aggregate_day, day_range, fetch_events, geocode, group_by_day, first_emoji, strip_emoji,
)

OUTPUT_FILE = Path(__file__).resolve().parent.parent / "travel-guide" / "data.json"
NOTION_API = "https://api.notion.com/v1"

# 歧义地名 → 精确地址（走地理编码前替换）。更多修正直接改缓存文件
AMBIGUOUS_MAP = {
    "甘孜": "四川省甘孜县",
    "新都桥": "四川省康定市新都桥镇",
    "八美": "四川省道孚县八美镇",
}

# ---------------------------------------------------------------- Notion

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
        headers={"Authorization": f"Bearer {notion_token()}", "Notion-Version": "2022-06-28",
                 "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        print(f"❌ Notion {e.code}: {e.read().decode('utf-8', 'replace')}", file=sys.stderr)
        sys.exit(1)


def _plain(rich: list) -> str:
    return "".join(t.get("plain_text", "") for t in rich or [])


def _title(page: dict) -> str:
    for prop in page.get("properties", {}).values():
        if prop.get("type") == "title":
            return _plain(prop.get("title"))
    return ""


def find_project_page(title: str) -> Optional[dict]:
    data = notion("POST", "/search", {"query": title, "filter": {"value": "page", "property": "object"}})
    for p in data.get("results", []):
        if _title(p) == title and not p.get("archived"):
            return p
    return None


def query_trip_pages(title: str) -> List[dict]:
    """父项目标题 → 通过「上级 项目」relation 找到所有子页（Day 页）"""
    parent = find_project_page(title)
    if not parent:
        print(f"❌ Notion 里没有标题为「{title}」的父项目页", file=sys.stderr)
        sys.exit(1)
    print(f"📌 父项目: {title} ({parent['id']})")
    pages, cursor = [], None
    while True:
        body = {"filter": {"property": "上级 项目", "relation": {"contains": parent["id"]}}, "page_size": 100}
        if cursor:
            body["start_cursor"] = cursor
        data = notion("POST", f"/databases/{NOTION_DB_ID}/query", body)
        pages.extend(data.get("results", []))
        if not data.get("has_more"):
            break
        cursor = data.get("next_cursor")
    if not pages:
        print("❌ 父项目下没有关联子页（Day 页的「上级 项目」为空？）", file=sys.stderr)
        sys.exit(1)
    return pages


_BULLET_RE = re.compile(r"^(\S+)\s+(\d{1,2}:\d{2})\s+(.+)$")
_CHILD_RE = re.compile(r"^(?:⏱\s*停留\s*(\d+)|💡\s*要点[：:]\s*(.+)|⚠️?\s*时限[：:]\s*(.+)|💰\s*费用[：:]\s*(.+))\s*(?:分钟)?$")


def _children(block_id: str) -> list:
    return notion("GET", f"/blocks/{block_id}/children?page_size=100").get("results", [])


def page_to_day(page: dict) -> dict:
    props = page.get("properties", {})

    def sel(name):
        s = props.get(name, {}).get("select")
        return s.get("name", "") if s else ""

    def date(name):
        d = props.get(name, {}).get("date")
        return d.get("start", "") if d else ""

    title = _title(page)
    m = re.match(r"^\s*(Day\s*\d+)(?:-\d+)?\s*[-—:：]\s*(.+?)(?:\s*\((\d+)站\))?\s*$", title, re.IGNORECASE)
    day_label = m.group(1).replace(" ", "") if m else ""
    route_title = m.group(2) if m else title

    review = _plain(props.get("短评", {}).get("rich_text"))
    route, transport = [], ""
    if "路线：" in review:
        route = [x.strip() for x in review.split("路线：")[1].split("|")[0].split("→") if x.strip()]
    if "交通：" in review:
        transport = review.split("交通：")[1].split("|")[0].strip()

    stops = []
    for block in _children(page["id"]):
        if block.get("type") != "bulleted_list_item":
            continue
        text = _plain(block["bulleted_list_item"]["rich_text"])
        mm = _BULLET_RE.match(text)
        if mm:
            icon, time, desc = mm.groups()
        else:
            icon, time, desc = first_emoji(text) or "📍", "", strip_emoji(text)
        transit = "→" in desc or "->" in desc
        head = re.split(r"\s*[·（(]\s*", desc, 1)[0]
        parts = [x for x in re.split(r"\s*(?:→|->)\s*", strip_emoji(head)) if x]
        stop = {
            "time": time, "icon": icon, "name": strip_emoji(desc),
            "is_transit": transit and len(parts) >= 2,
            "origin": parts[0] if transit and len(parts) >= 2 else None,
            "destination": parts[-1] if transit and len(parts) >= 2 else None,
            "place": parts[-1] if parts else strip_emoji(desc),
            "dwell_min": None, "note": None, "guard": None, "cost": None, "notes": [],
        }
        if block.get("has_children"):
            for ch in _children(block["id"]):
                if ch.get("type") != "bulleted_list_item":
                    continue
                ct = _plain(ch["bulleted_list_item"]["rich_text"])
                cm = _CHILD_RE.match(ct)
                if cm and cm.group(1):
                    stop["dwell_min"] = int(cm.group(1))
                elif cm and cm.group(2):
                    stop["note"] = cm.group(2)
                elif cm and cm.group(3):
                    stop["guard"] = cm.group(3)
                elif cm and cm.group(4):
                    stop["cost"] = cm.group(4)
                else:
                    stop["notes"].append(ct)
        stops.append(stop)

    icon = (page.get("icon") or {}).get("emoji", "")
    return {
        "id": page["id"], "day": day_label, "date": date("时间线") or date("上映/发布时间"),
        "title": route_title, "full_title": title, "icon": icon,
        "transport": transport or sel("交通方式"), "route": route,
        "stops": stops, "url": page.get("url", ""), "source": "notion",
    }

# ---------------------------------------------------------------- Outlook

def outlook_days(start: str, end: str) -> List[dict]:
    s, _ = day_range(start)
    _, e = day_range(end)
    events = fetch_events(s, e)
    if not events:
        print(f"❌ Outlook {start} → {end} 没有事件", file=sys.stderr)
        sys.exit(1)
    days = []
    for day_key, stops in group_by_day(events).items():
        agg = aggregate_day(day_key, stops)
        days.append({
            "id": None, "day": agg["day_label"] or "", "date": day_key,
            "title": agg["title"].split(" - ", 1)[-1], "full_title": agg["title"], "icon": agg["icon"],
            "transport": agg["transport"] or "", "route": agg["route"], "project": agg["project"],
            "stops": [{
                "time": st["time"], "end_time": st["end_time"], "icon": st["icon"],
                "name": f"{st['origin']}→{st['destination']}" if st["is_transit"] else st["title"],
                "is_transit": st["is_transit"], "origin": st["origin"], "destination": st["destination"],
                "place": st["place"], "location": st["location"], "transport": st["transport"],
                "dwell_min": st["dwell_min"], "note": st["note"], "guard": st["guard"], "cost": st["cost"],
                "notes": st["notes"],
            } for st in stops],
            "url": "", "source": "outlook",
        })
    return days

# ---------------------------------------------------------------- 坐标

def attach_coords(days: List[dict], region: str) -> int:
    hit, seen = 0, set()
    for d in days:
        for s in d["stops"]:
            name = s.get("place") or ""
            if not name:
                continue
            addr = AMBIGUOUS_MAP.get(name, name)
            g = geocode(addr, region if addr == name else "")
            if g and "error" in g:
                if name not in seen:
                    print(f"    ⚠️ {name} 高德接口错误：{g['error']}（未缓存，稍后重试）")
            elif g:
                s["coords"] = {"lng": g["lng"], "lat": g["lat"]}
                hit += 1
                if name not in seen:
                    print(f"    📍 {name} → {g['lng']:.4f},{g['lat']:.4f}  {g.get('address', '')}")
            elif name not in seen:
                print(f"    ❓ {name} 查不到坐标，页面上会标「无坐标」（可在 ~/.cache/trip-manager/geocode.json 手工补）")
            seen.add(name)
    return hit


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--outlook", action="store_true", help="从 Outlook 日历读未来行程")
    src.add_argument("--notion", nargs="?", const="", metavar="项目标题", help="从 Notion 父项目读已归档行程")
    ap.add_argument("--start", help="Outlook：起始日期 YYYY-MM-DD")
    ap.add_argument("--end", help="Outlook：结束日期 YYYY-MM-DD（含）")
    ap.add_argument("--title", help="行程标题（Outlook 模式必填；Notion 模式默认父项目标题）")
    ap.add_argument("--pages", help="Notion：逗号分隔的 Day page id（绕过父项目查询）")
    ap.add_argument("--region", default="", help="地理编码前缀，如 四川省（消歧义）")
    ap.add_argument("--no-geocode", action="store_true", help="跳过高德地理编码")
    ap.add_argument("--out", default=str(OUTPUT_FILE))
    args = ap.parse_args()

    if args.outlook:
        if not (args.start and args.end):
            ap.error("--outlook 需要 --start / --end")
        title = args.title or f"{args.start} → {args.end}"
        print(f"📥 Outlook {args.start} → {args.end}")
        days = outlook_days(args.start, args.end)
        title = args.title or next((d["project"] for d in days if d.get("project")), title)
    else:
        if args.pages:
            pages = [notion("GET", f"/pages/{pid.strip()}") for pid in args.pages.split(",") if pid.strip()]
            title = args.title or "行程"
        else:
            if not args.notion:
                ap.error("--notion 需要父项目标题，或用 --pages 给 page id")
            pages = query_trip_pages(args.notion)
            title = args.title or args.notion
        print(f"📥 Notion {len(pages)} 页")
        days = [page_to_day(p) for p in pages]
        for d in days:
            print(f"  ✓ {d['full_title']}  ({len(d['stops'])} 站)")
    days.sort(key=lambda d: (d["date"], d["day"]))

    if args.no_geocode:
        print("🗺️  跳过地理编码")
    else:
        print("🗺️  地理编码…")
        n = attach_coords(days, args.region)
        print(f"   {n}/{sum(len(d['stops']) for d in days)} 站有坐标")

    data = {"trip": {
        "title": title,
        "start_date": days[0]["date"] if days else "",
        "end_date": days[-1]["date"] if days else "",
        "generated_at": __import__("datetime").datetime.now().strftime("%Y-%m-%d %H:%M"),
        "days": days,
    }}
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, ensure_ascii=False, indent=2))
    print(f"\n✓ 已生成 {out}  ({len(days)} 天)")
    print("  预览: python3 scripts/server.py  → http://localhost:8899/")


if __name__ == "__main__":
    main()
