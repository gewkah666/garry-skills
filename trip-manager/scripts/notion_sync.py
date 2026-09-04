#!/usr/bin/env python3
"""
notion_sync.py - 将 Outlook 行程归档到 Notion 阅览世界

逻辑:
  1. 查询 Outlook 前一天的 calendarView 事件
  2. 按"日"分组，聚合为一条 Notion 行程条目
  3. 写入 Notion 「阅览世界」数据库
     - 类型=足迹, 状态=已完成
     - 名字=聚合标题 (e.g. "Day2 - 四姑娘山→甲居藏寨→八美")
     - icon=行程首个 emoji
     - 短评=一日总览
     - 时间线/上映/发布时间=当天日期
     - ⛱️ 起点=首站, 终点=末站
     - 交通方式=检测到的交通 emoji
     - 正文 body: 各时段 bullet list（景点 vs 交通段分类）
  4. 删除 Outlook 上的对应事件
  5. 若指定 --project "川西 10.1-10.7"，创建父级 page 并通过 上级 项目 关联
"""
import argparse
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from typing import Optional
from datetime import datetime, timedelta, timezone
from pathlib import Path

# 复用 outlook_event.py 的 Graph API 调用
SKILL_DIR = Path(__file__).parent
sys.path.insert(0, str(SKILL_DIR))
from outlook_event import graph_request, get_access_token  # noqa: E402

NOTION_DB_ID = "747e9f3b-0bbf-4f03-b678-7fc62a093790"  # 阅览世界 data_source_id

# 交通 emoji → Notion select 名称
TRANSPORT_MAP = {
    "🚗": "🚗 汽车", "🚙": "🚗 汽车", "🚕": "🚗 汽车",
    "🚞": "🚞 高铁", "🚄": "🚞 高铁", "🚆": "🚞 高铁", "🚅": "🚞 高铁",
    "✈️": "✈️ 飞机", "🛩️": "✈️ 飞机",
    "🚢": "🚢 船", "⛴": "🚢 船", "🚤": "🚢 船",
}

# 从标题中提取 emoji
EMOJI_RE = re.compile(
    "["
    "\U0001F300-\U0001F5FF"   # symbols & pictographs
    "\U0001F600-\U0001F64F"   # emoticons
    "\U0001F680-\U0001F6FF"   # transport
    "\U0001F700-\U0001F77F"
    "\U0001F900-\U0001F9FF"
    "\U0001FA00-\U0001FAFF"
    "\U00002700-\U000027BF"
    "\U0001F1E0-\U0001F1FF"
    "]+",
    flags=re.UNICODE,
)

# 行程段类型检测
TRANSIT_HINT_RE = re.compile(r"[→\->]|to|→")  # 含箭头 → 交通段


def get_yesterday_range():
    """获取昨天 00:00 ~ 今天 00:00 (Asia/Shanghai)"""
    tz_china = timezone(timedelta(hours=8))
    now = datetime.now(tz_china)
    today_midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    yesterday_midnight = today_midnight - timedelta(days=1)
    return (
        yesterday_midnight.isoformat(),
        today_midnight.isoformat(),
    )


def parse_beijing_dt(date_str: str) -> datetime:
    """解析 Graph API 返回的 UTC 时间字符串，返回北京时间 datetime"""
    clean = date_str.split(".")[0]
    if clean.endswith("Z"):
        utc_dt = datetime.fromisoformat(clean.replace("Z", "+00:00"))
    else:
        utc_dt = datetime.fromisoformat(clean).replace(tzinfo=timezone.utc)
    return utc_dt.astimezone(timezone(timedelta(hours=8)))


def extract_emoji(text: str) -> str:
    """从文本中提取首个 emoji"""
    m = EMOJI_RE.search(text)
    return m.group(0) if m else ""


def detect_transport(text: str) -> Optional[str]:
    """从标题中检测交通方式"""
    for emoji, name in TRANSPORT_MAP.items():
        if emoji in text:
            return name
    return None


