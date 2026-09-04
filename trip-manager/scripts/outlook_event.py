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
    """创建日历事件"""
    # 把 +08:00 偏移量从时间中减去（Graph API 会当作 UTC 处理）
    import re
    def normalize_dt(s):
        m = re.match(r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})([+-]\d{2}:\d{2})$", s)
        if m:
            # 减去时区偏移: 2026-09-15T08:00:00+08:00 → 2026-09-15T00:00:00Z
            from datetime import datetime, timedelta, timezone
            base = datetime.fromisoformat(m.group(1))
            sign = 1 if m.group(2)[0] == '+' else -1
            hh, mm = map(int, m.group(2)[1:].split(':'))
            offset = timedelta(hours=hh, minutes=mm) * sign
            utc = base - offset
            return utc.strftime("%Y-%m-%dT%H:%M:%SZ")
        return s

    start_utc = normalize_dt(args.start)
    end_utc = normalize_dt(args.end)
    tz = "UTC"

    parts = []
    if args.body:
        parts.append(args.body)
    if args.origin or args.destination:
        meta = []
        if args.origin:
            meta.append(f"起点：{args.origin}")
        if args.destination:
            meta.append(f"终点：{args.destination}")
        if args.transport:
            meta.append(f"交通：{args.transport}")
        parts.append("<br>".join(meta))

    event = {
        "subject": args.title,
        "body": {"contentType": "HTML", "content": "<br>".join(parts)},
        "start": {"dateTime": start_utc, "timeZone": tz},
        "end": {"dateTime": end_utc, "timeZone": tz},
        "location": {"displayName": args.location or ""},
        "isReminderOn": True,
    }
    if args.transport:
        if "飞机" in args.transport:
            t = "✈️ 飞机"
        elif "高铁" in args.transport or "火车" in args.transport:
            t = "🚞 高铁"
        elif "汽车" in args.transport:
            t = "🚗 汽车"
        else:
            t = args.transport
        event["categories"] = [t]

    result = graph_request("POST", "/me/events", event)
    print(f"✓ 已创建事件: {result.get('subject')} (id={result.get('id')})")
    print(f"  时间: {result.get('start', {}).get('dateTime')} → {result.get('end', {}).get('dateTime')}")
    if args.location:
        print(f"  地点: {args.location}")


def cmd_list(args):
    """列出指定时间范围的日历事件"""
    params = urllib.parse.urlencode({
        "startDateTime": args.start,
        "endDateTime": args.end,
        "$orderby": "start/dateTime",
        "$select": "id,subject,start,end,location,body,categories",
    })
    result = graph_request("GET", f"/me/calendarView?{params}")

    events = result.get("value", [])
    if not events:
        print(f"📭 {args.start} → {args.end} 无事件")
        return

    print(f"📅 {args.start} → {args.end} 共 {len(events)} 个事件:\n")
    for ev in events:
        # Graph API 返回 UTC 字符串，转换为 Asia/Shanghai 显示
        from datetime import datetime, timezone, timedelta
        start_dt = ev["start"]["dateTime"]
        display_dt = start_dt  # fallback
        try:
            # 处理 "2026-09-15T00:00:00.0000000" / "2026-09-15T00:00:00Z" 等
            clean = start_dt.split(".")[0]  # 去掉小数秒
            if clean.endswith("Z"):
                utc_dt = datetime.fromisoformat(clean.replace("Z", "+00:00"))
            else:
                utc_dt = datetime.fromisoformat(clean).replace(tzinfo=timezone.utc)
            beijing_dt = utc_dt.astimezone(timezone(timedelta(hours=8)))
            display_dt = beijing_dt.strftime("%Y-%m-%d %H:%M (北京)")
        except Exception:
            display_dt = start_dt
        print(f"  • [{display_dt}] {ev['subject']}")
        print(f"    id: {ev['id']}")
        if ev.get("location", {}).get("displayName"):
            print(f"    location: {ev['location']['displayName']}")
        if ev.get("categories"):
            print(f"    交通方式: {', '.join(ev['categories'])}")
        print()


def cmd_delete(args):
    """删除日历事件"""
    graph_request("DELETE", f"/me/events/{args.id}")
    print(f"✓ 已删除事件 {args.id}")


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="action", required=True)

    p_create = sub.add_parser("create", help="创建日历事件")
    p_create.add_argument("--start", required=True)
    p_create.add_argument("--end", required=True)
    p_create.add_argument("--title", required=True)
    p_create.add_argument("--location", help="地点")
    p_create.add_argument("--body", help="描述")
    p_create.add_argument("--transport", help="交通方式（飞机/高铁/汽车）")
    p_create.add_argument("--origin", help="起点")
    p_create.add_argument("--destination", help="终点")
    p_create.set_defaults(func=cmd_create)

    p_list = sub.add_parser("list", help="列出时间范围事件")
    p_list.add_argument("--start", required=True)
    p_list.add_argument("--end", required=True)
    p_list.set_defaults(func=cmd_list)

    p_delete = sub.add_parser("delete", help="删除事件")
    p_delete.add_argument("--id", required=True)
    p_delete.set_defaults(func=cmd_delete)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()