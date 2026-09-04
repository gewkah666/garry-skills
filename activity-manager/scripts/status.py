#!/usr/bin/env python3
"""status.py — 列出活动、重复系列状态、本月/本年配额余量、当月剩余提醒。"""
import argparse
from datetime import date

import common
from refresh import existing_series


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-calendar", action="store_true", help="不查询日历实例（离线快速模式）")
    args = ap.parse_args()

    db = common.load()
    today = date.today()
    mk, y = common.month_key(today), str(today.year)
    print(f"📋 权益活动一览  ({today})\n")
    for a in db["activities"]:
        icon = "✅" if a.get("enabled", True) else "⏸️"
        print(f"{icon} [{a['id']}] {a['name']}")
        r = a["rules"][0]
        if r.get("freq") == "daily":
            rules = "每天"
        elif r.get("freq") == "monthly":
            rules = "每月" + "、".join(str(x) for x in r.get("days_of_month", [])) + "号"
        else:
            rules = f"每周{['一','二','三','四','五','六','日'][r.get('weekday',1)-1]}"
        print(f"   ⏰ {rules} {a.get('time','10:00')}", end="")
        q = a.get("quota") or {}
        parts = []
        if q.get("per") == "month":
            parts.append(f"本月 {common.used_in_month(a, mk)}/{q.get('max')}")
        if q.get("year_max") is not None and q.get("year") == today.year:
            parts.append(f"本年 {common.used_in_year(a, y)}/{q['year_max']}")
        print(("   配额: " + " | ".join(parts)) if parts else "   配额: 不限", end="")
        if a.get("valid_until"):
            print(f"   截止 {a['valid_until']}", end="")
        series = {k: v for k, v in existing_series(a).items() if not v.startswith("PLACEHOLDER")}
        print(f"   🔁 系列: {len(series) or '未建'}" + (f"（{'/'.join(k+'号' for k in series if k)}）" if any(series) else ""))
        if series and not args.no_calendar and a.get("enabled", True):
            insts = []
            for sid in series.values():
                try:
                    insts += [d for d, _ in common.get_instances(
                        sid, today, common.month_end(today), a.get("time", "10:00"))]
                except SystemExit:
                    pass
            insts = sorted(set(insts))
            print(f"   📅 本月剩余提醒: {', '.join(str(d) for d in insts) or '无'}")
        print()


if __name__ == "__main__":
    main()
