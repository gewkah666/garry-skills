#!/usr/bin/env python3
"""
trip_modify.py - 修改行程（自动路由未来/过去）

规则:
  - 出发时间 > 今天 → 修改 Outlook 日历事件
  - 出发时间 ≤ 今天 → 修改 Notion page
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
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

SKILL_DIR = Path(__file__).parent
sys.path.insert(0, str(SKILL_DIR))
from outlook_event import graph_request, get_access_token  # noqa: E402
import notion_sync  # noqa: E402

NOTION_DB_ID = "747e9f3b-0bbf-4f03-b678-7fc62a093790"


def get_today_utc8():
    """返回今天 00:00 (Asia/Shanghai)"""
    tz_china = timezone(timedelta(hours=8))
    return datetime.now(tz_china).replace(hour=0, minute=0, second=0, microsecond=0)


def parse_beijing_dt(date_str: str) -> datetime:
    """解析 UTC 时间字符串 → 北京时间 datetime"""
    clean = date_str.split(".")[0]
    if clean.endswith("Z"):
        utc_dt = datetime.fromisoformat(clean.replace("Z", "+00:00"))
    else:
        utc_dt = datetime.fromisoformat(clean).replace(tzinfo=timezone.utc)
    return utc_dt.astimezone(timezone(timedelta(hours=8)))


def find_outlook_event_by_title(keyword: str, days_ahead: int = 365) -> Optional[dict]:
    """根据关键词查找未来 Outlook 日历事件"""
    token = get_access_token()
    now = datetime.now(timezone(timedelta(hours=8)))
    end = now + timedelta(days=days_ahead)
    params = urllib.parse.urlencode({
        "startDateTime": now.isoformat(),
        "endDateTime": end.isoformat(),
        "$orderby": "start/dateTime",
        "$select": "id,subject,start,end,location,body,categories",
    })
    result = graph_request("GET", f"/me/calendarView?{params}")
    for ev in result.get("value", []):
        if keyword.lower() in ev.get("subject", "").lower():
            return ev
    return None


def find_notion_page_by_title(keyword: str) -> Optional[tuple]:
    """根据关键词查找 Notion page（足迹/行程类型），返回 (page_id, title)"""
    notion_token = os.environ.get("NOTION_TOKEN")
    if not notion_token:
        return None
    search_req = urllib.request.Request(
        "https://api.notion.com/v1/search",
        data=json.dumps({"query": keyword, "filter": {"value": "page", "property": "object"}}).encode(),
        method="POST",
        headers={
            "Authorization": f"Bearer {notion_token}",
            "Notion-Version": "2022-06-28",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(search_req, timeout=15) as resp:
            data = json.loads(resp.read())
        for p in data.get("results", []):
            title = ""
            for prop in p.get("properties", {}).values():
                if prop.get("type") == "title":
                    title = "".join(t.get("plain_text", "") for t in prop.get("title", []))
            if keyword.lower() in title.lower():
                return p["id"], title
        return None
    except urllib.error.HTTPError as e:
        print(f"❌ 搜索失败: {e.read().decode()}", file=sys.stderr)
        return None


def modify_outlook_event(event_id: str, updates: dict):
    """更新 Outlook 日历事件"""
    payload = {}
    if "subject" in updates:
        payload["subject"] = updates["subject"]
    if "start" in updates:
        payload["start"] = updates["start"]
    if "end" in updates:
        payload["end"] = updates["end"]
    if "location" in updates:
        payload["location"] = {"displayName": updates["location"]}
    if "body" in updates:
        payload["body"] = {"contentType": "HTML", "content": updates["body"]}
    if "transport" in updates:
        # 删除旧 categories，再加新的
        payload["categories"] = [updates["transport"]]

    graph_request("PATCH", f"/me/events/{event_id}", payload)
    print(f"✓ Outlook 事件 {event_id[:20]}... 已更新")


def modify_notion_page(page_id: str, updates: dict):
    """更新 Notion page properties"""
    notion_token = os.environ.get("NOTION_TOKEN")
    if not notion_token:
        print("❌ 缺 NOTION_TOKEN")
        return

    payload = {"properties": {}}
    if "name" in updates:
        payload["properties"]["名字"] = {"title": [{"text": {"content": updates["name"]}}]}
    if "review" in updates:
        payload["properties"]["短评"] = {"rich_text": [{"text": {"content": updates["review"]}}]}
    if "score" in updates:
        payload["properties"]["打分（5分制）"] = {"select": {"name": updates["score"]}}
    if "status" in updates:
        payload["properties"]["状态"] = {"select": {"name": updates["status"]}}
    if "tags" in updates:
        payload["properties"]["标签"] = {"multi_select": [{"name": t} for t in updates["tags"]]}

    req = urllib.request.Request(
        f"https://api.notion.com/v1/pages/{page_id}",
        data=json.dumps(payload, ensure_ascii=False).encode(),
        method="PATCH",
        headers={
            "Authorization": f"Bearer {notion_token}",
            "Notion-Version": "2022-06-28",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            page = json.loads(resp.read())
        print(f"✓ Notion page {page_id[:20]}... 已更新")
        # 如果是正文 body 改动，append block
        if "body" in updates and updates["body"]:
            body_children = [{
                "object": "block",
                "type": "paragraph",
                "paragraph": {
                    "rich_text": [{"type": "text", "text": {"content": updates["body"]}}]
                }
            }]
            req2 = urllib.request.Request(
                f"https://api.notion.com/v1/blocks/{page_id}/children",
                data=json.dumps({"children": body_children}, ensure_ascii=False).encode(),
                method="PATCH",
                headers={
                    "Authorization": f"Bearer {notion_token}",
                    "Notion-Version": "2022-06-28",
                    "Content-Type": "application/json",
                },
            )
            with urllib.request.urlopen(req2, timeout=30) as resp:
                json.loads(resp.read())
            print(f"  ✓ 已添加 note: {updates['body'][:50]}")
    except urllib.error.HTTPError as e:
        print(f"❌ 更新失败: {e.read().decode()}", file=sys.stderr)


def smart_modify(keyword: str, updates: dict):
    """根据行程时间智能路由修改目标"""
    # 先找 Outlook 未来事件
    outlook_event = find_outlook_event_by_title(keyword)

    if outlook_event:
        beijing = parse_beijing_dt(outlook_event["start"]["dateTime"])
        today = get_today_utc8()
        if beijing >= today:
            # 未来行程 → Outlook
            print(f"→ 未来行程 [{beijing.date()}] 修改 Outlook 日历")
            modify_outlook_event(outlook_event["id"], updates)
            return "outlook"

    # 没找到未来行程 → 查 Notion 过去 page
    notion_result = find_notion_page_by_title(keyword)
    if not notion_result:
        print(f"❌ 未找到 '{keyword}' 的行程")
        return None
    page_id, title = notion_result
    print(f"→ 过去行程 [{title}] 修改 Notion page")
    modify_notion_page(page_id, updates)
    return "notion"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("keyword", help="行程关键词（如：'北京出差'、'Day2'）")
    ap.add_argument("--subject", help="新标题")
    ap.add_argument("--start", help="新开始时间 ISO8601")
    ap.add_argument("--end", help="新结束时间 ISO8601")
    ap.add_argument("--location", help="新地点")
    ap.add_argument("--body", help="新描述 / Notion 备注")
    ap.add_argument("--transport", help="新交通方式（飞机/高铁/汽车）")
    ap.add_argument("--name", help="新 Notion 名字")
    ap.add_argument("--review", help="新 Notion 短评")
    ap.add_argument("--score", help="新 Notion 评分")
    ap.add_argument("--status", help="新 Notion 状态")
    ap.add_argument("--tags", nargs="+", help="新 Notion 标签")
    args = ap.parse_args()

    updates = {}
    for k in ["subject", "start", "end", "location", "body", "transport", "name", "review", "score", "status", "tags"]:
        v = getattr(args, k)
        if v:
            updates[k] = v

    if not updates:
        print("❌ 至少指定一个 --subject/--start/--body/--score 等")
        sys.exit(1)

    target = smart_modify(args.keyword, updates)
    if not target:
        sys.exit(1)
    print(f"\n✓ 已路由到: {target}")


if __name__ == "__main__":
    main()