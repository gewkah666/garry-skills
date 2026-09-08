#!/usr/bin/env python3
"""
init_guide.py - 生成 guide.json 骨架（行程从 trip-manager 来，其余章节留空给 agent 研究填写）

数据源（三选一）:
  --from-data <trip-manager/travel-guide/data.json>       build_data.py 的输出（推荐）
  --outlook --start YYYY-MM-DD --end YYYY-MM-DD [--region 四川省]
  --notion "父项目标题" [--region 四川省]

可选:
  --notes <place_content.json>   按站点名合并已有研究：{"地名": {"位置": "…", "正文": ["h2|…", "bul|…"]}}
  --refresh-days                 guide.json 已存在时只替换 days / route 相关内容，保留其它章节与人工填过的 note/guard/details/photo
  --slug / --title / --destination / --travelers / --pace / --vehicle

输出: trip-guide/output/<slug>/guide.json
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import List, Optional

HERE = Path(__file__).resolve().parent
SKILL_DIR = HERE.parent
TM_SCRIPTS = SKILL_DIR.parent / "trip-manager" / "scripts"
sys.path.insert(0, str(TM_SCRIPTS))
from trip_common import driving_minutes, geocode  # noqa: E402

OUTPUT_DIR = SKILL_DIR / "output"

PREP_SEED = {
    "essentials": [
        {"text": "身份证 / 驾照 / 行驶证（自驾）", "why": "景区与检查站都要查"},
        {"text": "充电宝 + 车充 + 线", "why": "导航 + 拍照一天耗两块电"},
        {"text": "离线地图（高德 / 两步路）提前下载目的地", "why": "山区失联路段"},
        {"text": "现金 300–500", "why": "寺院、路边摊、停车常无码"},
        {"text": "常用药：感冒、肠胃、创可贴", "why": ""},
    ],
    "confirm": [
        {"text": "所有住宿订单与入住电话", "when": "出发前 1 天"},
        {"text": "交通票 / 航班值机", "when": "出发前 1 天"},
        {"text": "需预约的景区门票 / 观光车", "when": "按各景区规则"},
    ],
}


def slugify(s: str) -> str:
    s = re.sub(r"[^\w\-]+", "-", s.strip().lower()).strip("-")
    return s or "trip"


# ---------------------------------------------------------------- 行程数据

def load_days(args) -> tuple:
    """返回 (title, days) —— days 是 trip-manager data.json 里的 days 结构"""
    if args.from_data:
        data = json.loads(Path(args.from_data).expanduser().read_text())
        return data["trip"].get("title", ""), data["trip"]["days"]
    import build_data  # noqa: E402  trip-manager 的
    if args.outlook:
        if not (args.start and args.end):
            sys.exit("--outlook 需要 --start / --end")
        days = build_data.outlook_days(args.start, args.end)
        title = next((d.get("project") for d in days if d.get("project")), f"{args.start} → {args.end}")
    else:
        pages = build_data.query_trip_pages(args.notion)
        days = [build_data.page_to_day(p) for p in pages]
        title = args.notion
    days.sort(key=lambda d: (d["date"], d["day"]))
    build_data.attach_coords(days, args.region or "")
    return title, days


def add_transfers(days: List[dict]) -> int:
    """相邻两站都有坐标 → 查高德驾车（分钟 / 公里），写到前一站的 transfer"""
    n = 0
    for d in days:
        stops = d["stops"]
        for a, b in zip(stops, stops[1:]):
            if a.get("transfer") or not (a.get("coords") and b.get("coords")):
                continue
            if a["coords"] == b["coords"]:
                continue
            r = driving_minutes(a["coords"], b["coords"])
            if r:
                a["transfer"] = {"minutes": r[0], "km": r[1]}
                n += 1
    return n


def merge_notes(days: List[dict], notes_path: Path) -> int:
    """把 place_content.json 风格的研究按站点名合并到 stop.details / caption"""
    content = json.loads(notes_path.expanduser().read_text())
    keys = list(content)
    n = 0

    def match(name: str) -> Optional[str]:
        cands = [name] + [x for x in re.split(r"[·・:：（(→\s]+", name) if len(x) >= 2]
        for c in cands:
            if c in content:
                return c
        for c in cands:
            for k in keys:
                if k in c or (len(k) >= 2 and c in k):
                    return k
        return None

    for d in days:
        for s in d["stops"]:
            if s.get("details"):
                continue
            k = match(s.get("place") or "") or match(s.get("name") or "")
            if not k:
                continue
            body = content[k]
            s["details"] = list(body.get("正文") or [])
            if body.get("位置") and not s.get("caption"):
                s["caption"] = body["位置"]
            n += 1
    return n


def to_guide_days(days: List[dict]) -> List[dict]:
    out = []
    for d in days:
        stops = []
        for s in d["stops"]:
            st = {
                "time": s.get("time", ""), "end_time": s.get("end_time", ""), "name": s.get("name", ""),
                "icon": s.get("icon", "📍"), "is_transit": bool(s.get("is_transit")),
                "place": s.get("place") or s.get("name", ""),
            }
            if s.get("is_transit"):
                st["origin"], st["destination"] = s.get("origin"), s.get("destination")
            if s.get("coords"):
                st["coords"] = s["coords"]
            else:
                st["status"] = "pending"
            for k in ("dwell_min", "cost", "note", "guard", "transport", "transfer", "details", "caption", "source"):
                if s.get(k):
                    st[k] = s[k]
            if s.get("notes"):
                st.setdefault("details", []).extend(f"bul|{x}" for x in s["notes"])
            stops.append(st)
        out.append({
            "day": d.get("day") or "", "date": d.get("date", ""), "icon": d.get("icon") or "📍",
            "title": d.get("title", ""), "area": "", "summary": "", "transport": d.get("transport", ""),
            "route": d.get("route") or [], "stops": stops, "photo": [], "fallback": "",
            "notion_url": d.get("url", ""),
        })
    return out


def seed_sights(days: List[dict]) -> List[dict]:
    seen, out = set(), []
    for d in days:
        for s in d["stops"]:
            if s["is_transit"] or not s.get("place"):
                continue
            if re.search(r"住宿|酒店|入住|机场|还车|取车", s["name"]):
                continue
            if s["place"] in seen:
                continue
            seen.add(s["place"])
            item = {"name": s["place"], "local_name": "", "area": "", "day": d["day"], "status": "scheduled",
                    "hours": "", "duration": "", "best_time": "", "ticket": "", "caution": "", "image": "", "source": "", "why": ""}
            if s.get("coords"):
                item["coords"] = s["coords"]
            out.append(item)
    return out


def refresh_days(old: dict, new_days: List[dict]) -> List[dict]:
    """保留旧 guide 里人工填的 note / guard / details / photo / summary 等，替换行程结构"""
    old_by_date = {d["date"]: d for d in old.get("days", [])}
    for nd in new_days:
        od = old_by_date.get(nd["date"])
        if not od:
            continue
        for k in ("area", "summary", "photo", "fallback"):
            if od.get(k):
                nd[k] = od[k]
        old_stops = {(s.get("place"), s.get("time")): s for s in od.get("stops", [])}
        old_by_place = {s.get("place"): s for s in od.get("stops", [])}
        for ns in nd["stops"]:
            os_ = old_stops.get((ns.get("place"), ns.get("time"))) or old_by_place.get(ns.get("place"))
            if not os_:
                continue
            for k in ("note", "guard", "details", "caption", "source", "cost", "photo"):
                if os_.get(k) and not ns.get(k):
                    ns[k] = os_[k]
    return new_days


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--from-data", help="trip-manager 的 data.json")
    src.add_argument("--outlook", action="store_true")
    src.add_argument("--notion", metavar="父项目标题")
    ap.add_argument("--start"); ap.add_argument("--end"); ap.add_argument("--region", default="")
    ap.add_argument("--notes", help="place_content.json 风格的已有研究")
    ap.add_argument("--slug"); ap.add_argument("--title"); ap.add_argument("--destination", default="")
    ap.add_argument("--travelers", default=""); ap.add_argument("--pace", default=""); ap.add_argument("--vehicle", default="")
    ap.add_argument("--no-transfer", action="store_true", help="不查转场车程")
    ap.add_argument("--refresh-days", action="store_true", help="已有 guide.json 时只刷新行程")
    ap.add_argument("--force", action="store_true", help="覆盖已有 guide.json")
    args = ap.parse_args()

    trip_title, raw_days = load_days(args)
    title = args.title or trip_title
    slug = args.slug or slugify(title)
    out_dir = OUTPUT_DIR / slug
    out_file = out_dir / "guide.json"

    if not args.no_transfer:
        print("🚗 查转场车程…")
        print(f"   {add_transfers(raw_days)} 段")
    if args.notes:
        print(f"📝 合并研究 {args.notes}: {merge_notes(raw_days, Path(args.notes))} 站")

    days = to_guide_days(raw_days)
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    if out_file.exists() and args.refresh_days:
        guide = json.loads(out_file.read_text())
        guide["days"] = refresh_days(guide, days)
        guide["meta"]["start"], guide["meta"]["end"] = days[0]["date"], days[-1]["date"]
        guide["meta"]["generated_at"] = now
        out_file.write_text(json.dumps(guide, ensure_ascii=False, indent=2))
        print(f"✓ 已刷新行程: {out_file}  ({len(days)} 天，其它章节保留)")
        return
    if out_file.exists() and not args.force:
        sys.exit(f"❌ {out_file} 已存在：用 --refresh-days 只刷新行程，或 --force 覆盖")

    guide = {
        "meta": {
            "title": title, "kicker": "ITINERARY", "destination": args.destination,
            "start": days[0]["date"] if days else "", "end": days[-1]["date"] if days else "",
            "travelers": args.travelers, "pace": args.pace, "vehicle": args.vehicle,
            "cover": "", "sources": [], "generated_at": now,
        },
        "legs": [], "stays": [],
        "days": days,
        "sights": seed_sights(days),
        "food": {"primer": [], "snacks": [], "restaurants": [], "chains": []},
        "experiences": [], "shopping": [],
        "prep": json.loads(json.dumps(PREP_SEED, ensure_ascii=False)),
        "notes": {"weather": [], "culture": [], "transport": [], "safety": [], "payment": []},
        "language": [],
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file.write_text(json.dumps(guide, ensure_ascii=False, indent=2))
    n_stops = sum(len(d["stops"]) for d in days)
    print(f"✓ 骨架已生成: {out_file}")
    print(f"  {len(days)} 天 / {n_stops} 站 / {len(guide['sights'])} 个景点待补 / 其余章节为空")
    print("  下一步：按 references/content-model.md 填写，然后 validate_guide.py → build_guide.py")


if __name__ == "__main__":
    main()