def is_transit_segment(title: str) -> bool:
    """判断是否为交通段（含 → 或 A→B 模式）"""
    return bool(TRANSIT_HINT_RE.search(title))


def clean_title(title: str) -> tuple:
    """
    清理标题：去除 Day N[-M]: 前缀
    返回: (cleaned_title, day_label_or_none)
    例如: "Day2-1: 双桥沟" → ("双桥沟", "Day2")
          "Day2-5: 甲居→八美" → ("甲居→八美", "Day2")
    """
    m = re.match(r"^(Day\s*\d+)(?:-\d+)?[-:]\s*(.+)$", title, re.IGNORECASE)
    if m:
        return m.group(2).strip(), m.group(1)
    return title.strip(), None


def group_events_by_day(events: list) -> dict:
    """按日期（北京）分组"""
    by_day = defaultdict(list)
    for ev in events:
        beijing = parse_beijing_dt(ev["start"]["dateTime"])
        day_key = beijing.strftime("%Y-%m-%d")
        by_day[day_key].append((beijing, ev))
    # 每天内按时间排序
    for day_key in by_day:
        by_day[day_key].sort(key=lambda x: x[0])
    return dict(by_day)


def aggregate_day(day_key: str, items: list) -> dict:
    """
    聚合一天的事件为一个 Notion page 数据结构
    items: [(beijing_dt, event), ...]
    """
    locations = []
    segments = []  # 每段 bullet
    transport_modes = set()
    icon_emoji = None
    day_label = None

    for beijing_dt, ev in items:
        subject = ev["subject"]
        cleaned, label = clean_title(subject)
        if label:
            day_label = label  # 记录 Day N 标签
        
        # 取 emoji 作为 icon
        if not icon_emoji:
            icon_emoji = extract_emoji(subject)

        location = ev.get("location", {}).get("displayName", "")
        start_time = beijing_dt.strftime("%H:%M")
        
        # 检测交通方式
        transport = detect_transport(subject)
        if transport:
            transport_modes.add(transport)

        # 判断是交通段还是景点段
        is_transit = is_transit_segment(subject)
        bullet_prefix = "🚗" if is_transit else "📍"
        if transport:
            bullet_prefix = transport.split()[0]  # ✈️ / 🚞 / 🚗
        
        time_range = f"{start_time}"
        location_str = f" → {location}" if location else ""
        segments.append(f"{bullet_prefix} {time_range} {cleaned}{location_str}")

        if location and location not in locations:
            locations.append(location)

    # 构造聚合标题
    # 优先用 day_label (如 "Day2"),否则用日期
    prefix = day_label or day_key[5:]  # "2026-10-01" → "10-01"
    unique_locs = locations
    if len(unique_locs) == 0:
        title = f"{prefix} - 出行"
    elif len(unique_locs) == 1:
        title = f"{prefix} - {unique_locs[0]}"
    elif len(unique_locs) == 2:
        title = f"{prefix} - {unique_locs[0]}→{unique_locs[-1]}"
    else:
        title = f"{prefix} - {unique_locs[0]}→{unique_locs[-1]} ({len(unique_locs)}站)"

    return {
        "day_key": day_key,
        "day_label": day_label,
        "title": title,
        "icon": icon_emoji,
        "locations": unique_locs,
        "origin": unique_locs[0] if unique_locs else None,
        "destination": unique_locs[-1] if unique_locs else None,
        "transport": next(iter(transport_modes), None),
        "segments": segments,
        "events": [ev for _, ev in items],
    }


