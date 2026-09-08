#!/usr/bin/env python3
"""
outlook_event.py - Outlook 日历事件 CRUD（Microsoft Graph API）

支持两种认证模式:
  1. Client Credentials (应用权限) — 仅适用于企业租户
  2. Device Code Flow (委托权限) — 适用于个人 MSA 账号（Master 当前模式）

首次使用 device code 流会提示浏览器登录;token 缓存到本地。
"""
import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from trip_common import build_body, parse_graph_dt, to_graph_dt, event_to_stop, normalize_transport  # noqa: E402

GRAPH_BASE = "https://graph.microsoft.com/v1.0"

CACHE_DIR = Path.home() / ".cache" / "trip-manager"
CACHE_DIR.mkdir(parents=True, exist_ok=True)
TOKEN_FILE = CACHE_DIR / "ms_token.json"


def get_access_token_client_credentials() -> str:
    """Client Credentials 模式（企业租户）"""
    client_id = os.environ.get("MS_GRAPH_CLIENT_ID")
    client_secret = os.environ.get("MS_GRAPH_CLIENT_SECRET")
    tenant_id = os.environ.get("MS_GRAPH_TENANT_ID")
    if not all([client_id, client_secret, tenant_id]):
        print("❌ 缺少 MS_GRAPH_CLIENT_ID / MS_GRAPH_CLIENT_SECRET / MS_GRAPH_TENANT_ID", file=sys.stderr)
        sys.exit(1)

    if TOKEN_FILE.exists():
        cached = json.loads(TOKEN_FILE.read_text())
        if cached.get("mode") != "client_credentials":
            TOKEN_FILE.unlink()
        else:
            expires_at = datetime.fromisoformat(cached["expires_at"])
            if datetime.now(timezone.utc) < expires_at - timedelta(minutes=5):
                return cached["access_token"]

    is_msa = tenant_id == "consumers"
    token_url = (
        "https://login.microsoftonline.com/consumers/oauth2/v2.0/token"
        if is_msa
        else f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"
    )
    data = urllib.parse.urlencode({
        "grant_type": "client_credentials",
        "client_id": client_id,
        "client_secret": client_secret,
        "scope": "https://graph.microsoft.com/.default",
    }).encode()
    req = urllib.request.Request(token_url, data=data, method="POST")
    with urllib.request.urlopen(req, timeout=30) as resp:
        result = json.loads(resp.read())

    expires_at = datetime.now(timezone.utc) + timedelta(seconds=result["expires_in"])
    TOKEN_FILE.write_text(json.dumps({
        "mode": "client_credentials",
        "access_token": result["access_token"],
        "expires_at": expires_at.isoformat(),
    }))
    return result["access_token"]


