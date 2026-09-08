#!/usr/bin/env python3
"""
trip_check.py - 出发前的行程一致性检查（不改任何数据）

读 Outlook 日历里某个区间的事件，按天检查：
  ⛔ 事件时间重叠
  ⛔ 赶不及：上一站到下一站的驾车耗时 > 两站之间留出的时间（高德路径规划，需 AMAP_API_KEY）
  ⚠️ 全天跨度 > 13 小时 / 站点 > 6 个
  ⚠️ 11:00–14:30 之间没有 ≥ 40 分钟的空档（没留午饭）
  ⚠️ 到达 / 离开日排得比中间天还满
  💡 站点没有地点也没有起终点（手机上无法导航）
  💡 站点没写 要点 / 时限（body 里的 `要点：` `时限：`）
并把每天的 时限 汇总打印出来，方便过一遍。

用法:
  trip_check.py --start 2026-10-01 --end 2026-10-07 [--region 四川省] [--no-route]
  trip_check.py --next 30            # 未来 30 天
退出码：有 ⛔ 时为 1
"""
from __future__ import annotations

import argparse
import sys
from datetime import timedelta
from pathlib import Path
from typing import List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
from trip_common import (  # noqa: E402
    aggregate_day, amap_key, day_range, driving_minutes, fetch_events, geocode, group_by_day, now_cn,
)

MAX_DAY_HOURS = 13
MAX_STOPS = 6
LUNCH_WINDOW = (11 * 60, 14 * 60 + 30)
LUNCH_MIN = 40
SLACK_MIN = 10  # 驾车耗时允许比空档多出的分钟数


def minutes(dt) -> int:
    return dt.hour * 60 + dt.minute


