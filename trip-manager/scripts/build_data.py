#!/usr/bin/env python3
"""
build_data.py - 从 Notion 拉取行程数据,生成 travel-guide/data.json

支持两种模式:
  - 单行程: build_data.py "川西 10.1-10.7"  (用 search 自动查找)
  - 硬编码 (备选): build_data.py --pinned  (用预定义 page id)
"""
from __future__ import annotations
import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Optional

NOTION_API = "https://api.notion.com/v1"

OUTPUT_DIR = Path(__file__).parent / "travel-guide"
OUTPUT_DIR.mkdir(exist_ok=True)


# 已知的 Day page id (用于 --pinned 模式)
PINNED_DAYS = {
    "Day2": "3c7616ff-95e7-81ee-8653-cb0808fe0970",
    "Day3": "3c7616ff-95e7-8160-be07-f7a015674fda",
    "Day4": "3c7616ff-95e7-81b0-9696-c5ba5b52b055",
    "Day5": "3c7616ff-95e7-81ca-944a-cce66ed84e59",
    "Day6": "3c7616ff-95e7-8139-8adf-d9e31cbb9f02",
    "Day7": "3c7616ff-95e7-8117-a623-db2f3dfe154a",
}

PINNED_TRIP_INFO = {
    "title": "川西 10.1-10.7",
    "start_date": "2026-10-01",
    "end_date": "2026-10-07",
}


def get_notion_token() -> str:
    token = os.environ.get("NOTION_TOKEN")
    if not token:
        try:
            with open(Path.home() / ".hermes" / "config.yaml") as f:
                for line in f:
                    if "NOTION_TOKEN:" in line:
                        token = line.split("NOTION_TOKEN:")[-1].strip()
                        break
        except FileNotFoundError:
            pass
    if not token:
        print("❌ NOTION_TOKEN not set", file=sys.stderr)
        sys.exit(1)
    return token


def notion_request(path: str, method: str = "GET", data: dict | None = None) -> dict:
    token = get_notion_token()
    headers = {
        "Authorization": f"Bearer {token}",
        "Notion-Version": "2022-06-28",
        "Content-Type": "application/json",
    }
    body = json.dumps(data).encode() if data else None
    req = urllib.request.Request(
        f"{NOTION_API}{path}", data=body, method=method, headers=headers
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        print(f"❌ {e.code}: {e.read().decode()}", file=sys.stderr)
        sys.exit(1)


def extract_page_data(page: dict) -> dict:
    props = page.get("properties", {})

    def get_title():
        return "".join(t.get("plain_text", "") for t in props.get("名字", {}).get("title", []))

    def get_text(prop_name):
        return "".join(t.get("plain_text", "") for t in props.get(prop_name, {}).get("rich_text", []))

    def get_select(prop_name):
        sel = props.get(prop_name, {}).get("select")
        return sel.get("name", "") if sel else ""

    def get_date(prop_name):
        d = props.get(prop_name, {}).get("date")
        return d.get("start", "") if d else ""

    def get_icon():
        icon = page.get("icon", {})
        return icon.get("emoji", "") if icon else ""

    title = get_title()
    m = re.match(r"^(Day\d+)\s*[-—]\s*(.+?)(?:\s*\((\d+)站\))?$", title)
    day = m.group(1) if m else ""
    route_title = m.group(2) if m else title
    stop_count = m.group(3) if m else ""

    review = get_text("短评")
    locations = []
    transport = ""
    if "路线：" in review:
        route_part = review.split("路线：")[1].split(" |")[0]
        locations = [loc.strip() for loc in route_part.split("→")]
    if "交通：" in review:
        transport = review.split("交通：")[1].strip()

    body_blocks = notion_request(f"/blocks/{page['id']}/children?page_size=100").get("results", [])
    waypoints = []
    for block in body_blocks:
        btype = block.get("type", "")
        if btype == "bulleted_list_item":
            text = "".join(t.get("plain_text", "") for t in block["bulleted_list_item"]["rich_text"])
            m2 = re.match(r"^(\S+)\s+(\d{1,2}:\d{2})\s+(.+)$", text)
            if m2:
                emoji, time, desc = m2.groups()
                waypoints.append({"time": time, "icon": emoji, "name": desc})
            else:
                waypoints.append({"icon": "📍", "name": text})

    return {
        "id": page["id"],
        "day": day,
        "date": get_date("时间线"),
        "title": route_title,
        "full_title": title,
        "icon": get_icon(),
        "transport": transport or get_select("交通方式"),
        "locations": locations,
        "stop_count": stop_count,
        "waypoints": waypoints,
        "url": page.get("url", ""),
    }


# 行程所在省份前缀：避免裸地名歧义（如"新都桥"裸查命中上海同名 POI、"甘孜"命中州府康定）
PROVINCE = "四川省"
# 歧义地点 → 精确地理编码地址（高德裸查结果不可靠时手工修正）
AMBIGUOUS_MAP = {
    "甘孜": "四川省甘孜县",
    "新都桥": "四川省康定市新都桥镇",
    "八美": "四川省道孚县八美镇",
}


def geocode_locations(locations: list) -> dict:
    api_key = os.environ.get("AMAP_API_KEY")
    if not api_key:
        print("⚠️  AMAP_API_KEY 未设置")
        return {}

    result = {}
    for loc in locations:
        try:
            addr = AMBIGUOUS_MAP.get(loc, f"{PROVINCE}{loc}")
            url = f"https://restapi.amap.com/v3/geocode/geo?address={urllib.parse.quote(addr)}&key={api_key}"
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read())
            if data.get("geocodes"):
                lng, lat = data["geocodes"][0]["location"].split(",")
                result[loc] = {"lng": float(lng), "lat": float(lat)}
                print(f"    {loc} → {lng},{lat}")
        except Exception as e:
            print(f"⚠️  地理编码失败 {loc}: {e}")
    return result