def get_access_token_device_code() -> str:
    """Device Code Flow（个人 MSA 账号）"""
    client_id = os.environ.get("MS_GRAPH_CLIENT_ID")
    if not client_id:
        print("❌ 缺少 MS_GRAPH_CLIENT_ID", file=sys.stderr)
        sys.exit(1)

    if TOKEN_FILE.exists():
        cached = json.loads(TOKEN_FILE.read_text())
        if cached.get("mode") == "device_code":
            expires_at = datetime.fromisoformat(cached["expires_at"])
            if datetime.now(timezone.utc) < expires_at - timedelta(minutes=5):
                return cached["access_token"]
            # 过期,尝试 refresh_token
            if "refresh_token" in cached:
                try:
                    refresh_data = urllib.parse.urlencode({
                        "grant_type": "refresh_token",
                        "client_id": client_id,
                        "refresh_token": cached["refresh_token"],
                    }).encode()
                    refresh_req = urllib.request.Request(
                        "https://login.microsoftonline.com/consumers/oauth2/v2.0/token",
                        data=refresh_data, method="POST",
                        headers={"Content-Type": "application/x-www-form-urlencoded"},
                    )
                    with urllib.request.urlopen(refresh_req, timeout=30) as resp:
                        result = json.loads(resp.read())
                    new_expires = datetime.now(timezone.utc) + timedelta(seconds=result["expires_in"])
                    TOKEN_FILE.write_text(json.dumps({
                        "mode": "device_code",
                        "access_token": result["access_token"],
                        "refresh_token": result.get("refresh_token", cached["refresh_token"]),
                        "expires_at": new_expires.isoformat(),
                    }))
                    return result["access_token"]
                except urllib.error.HTTPError:
                    # refresh_token 失效,清除缓存走完整流程
                    TOKEN_FILE.unlink()

    # 1. 请求 device code
    data = urllib.parse.urlencode({
        "client_id": client_id,
        "scope": "https://graph.microsoft.com/Calendars.ReadWrite offline_access",
    }).encode()
    req = urllib.request.Request(
        "https://login.microsoftonline.com/consumers/oauth2/v2.0/devicecode",
        data=data, method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        dc = json.loads(resp.read())

    print("=" * 60)
    print("🔐 Microsoft 账户登录")
    print("=" * 60)
    print(f"1. 在浏览器打开: {dc['verification_uri']}")
    print(f"2. 输入代码:     {dc['user_code']}")
    print("=" * 60)
    print("⏳ 等待登录...")

    # 2. 轮询 token
    expires_in = dc["expires_in"]
    interval = dc["interval"]
    deadline = time.time() + expires_in
    while time.time() < deadline:
        time.sleep(interval)
        poll_data = urllib.parse.urlencode({
            "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
            "client_id": client_id,
            "device_code": dc["device_code"],
        }).encode()
        poll_req = urllib.request.Request(
            "https://login.microsoftonline.com/consumers/oauth2/v2.0/token",
            data=poll_data, method="POST",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        try:
            with urllib.request.urlopen(poll_req, timeout=30) as resp:
                token = json.loads(resp.read())
            break
        except urllib.error.HTTPError as e:
            body = json.loads(e.read())
            if body.get("error") == "authorization_pending":
                continue
            elif body.get("error") == "slow_down":
                interval += 5
                continue
            else:
                print(f"❌ 登录失败: {body}")
                sys.exit(1)
    else:
        print("❌ 登录超时")
        sys.exit(1)

    expires_at = datetime.now(timezone.utc) + timedelta(seconds=token["expires_in"])
    TOKEN_FILE.write_text(json.dumps({
        "mode": "device_code",
        "access_token": token["access_token"],
        "refresh_token": token.get("refresh_token", ""),
        "expires_at": expires_at.isoformat(),
    }))
    print("✓ 登录成功!\n")
    return token["access_token"]


def get_access_token() -> str:
    """智能选择认证模式"""
    if os.environ.get("MS_GRAPH_CLIENT_SECRET"):
        return get_access_token_client_credentials()
    return get_access_token_device_code()


def graph_request(method: str, path: str, body: dict = None) -> dict:
    """发送 Graph API 请求"""
    token = get_access_token()
    url = f"{GRAPH_BASE}{path}"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="replace")
        print(f"❌ Graph API 错误 {e.code}: {err_body}", file=sys.stderr)
        sys.exit(1)


def cmd_create(args):
    """创建日历事件（body 里写结构化元数据，归档 / 地图 / 检查都靠它）"""
    transport = normalize_transport(args.transport)
    body_html = build_body(
        notes=args.body, project=args.project, origin=args.origin, destination=args.destination,
        transport=transport, dwell=args.dwell, note=args.note, guard=args.guard, cost=args.cost,
    )
    event = {
        "subject": args.title,
        "body": {"contentType": "HTML", "content": body_html},
        "start": to_graph_dt(args.start),
        "end": to_graph_dt(args.end),
        "location": {"displayName": args.location or args.destination or ""},
        "isReminderOn": True,
        "reminderMinutesBeforeStart": args.reminder,
    }
    if transport:
        event["categories"] = [transport]
    if args.dry_run:
        print(json.dumps(event, ensure_ascii=False, indent=2))
        return
    result = graph_request("POST", "/me/events", event)
    stop = event_to_stop(result)
    print(f"✓ 已创建事件: {result.get('subject')} (id={result.get('id')})")
    print(f"  时间: {stop['start'].strftime('%Y-%m-%d %H:%M')} → {stop['end'].strftime('%H:%M') if stop['end'] else '?'} (北京)")
    if stop["location"]:
        print(f"  地点: {stop['location']}")
    if stop["is_transit"]:
        print(f"  路段: {stop['origin']} → {stop['destination']}  {stop['transport'] or ''}")
    if stop["project"]:
        print(f"  项目: {stop['project']}")


def cmd_list(args):
    """列出指定时间范围的日历事件（--json 输出结构化站点，供其它脚本用）"""
    from trip_common import fetch_events, group_by_day
    events = fetch_events(args.start, args.end)
    if args.json:
        out = []
        for day, stops in group_by_day(events).items():
            for s in stops:
                d = {k: v for k, v in s.items() if k not in ("start", "end")}
                d["date"] = day
                out.append(d)
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return
    if not events:
        print(f"📭 {args.start} → {args.end} 无事件")
        return
    print(f"📅 {args.start} → {args.end} 共 {len(events)} 个事件:\n")
    for day, stops in group_by_day(events).items():
        print(f"── {day} ──")
        for s in stops:
            where = f"{s['origin']}→{s['destination']}" if s["is_transit"] else (s["location"] or "")
            print(f"  {s['icon']} {s['time']}–{s['end_time']} {s['title']}" + (f"  @{where}" if where else ""))
            extra = [x for x in (
                s["transport"], f"停留 {s['dwell_min']}min" if s["dwell_min"] and not s["is_transit"] else None,
                f"项目 {s['project']}" if s["project"] else None,
                f"⚠️ {s['guard']}" if s["guard"] else None) if x]
            if extra:
                print("     " + " · ".join(extra))
            print(f"     id: {s['id']}")
        print()


def cmd_delete(args):
    graph_request("DELETE", f"/me/events/{args.id}")
    print(f"✓ 已删除事件 {args.id}")


def main():
    ap = argparse.ArgumentParser(description="Outlook 行程事件 CRUD（Microsoft Graph）")
    sub = ap.add_subparsers(dest="action", required=True)

    p = sub.add_parser("create", help="创建日历事件")
    p.add_argument("--start", required=True, help="ISO8601，如 2026-10-01T08:00（无时区按北京时间）")
    p.add_argument("--end", required=True)
    p.add_argument("--title", required=True, help="建议 'Day2-1: 🏔 双桥沟'（DayN 前缀用于归档聚合）")
    p.add_argument("--location", help="地点（景点 / 酒店）")
    p.add_argument("--body", help="自由描述（可多行）")
    p.add_argument("--transport", help="交通方式：飞机/高铁/汽车/船/步行（自动加 emoji）")
    p.add_argument("--origin", help="起点（填了起点+终点即视为交通段）")
    p.add_argument("--destination", help="终点")
    p.add_argument("--project", help="所属多日行程，如 '川西 10.1-10.7'（归档时自动挂到同名父页）")
    p.add_argument("--dwell", help="计划停留时长，如 90 / 1.5h")
    p.add_argument("--note", help="要点：到了现场要照做的一条（如 '7:00 前到沟口抢早班观光车'）")
    p.add_argument("--guard", help="时限：最晚离开 / 排队上限 / 换乘缓冲（如 '14:00 前必须离开'）")
    p.add_argument("--cost", help="预计花费")
    p.add_argument("--reminder", type=int, default=30, help="提前提醒分钟数（默认 30）")
    p.add_argument("--dry-run", action="store_true", help="只打印将要提交的事件 JSON")
    p.set_defaults(func=cmd_create)

    p = sub.add_parser("list", help="列出时间范围事件")
    p.add_argument("--start", required=True)
    p.add_argument("--end", required=True)
    p.add_argument("--json", action="store_true", help="输出结构化 JSON")
    p.set_defaults(func=cmd_list)

    p = sub.add_parser("delete", help="删除事件")
    p.add_argument("--id", required=True)
    p.set_defaults(func=cmd_delete)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