def check_day(day_key: str, stops: List[dict], region: str, use_route: bool, route_ok: dict) -> List[str]:
    out: List[str] = []
    agg = aggregate_day(day_key, stops)
    visits = [s for s in stops if not s["is_transit"] and not s["all_day"]]
    timed = [s for s in stops if not s["all_day"]]

    # 重叠 & 赶不及
    for a, b in zip(timed, timed[1:]):
        if a["end"] and a["end"] > b["start"]:
            out.append(f"⛔ 重叠：{a['time']} {a['title']} 结束于 {a['end_time']}，晚于 {b['time']} {b['title']}")
            continue
        if not use_route or a["is_transit"] or b["is_transit"] or not a["end"]:
            continue
        gap = int((b["start"] - a["end"]).total_seconds() // 60)
        ga, gb = geocode(a["place"], region), geocode(b["place"], region)
        if not (ga and gb) or "error" in ga or "error" in gb or (ga["lng"], ga["lat"]) == (gb["lng"], gb["lat"]):
            continue
        r = driving_minutes(ga, gb)
        if r is None:
            route_ok["failed"] = True
            continue
        drive, km = r
        if drive > gap + SLACK_MIN:
            out.append(f"⛔ 赶不及：{a['place']} → {b['place']} 驾车约 {drive} 分钟 / {km} km，只留了 {gap} 分钟")
        elif drive > 0:
            out.append(f"   ✓ {a['place']} → {b['place']} 驾车 {drive} 分钟 / {km} km，空档 {gap} 分钟")

    # 跨度 / 数量
    if timed:
        first, last = timed[0]["start"], (timed[-1]["end"] or timed[-1]["start"])
        span = (last - first).total_seconds() / 3600
        if span > MAX_DAY_HOURS:
            out.append(f"⚠️ 全天跨度 {span:.1f} 小时（{first.strftime('%H:%M')}–{last.strftime('%H:%M')}），考虑砍一站")
    if len(visits) > MAX_STOPS:
        out.append(f"⚠️ {len(visits)} 个站点，偏多（建议 ≤ {MAX_STOPS}，一天一个区域一个锚点）")

    # 午饭空档
    if len(timed) >= 3:
        busy = sorted((minutes(s["start"]), minutes(s["end"]) if s["end"] else minutes(s["start"]) + 60) for s in timed)
        free, cur = [], LUNCH_WINDOW[0]
        for s, e in busy:
            if s > cur:
                free.append((cur, min(s, LUNCH_WINDOW[1])))
            cur = max(cur, e)
        if cur < LUNCH_WINDOW[1]:
            free.append((cur, LUNCH_WINDOW[1]))
        if not any(e - s >= LUNCH_MIN for s, e in free if e > s and s >= LUNCH_WINDOW[0]):
            out.append("⚠️ 11:00–14:30 没有 ≥40 分钟的空档，没留午饭 / 休整")

    # 可导航性 / 要点 / 时限
    for s in visits:
        if not (s["location"] or s["place"]):
            out.append(f"💡 {s['time']} {s['title']}：没有地点，手机上无法导航")
    missing = [s["title"] for s in visits if not (s["note"] or s["guard"])]
    if missing:
        out.append("💡 没写 要点/时限 的站点：" + "、".join(missing))
    guards = [f"{s['time']} {s['title']}：{s['guard']}" for s in stops if s["guard"]]
    if guards:
        out.append("⏰ 时限：" + " ｜ ".join(guards))
    return out, agg, len(visits)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--start", help="YYYY-MM-DD")
    ap.add_argument("--end", help="YYYY-MM-DD（含）")
    ap.add_argument("--next", type=int, help="检查未来 N 天")
    ap.add_argument("--region", default="", help="地理编码前缀（如 四川省）")
    ap.add_argument("--no-route", action="store_true", help="不查驾车耗时")
    args = ap.parse_args()

    if args.next:
        start = now_cn().strftime("%Y-%m-%d")
        end = (now_cn() + timedelta(days=args.next)).strftime("%Y-%m-%d")
    elif args.start and args.end:
        start, end = args.start, args.end
    else:
        ap.error("需要 --start/--end 或 --next")

    use_route = not args.no_route and bool(amap_key())
    if not args.no_route and not amap_key():
        print("ℹ️  AMAP_API_KEY 未设置，跳过驾车耗时检查\n")

    s, _ = day_range(start)
    _, e = day_range(end)
    events = fetch_events(s, e)
    if not events:
        print(f"📭 {start} → {end} 没有行程")
        return
    by_day = group_by_day(events)
    print(f"🧭 {start} → {end}：{len(events)} 个事件 / {len(by_day)} 天\n")

    route_ok = {"failed": False}
    blockers, counts = 0, []
    for day_key, stops in by_day.items():
        issues, agg, n = check_day(day_key, stops, args.region, use_route, route_ok)
        counts.append(n)
        print(f"── {day_key}  {agg['icon']} {agg['title']}  {agg['transport'] or ''}")
        for st in stops:
            where = f"{st['origin']}→{st['destination']}" if st["is_transit"] else (st["location"] or st["place"])
            print(f"   {st['icon']} {st['time']}–{st['end_time']} {st['title']}  [{where}]")
        for line in issues:
            print("   " + line)
            blockers += line.startswith("⛔")
        print()

    days = list(by_day)
    if len(days) >= 3:
        mid = sum(counts[1:-1]) / max(1, len(counts) - 2)
        for idx, label in ((0, "到达日"), (-1, "离开日")):
            if counts[idx] > mid:
                print(f"⚠️ {label} {days[idx]} 排了 {counts[idx]} 站，比中间平均 {mid:.1f} 还多，建议减负")
    if route_ok["failed"]:
        print("ℹ️  部分路段驾车耗时查询失败（高德路径规划未开通或超时），已跳过")
    print(f"\n{'⛔ 有 ' + str(blockers) + ' 处硬伤，先改再出发' if blockers else '✓ 没有硬伤'}")
    sys.exit(1 if blockers else 0)


if __name__ == "__main__":
    main()