def archive_yesterday_events(project_title: str = None):
    """归档昨天的行程到 Notion（按日聚合）"""
    start, end = get_yesterday_range()
    print(f"📅 查询昨天行程: {start} → {end}")

    params = urllib.parse.urlencode({
        "startDateTime": start,
        "endDateTime": end,
        "$orderby": "start/dateTime",
        "$select": "id,subject,start,end,location,body,categories",
    })
    result = graph_request("GET", f"/me/calendarView?{params}")
    events = result.get("value", [])

    if not events:
        print("📭 昨天无行程")
        return

    by_day = group_events_by_day(events)
    print(f"📦 发现 {len(events)} 个事件，聚合为 {len(by_day)} 天\n")

    # 创建父项目（如果指定）
    parent_page_id = None
    if project_title and len(by_day) > 1:
        parent_page_id = create_parent_project(project_title, list(by_day.keys())[0], list(by_day.keys())[-1])

    archived = 0
    for day_key, items in by_day.items():
        try:
            archive_day(day_key, items, parent_page_id)
            archived += 1
        except Exception as e:
            print(f"❌ 归档 {day_key} 失败: {e}", file=sys.stderr)

    print(f"\n✓ 已归档 {archived}/{len(by_day)} 天")


def create_parent_project(title: str, start_date: str, end_date: str) -> Optional[str]:
    """
    创建（或复用同名）父项目 page（多日游的聚合），返回 page_id

    行为：先在 Notion 搜索同名 page，存在则复用，不存在则新建
    """
    notion_token = os.environ.get("NOTION_TOKEN")
    if not notion_token:
        print("  ⚠️  跳过父项目创建（缺 NOTION_TOKEN）")
        return None

    # 尝试查找同名 page
    search_req = urllib.request.Request(
        "https://api.notion.com/v1/search",
        data=json.dumps({"query": title, "filter": {"value": "page", "property": "object"}}).encode(),
        method="POST",
        headers={
            "Authorization": f"Bearer {notion_token}",
            "Notion-Version": "2022-06-28",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(search_req, timeout=30) as resp:
            search_data = json.loads(resp.read())
        for p in search_data.get("results", []):
            # 检查标题匹配
            ptitle = ""
            for prop in p.get("properties", {}).values():
                if prop.get("type") == "title":
                    for t in prop.get("title", []):
                        ptitle += t.get("plain_text", "")
            if ptitle == title:
                print(f"  📌 复用已有父项目: {title} ({p['id']})\n")
                return p["id"]
    except Exception as e:
        print(f"  ⚠️  搜索父项目失败: {e}", file=sys.stderr)

    # 不存在则创建
    payload = {
        "parent": {"database_id": NOTION_DB_ID},
        "properties": {
            "名字": {"title": [{"text": {"content": title}}]},
            "类型": {"select": {"name": "足迹"}},
            "状态": {"select": {"name": "已完成"}},
            "标签": {"multi_select": [{"name": "足迹"}, {"name": "行程"}]},
            "上映/发布时间": {"date": {"start": start_date}},
            "时间线": {"date": {"start": start_date, "end": end_date}},
            "短评": {"rich_text": [{"text": {"content": f"多日行程"}}]},
        },
    }
    req = urllib.request.Request(
        "https://api.notion.com/v1/pages",
        data=json.dumps(payload, ensure_ascii=False).encode(),
        method="POST",
        headers={
            "Authorization": f"Bearer {notion_token}",
            "Notion-Version": "2022-06-28",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            page = json.loads(resp.read())
        print(f"  📌 父项目创建: {title} ({page.get('id')})\n")
        return page.get("id")
    except urllib.error.HTTPError as e:
        print(f"  ⚠️  父项目创建失败: {e.read().decode()}", file=sys.stderr)
        return None


def archive_day(day_key: str, items: list, parent_page_id: str = None):
    """归档一天的所有事件为一个聚合 Notion page"""
    aggregated = aggregate_day(day_key, items)
    title = aggregated["title"]
    icon_emoji = aggregated["icon"]

    print(f"📅 {day_key}: {title}")
    print(f"   {len(items)} 个事件 → 1 个 Notion 条目")

    # 构造 Notion page
    notion_token = os.environ.get("NOTION_TOKEN")
    if not notion_token:
        print(f"  ⚠️  跳过 Notion 写入（缺 NOTION_TOKEN）：{title}")
        return

    payload = {
        "parent": {"database_id": NOTION_DB_ID},
        "properties": {
            "名字": {"title": [{"text": {"content": title}}]},
            "类型": {"select": {"name": "足迹"}},
            "状态": {"select": {"name": "已完成"}},
            "标签": {"multi_select": [{"name": "足迹"}, {"name": "行程"}]},
            "上映/发布时间": {"date": {"start": day_key}},
            "时间线": {"date": {"start": day_key}},
        },
    }

    # 短评：行程总览
    short_review_parts = []
    if aggregated["locations"]:
        short_review_parts.append(f"路线：{' → '.join(aggregated['locations'])}")
    if aggregated["transport"]:
        short_review_parts.append(f"交通：{aggregated['transport']}")
    if short_review_parts:
        payload["properties"]["短评"] = {
            "rich_text": [{"text": {"content": " | ".join(short_review_parts)}}]
        }

    # 交通方式 select
    if aggregated["transport"]:
        payload["properties"]["交通方式"] = {
            "select": {"name": aggregated["transport"]}
        }

    # 关联父项目（relation field "上级 项目"）
    if parent_page_id:
        payload["properties"]["上级 项目"] = {
            "relation": [{"id": parent_page_id}]
        }

    # 图标
    if icon_emoji:
        payload["icon"] = {"type": "emoji", "emoji": icon_emoji}

    # 写入 page（不带 children）
    req = urllib.request.Request(
        "https://api.notion.com/v1/pages",
        data=json.dumps(payload, ensure_ascii=False).encode(),
        method="POST",
        headers={
            "Authorization": f"Bearer {notion_token}",
            "Notion-Version": "2022-06-28",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            page = json.loads(resp.read())
        page_id = page.get("id")
        print(f"  ✓ Notion 创建: {title} ({page_id})")
    except urllib.error.HTTPError as e:
        err = e.read().decode("utf-8", errors="replace")
        print(f"  ❌ Notion 写入失败: {err}", file=__import__("sys").stderr)
        raise

    # 添加正文 body（各时段 bullet）
    body_children = [
        {
            "object": "block",
            "type": "heading_2",
            "heading_2": {"rich_text": [{"type": "text", "text": {"content": "📋 当日行程"}}]},
        },
    ]
    for seg in aggregated["segments"]:
        body_children.append({
            "object": "block",
            "type": "bulleted_list_item",
            "bulleted_list_item": {"rich_text": [{"type": "text", "text": {"content": seg}}]},
        })

    # 关联父项目（在 body 末尾加 mention）
    if parent_page_id:
        body_children.append({
            "object": "block",
            "type": "paragraph",
            "paragraph": {
                "rich_text": [
                    {"type": "text", "text": {"content": "属于父项目：", "link": None}},
                    {
                        "type": "mention",
                        "mention": {"type": "page", "page": {"id": parent_page_id}},
                    },
                ]
            },
        })

    req = urllib.request.Request(
        f"https://api.notion.com/v1/blocks/{page_id}/children",
        data=json.dumps({"children": body_children}, ensure_ascii=False).encode(),
        method="PATCH",
        headers={
            "Authorization": f"Bearer {notion_token}",
            "Notion-Version": "2022-06-28",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            json.loads(resp.read())
        print(f"  ✓ Body 写入: {len(body_children)} blocks")
    except urllib.error.HTTPError as e:
        print(f"  ⚠️  Body 写入失败: {e.read().decode()}", file=sys.stderr)

    # 删除 Outlook 事件
    deleted = 0
    for _, ev in items:
        try:
            graph_request("DELETE", f"/me/events/{ev['id']}")
            deleted += 1
        except Exception as e:
            print(f"  ⚠️  删除 Outlook 事件失败 {ev['id']}: {e}", file=sys.stderr)
    print(f"  ✓ Outlook 清理: {deleted}/{len(items)}\n")


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="action", required=True)

    p1 = sub.add_parser("archive-yesterday", help="归档昨天的行程")
    p1.add_argument("--project", help="多日游的父项目标题（可选，自动创建）")
    p1.set_defaults(func=lambda args: archive_yesterday_events(args.project))

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()