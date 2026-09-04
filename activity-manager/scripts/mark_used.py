#!/usr/bin/env python3
"""mark_used.py — 标记活动已使用 N 次，删除重复系列中当月剩余实例。
若本年配额封顶，连带删除本年度所有未来实例。支持 monthly 多系列。

用法:
  python3 mark_used.py --id ceb-jd-500
  python3 mark_used.py --id ceb-zfb-recharge --count 2
  python3 mark_used.py --id ceb-jd-500 --date 2026-09-04   # 补记历史日期
"""
import argparse
from datetime import date, timedelta

import common
from refresh import existing_series


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--id", required=True)
    ap.add_argument("--count", type=int, default=1)
    ap.add_argument("--date", default=None)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    db = common.load()
    a = common.find_activity(db, args.id)
    used_date = date.fromisoformat(args.date) if args.date else date.today()
    mk, y = common.month_key(used_date), str(used_date.year)
    q = a.get("quota") or {}

    a.setdefault("used", {}).setdefault("months", {})
    a["used"]["months"][mk] = a["used"]["months"].get(mk, 0) + args.count
    a.setdefault("used", {}).setdefault("years", {})
    a["used"]["years"][y] = a["used"]["years"].get(y, 0) + args.count
    print(f"✓ [{a['id']}] {mk} 已用 {a['used']['months'][mk]} 次 | {y} 年已用 {a['used']['years'][y]} 次")

    series = {k: v for k, v in existing_series(a).items() if not v.startswith("PLACEHOLDER")}
    if not series:
        print("⚠ 无系列，跳过实例清理")
        if not args.dry_run:
            common.save(db)
        return

    # 删除范围：使用日之后 → 当月末；若年配额触顶 → 延伸到年底/valid_until
    year_exhausted = (q.get("year_max") is not None and q.get("year") == used_date.year
                      and a["used"]["years"][y] >= q["year_max"])
    if year_exhausted:
        until = date(used_date.year, 12, 31)
        if a.get("valid_until"):
            until = min(until, date.fromisoformat(a["valid_until"]))
        print(f"  年配额已触顶 → 清除至 {until} 的全部剩余提醒")
    else:
        until = common.month_end(used_date)

    from_d = used_date + timedelta(days=1)
    if from_d > until:
        print("✓ 当月已无剩余实例")
        if not args.dry_run:
            common.save(db)
        return

    time_str = a.get("time", "10:00")
    removed = 0
    for key, sid in series.items():
        for d, iid in common.get_instances(sid, from_d, until, time_str):
            print(f"  删除实例 {d} (series day={key or '-'})")
            if not args.dry_run:
                common.delete_event(iid)
            removed += 1
    print(f"✓ 清除剩余提醒 {removed} 条")
    if not args.dry_run:
        common.save(db)


if __name__ == "__main__":
    main()
