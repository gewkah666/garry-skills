#!/usr/bin/env python3
"""activity-manager 共享模块：数据读写、Outlook 重复系列（recurrence）桥接、实例管理。

设计：周期性活动用 Outlook 原生重复事件（每天/每周五一个系列），
配额控制通过删除"当月剩余实例"实现，而非逐日排一次性事件。
"""
import json
import sys
import urllib.parse
from datetime import date, datetime, timedelta
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
DATA_FILE = SKILL_DIR / "assets" / "activities.json"
TRIP_SCRIPTS = Path.home() / ".hermes/skills/garry-skills/trip-manager/scripts"

# 复用 trip-manager 的 Outlook 认证与 Graph 请求
sys.path.insert(0, str(TRIP_SCRIPTS))
import outlook_event  # noqa: E402

TZ_NAME = "China Standard Time"
EVENT_MINUTES = 30          # 事件时长：开始 → 开始后30分钟
REMINDER_MIN = 0            # 提醒时点：0=活动开始时准点响。
                            # ⚠️ 严禁为凑"多重提醒"而建第二个事件——日历上即重复。
WEEKDAY_NAMES = ["monday", "tuesday", "wednesday", "thursday",
                 "friday", "saturday", "sunday"]


def load() -> dict:
    return json.loads(DATA_FILE.read_text(encoding="utf-8"))


def save(db: dict):
    DATA_FILE.write_text(
        json.dumps(db, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def find_activity(db: dict, aid: str) -> dict:
    for a in db["activities"]:
        if a["id"] == aid:
            return a
    raise SystemExit(f"❌ 找不到活动 id: {aid}")


def month_key(d: date) -> str:
    return d.strftime("%Y-%m")


def month_end(d: date) -> date:
    return (d.replace(day=1) + timedelta(days=32)).replace(day=1) - timedelta(days=1)


def used_in_month(a: dict, mk: str) -> int:
    return a.get("used", {}).get("months", {}).get(mk, 0)


def used_in_year(a: dict, y: str) -> int:
    return a.get("used", {}).get("years", {}).get(y, 0)


def event_title(a: dict) -> str:
    return f"💰 {a['name']}"


def _local_dt(d: date, time_str: str, add_minutes: int = 0) -> str:
    h, m = map(int, time_str.split(":"))
    base = datetime(d.year, d.month, d.day, h, m) + timedelta(minutes=add_minutes)
    return base.strftime("%Y-%m-%dT%H:%M:%S")


def _utc(d: date, time_str: str, days_offset: int = 0) -> str:
    """CST 时刻 → UTC 字符串（中国无夏令时，固定 -8h）。"""
    h, m = map(int, time_str.split(":"))
    base = datetime(d.year, d.month, d.day, h, m) + timedelta(days=days_offset)
    return (base - timedelta(hours=8)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _cst_date(utc_str: str) -> date:
    clean = utc_str.split(".")[0].rstrip("Z")
    return (datetime.fromisoformat(clean) + timedelta(hours=8)).date()


def create_series(a: dict, start: date, month_day: int = None) -> str:
    """创建 Outlook 原生重复事件系列，返回 series id。
    monthly 规则需传 month_day（Graph v1.0 absoluteMonthly 仅支持单个 dayOfMonth）。
    每个场次仅此一个事件；提醒于活动开始时（REMINDER_MIN）准点响。
    """
    rule = a["rules"][0]
    time_str = a.get("time", "10:00")
    freq = rule.get("freq")
    if freq == "daily":
        pattern = {"type": "daily", "interval": 1, "daysOfWeek": []}
    elif freq == "monthly":
        pattern = {"type": "absoluteMonthly", "interval": 1,
                   "dayOfMonth": month_day, "index": "first"}
    else:
        pattern = {
            "type": "weekly", "interval": 1,
            "daysOfWeek": [WEEKDAY_NAMES[rule["weekday"] - 1]],
            "firstDayOfWeek": "monday",
        }
    rng = {"type": "noEnd", "startDate": start.isoformat(),
           "recurrenceTimeZone": TZ_NAME}
    if a.get("valid_until"):
        rng = {"type": "endDate", "startDate": start.isoformat(),
               "endDate": a["valid_until"], "recurrenceTimeZone": TZ_NAME}
    body = a.get("desc", "") + "<br>使用后可让助手标记已用，当月剩余提醒会自动清除。"
    event = {
        "subject": event_title(a),
        "body": {"contentType": "HTML", "content": body},
        "start": {"dateTime": _local_dt(start, time_str), "timeZone": TZ_NAME},
        "end": {"dateTime": _local_dt(start, time_str, EVENT_MINUTES),
                "timeZone": TZ_NAME},
        "recurrence": {"pattern": pattern, "range": rng},
        "isReminderOn": True,
        "reminderMinutesBeforeStart": REMINDER_MIN,
        "categories": ["💰 权益活动"],
    }
    result = outlook_event.graph_request("POST", "/me/events", event)
    return result.get("id")


def delete_event(event_id: str):
    """删除事件；404（已被删除）视为成功跳过。graph_request 遇错直接 exit，故裸调。"""
    import urllib.error
    import urllib.request
    token = outlook_event.get_access_token()
    req = urllib.request.Request(
        f"{outlook_event.GRAPH_BASE}/me/events/{event_id}",
        method="DELETE",
        headers={"Authorization": f"Bearer {token}"})
    try:
        urllib.request.urlopen(req, timeout=30)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            print(f"  （{event_id[:12]}… 已不存在，跳过）")
            return
        raise SystemExit(f"❌ 删除失败 {e.code}: {e.read().decode('utf-8', 'replace')[:200]}")


def get_instances(series_id: str, from_d: date, to_d: date,
                  time_str: str = "10:00") -> list:
    """返回系列在 [from_d, to_d]（CST 日期）内的实例 [(date, instance_id), ...]。"""
    params = urllib.parse.urlencode({
        "startDateTime": _utc(from_d, time_str),
        "endDateTime": _utc(to_d, time_str, 1),
    })
    path = f"/me/events/{series_id}/instances?{params}"
    items = []
    while path:
        r = outlook_event.graph_request("GET", path)
        for it in r.get("value", []):
            items.append((_cst_date(it["start"]["dateTime"]), it["id"]))
        nxt = r.get("@odata.nextLink")
        path = nxt.replace(outlook_event.GRAPH_BASE, "") if nxt else None
    # Graph instances 边界偶有 ±1 天漂移，客户端过滤兜底
    return [(d, iid) for d, iid in items if from_d <= d <= to_d]