def build_from_pinned():
    """硬编码模式:直接读 PINNED_DAYS 中所有 page id"""
    print(f"📌 硬编码模式 (共 {len(PINNED_DAYS)} 天)")
    pages = []
    for day, pid in PINNED_DAYS.items():
        page = notion_request(f"/pages/{pid}")
        pages.append(page)
        print(f"  ✓ {day}: {page['properties']['名字']['title'][0]['plain_text']}")
    return pages


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("title", nargs="?", default=PINNED_TRIP_INFO["title"])
    ap.add_argument("--pinned", action="store_true", help="用硬编码 page id 模式")
    args = ap.parse_args()

    if args.pinned or args.title == PINNED_TRIP_INFO["title"]:
        print(f"📥 使用硬编码模式: {args.title}")
        pages = build_from_pinned()
    else:
        # 兼容旧 search 模式
        pages = query_trip_pages(args.title)

    days = [extract_page_data(p) for p in pages]
    days.sort(key=lambda d: d["date"])

    # 地理编码
    all_locs = set()
    for d in days:
        all_locs.update(d["locations"])
    print(f"🗺️  地理编码 {len(all_locs)} 个地点")
    geo = geocode_locations(sorted(all_locs))

    # 挂坐标
    for d in days:
        d["waypoints_with_geo"] = []
        for wp in d["waypoints"]:
            name = wp["name"]
            for loc in d["locations"]:
                if loc in name and loc in geo:
                    wp["coords"] = geo[loc]
                    d["waypoints_with_geo"].append(wp)
                    break

    data = {
        "trip": {
            "title": args.title,
            "start_date": days[0]["date"] if days else "",
            "end_date": days[-1]["date"] if days else "",
            "amap_key": os.environ.get("AMAP_JS_API_KEY", ""),
            "days": days,
        },
        "geo_cache": geo,
    }

    output_file = OUTPUT_DIR / "data.json"
    output_file.write_text(json.dumps(data, ensure_ascii=False, indent=2))
    print(f"\n✓ 已生成: {output_file}")
    print(f"  共 {len(days)} 天, {len(geo)} 个地理编码")


if __name__ == "__main__":
    main()