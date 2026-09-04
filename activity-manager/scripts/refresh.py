#!/usr/bin/env python3
"""refresh.py — 确保每个启用活动存在 Outlook 重复事件系列（幂等）。

monthly 规则的多日（days_of_month: [10,20]）会为每一天各建一个 series，
因为 Graph v1.0 absoluteMonthly 仅支持单个 dayOfMonth。

用法:
  python3 refresh.py
  python3 refresh.py --dry-run
  python3 refresh.py --clean [--id xxx]
"""
import argparse
from datetime import date, timedelta

import common


def next_or_today(a: dict, today: date) -> date:
    """今天有场次且未过期 → 今天；否则下一个场次日。"""
    rule = a["rules"][0]
    if rule.get("freq") == "daily":
        return today
    if rule.get("freq") == "monthly":
        days = sorted(rule["days_of_month"])
        d = today
        for _ in range(400):
            if d.day in days:
                return d
            d += timedelta(days=1)
        return d
    d = today
    for _ in range(8):
        if d.isoweekday() == rule["weekday"]:
            return d
        d += timedelta(days=1)
    return d


def existing_series(a: dict) -> dict:
    """统一 series 存储：{"<key>": id}。key 为 '' (单系列) 或 monthly 的日号。"""
    s = a.get("series_id")
    if isinstance(s, dict):
        return s
    if isinstance(s, str) and s:
        return {"": s}
    return {}


def save_series(a: dict, mapping: dict):
    if len(mapping) == 1 and "" in mapping:
        a["series_id"] = mapping[""]
    else:
        a["series_id"] = mapping


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--clean", action="store_true")
    ap.add_argument("--id")
    args = ap.parse_args()

    db = common.load()
    today = date.today()

    if args.clean:
        acts = [common.find_activity(db, args.id)] if args.id else db["activities"]
        for a in acts:
            for key, sid in existing_series(a).items():
                print(f"  删除系列 [{a['id']}] day={key or '-'} {sid[:16]}…")
                if not args.dry_run and not sid.startswith("PLACEHOLDER"):
                    common.delete_event(sid)
            for d, eid in list(a.get("events", {}).items()):
                if eid and not eid.startswith("series:"):
                    print(f"  删除一次性事件 [{a['id']}] {d} {eid[:16]}…")
                    if not args.dry_run:
                        common.delete_event(eid)
            a["series_id"] = None
            a["events"] = {}
        if not args.dry_run:
            common.save(db)
        print("✓ clean 完成")
        return

    for a in db["activities"]:
        if not a.get("enabled", True):
            continue
        rule = a["rules"][0]
        have = existing_series(a)

        def ensure(key, maker, label):
            if have.get(key):
                print(f"  [{a['id']}] {label} 系列已存在")
                return
            start = next_or_today(a, today)
            if a.get("valid_until") and start > date.fromisoformat(a["valid_until"]):
                print(f"  [{a['id']}] 已过有效期，跳过")
                return
            print(f"  + [{a['id']}] 创建系列: {label} {a.get('time','10:00')} 自 {start}")
            if args.dry_run:
                return
            have[key] = maker(start)
            save_series(a, have)
            common.save(db)

        if rule.get("freq") == "monthly":
            for day in sorted(rule["days_of_month"]):
                ensure(str(day), lambda s, d=day: common.create_series(a, s, month_day=d),
                       f"每月{day}号")
        else:
            ensure("", lambda s: common.create_series(a, s),
                   f"{rule.get('freq')}")
        # 注：不再建 @go 伴生系列——Outlook 单事件仅支持一个提醒时点，
        # 成对建会被视为日历重复。如需"开始时"准点响，改 create_series 的
        # reminderMinutesBeforeStart 为 1 并重建，而不是加第二个事件。
    if not args.dry_run:
        common.save(db)
    print("✓ refresh 完成")


if __name__ == "__main__":
    main()
