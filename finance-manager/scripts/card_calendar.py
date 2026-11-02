#!/Users/garry/.hermes/hermes-agent/venv/bin/python
"""card_calendar — 信用卡出账日 / 还款日 → Outlook 月度重复事件。

  card_calendar.py sync            按 Notion 账户库里的 出账日 / 还款日 建或更新每张使用中信用卡的系列
  card_calendar.py list            看现在每张卡的额度、出账日、还款日和已建的系列
  card_calendar.py clean [--card 名称]   删掉系列（销卡、改日子时先 clean 再 sync）

每张卡最多两个系列：「💳 X 出账」（09:00）和「💳 还 X」（10:00，提醒在事件开始时）。
系列 id 记回 Notion 账户库的「提醒系列」字段，重复跑不会重复建。事件带 category「💳 信用卡」，
trip-manager 归档脚本按 category 忽略它们。复用 trip-manager 的 Graph 认证（device-code token 缓存）。
"""
import argparse
import importlib.util
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path

HOME = Path(os.environ.get("HERMES_HOME", os.path.expanduser("~/.hermes")))
# Graph 认证需要 MS_GRAPH_CLIENT_ID，和 trip-manager 一样放在 ~/.hermes/trip-env.sh
try:
    for _line in (HOME / "trip-env.sh").read_text().splitlines():
        _line = _line.strip().removeprefix("export ").strip()
        if "=" in _line and not _line.startswith("#"):
            _k, _v = _line.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip().strip('"').strip("'"))
except OSError:
    pass
sys.path.insert(0, str(HOME / "skills/garry-skills/trip-manager/scripts"))
import outlook_event  # noqa: E402

TZ = "China Standard Time"
CATEGORY = "💳 信用卡"
SLOTS = {"statement": ("出账", "09:00"), "due": ("due", "10:00")}
EVENT_MINUTES = 30


def load_finance():
    pkg = HOME / "plugins" / "finance"
    spec = importlib.util.spec_from_file_location("finance", pkg / "__init__.py", submodule_search_locations=[str(pkg)])
    m = importlib.util.module_from_spec(spec)
    sys.modules["finance"] = m
    spec.loader.exec_module(m)
    from finance import ledger, notion, ops
    return ledger, notion, ops


def _dt(d: date, hhmm: str, add_min: int = 0) -> str:
    h, mi = map(int, hhmm.split(":"))
    return (datetime(d.year, d.month, d.day, h, mi) + timedelta(minutes=add_min)).strftime("%Y-%m-%dT%H:%M:%S")


def next_on(day: int) -> date:
    today = date.today()
    for y, m in ((today.year, today.month), (today.year + (today.month == 12), today.month % 12 + 1)):
        try:
            d = date(y, m, min(day, 28) if day > 28 else day)
        except ValueError:
            continue
        if d >= today:
            return d
    return today


def title(card: str, slot: str) -> str:
    return f"💳 {card} 出账" if slot == "statement" else f"💳 还 {card}"


def body(a) -> str:
    parts = []
    if a["credit_limit"]:
        parts.append(f"额度 ¥{a['credit_limit']:,.0f}")
    if a["statement_day"]:
        parts.append(f"每月 {int(a['statement_day'])} 日出账")
    if a["due_day"]:
        parts.append(f"每月 {int(a['due_day'])} 日还款")
    parts.append("由 finance-manager 维护；改日子在 Notion 账户库改后跑 card_calendar.py sync。")
    return "<br>".join(parts)


def create_series(a, slot: str, day: int) -> str:
    start = next_on(day)
    hhmm = SLOTS[slot][1]
    event = {
        "subject": title(a["name"], slot),
        "body": {"contentType": "HTML", "content": body(a)},
        "start": {"dateTime": _dt(start, hhmm), "timeZone": TZ},
        "end": {"dateTime": _dt(start, hhmm, EVENT_MINUTES), "timeZone": TZ},
        "recurrence": {"pattern": {"type": "absoluteMonthly", "interval": 1, "dayOfMonth": day, "index": "first"},
                       "range": {"type": "noEnd", "startDate": start.isoformat(), "recurrenceTimeZone": TZ}},
        "isReminderOn": True,
        "reminderMinutesBeforeStart": 0,
        "categories": [CATEGORY],
    }
    return outlook_event.graph_request("POST", "/me/events", event)["id"]


def delete_series(series_id: str) -> None:
    token = outlook_event.get_access_token()
    req = urllib.request.Request(f"{outlook_event.GRAPH_BASE}/me/events/{series_id}", method="DELETE",
                                 headers={"Authorization": f"Bearer {token}"})
    try:
        urllib.request.urlopen(req, timeout=30)
    except urllib.error.HTTPError as e:
        if e.code != 404:
            raise


def cards(ledger):
    with ledger.connect() as con:
        return [dict(a) for a in ledger.accounts(con) if a["type"] == "信用卡" and not a["archived"]]


def save_calendar(notion, account_id: str, cal: dict) -> None:
    notion.update_page(account_id, {"提醒系列": notion.rt(json.dumps(cal, ensure_ascii=False))})


def cmd_sync(args):
    ledger, notion, ops = load_finance()
    ops.sync()
    changed = []
    for a in cards(ledger):
        cal = json.loads(a["calendar"] or "{}")
        active = a["status"] != "已销户"
        want = {"statement": int(a["statement_day"]) if a["statement_day"] and active else None,
                "due": int(a["due_day"]) if a["due_day"] and active else None}
        for slot, day in want.items():
            have = cal.get(slot)
            if have and (not day or have.get("day") != day):
                delete_series(have["id"])
                cal.pop(slot, None)
                changed.append(f"删 {title(a['name'], slot)}（{have.get('day')} 日）")
                have = None
            if day and not have:
                sid = create_series(a, slot, day)
                cal[slot] = {"id": sid, "day": day}
                changed.append(f"建 {title(a['name'], slot)}（每月 {day} 日）")
        if cal != json.loads(a["calendar"] or "{}"):
            save_calendar(notion, a["id"], cal)
    ops.sync()
    print(json.dumps({"ok": True, "changed": changed or ["无变化"]}, ensure_ascii=False, indent=2))


def cmd_list(args):
    ledger, _, ops = load_finance()
    ops.sync()
    for a in cards(ledger):
        cal = json.loads(a["calendar"] or "{}")
        print(f"{a['name']}{'（已销户）' if a['status'] == '已销户' else ''}: 额度 {a['credit_limit'] or '-'} · 出账 {a['statement_day'] or '-'} 日 · 还款 {a['due_day'] or '-'} 日 · 日历 {', '.join(cal) or '无'}")


def cmd_clean(args):
    ledger, notion, ops = load_finance()
    for a in cards(ledger):
        if args.card and args.card not in a["name"]:
            continue
        cal = json.loads(a["calendar"] or "{}")
        for slot, meta in cal.items():
            delete_series(meta["id"])
            print("删", title(a["name"], slot))
        if cal:
            save_calendar(notion, a["id"], {})
    ops.sync()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("sync"); sub.add_parser("list")
    c = sub.add_parser("clean"); c.add_argument("--card")
    a = ap.parse_args()
    {"sync": cmd_sync, "list": cmd_list, "clean": cmd_clean}[a.cmd](a)


if __name__ == "__main__":
    main()
