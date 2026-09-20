#!/usr/bin/env python3
"""
sync_outlook.py - guide.json 的每日行程 → Outlook 日历（trip-manager 的事件契约）

  sync_outlook.py output/<slug>/guide.json --project "川西 10.1-10.7" [--dry-run] [--keep-old]

默认先删掉行程日期范围内已有的行程事件（只删 trip_common 认作行程的事件，权益活动不动），
再按 days[].stops[] 逐站创建：标题 `DayN-k: icon 名称`，body 写 项目/起点/终点/交通/停留/要点/时限/费用。
删除前把原事件存到 ~/.cache/trip-manager/outlook-backup-<时间>.json。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

TM = Path.home() / "Projects" / "garry-skills" / "trip-manager" / "scripts"
sys.path.insert(0, str(TM))
from outlook_event import graph_request, normalize_transport, to_graph_dt  # noqa: E402
from trip_common import build_body, fetch_events  # noqa: E402

ARROW = re.compile(r"(.+?)\s*(?:→|->)\s*(.+)")


def stop_events(guide: dict, project: str):
    out = []
    for d in guide.get("days", []):
        date = d["date"]
        prev_place = None
        for k, s in enumerate(d.get("stops", []), 1):
            if not s.get("time"):
                continue
            start = datetime.fromisoformat(f"{date}T{s['time']}")
            end = datetime.fromisoformat(f"{date}T{s.get('end_time') or s['time']}")
            if end <= start:
                end = end + timedelta(days=1) if s.get("end_time") else start + timedelta(hours=1)
            transit = bool(s.get("is_transit"))
            origin = destination = None
            if transit:
                m = ARROW.search(re.sub(r"[（(].*?[)）]", lambda mm: mm.group(0) if "→" in mm.group(0) else "", s["name"]))
                inner = re.search(r"[（(]([^（）()]*→[^（）()]*)[)）]", s["name"])
                src = inner.group(1) if inner else s["name"]
                m = ARROW.search(src)
                if m:
                    origin, destination = m.group(1).strip(" ·"), m.group(2).strip(" ·")
                    destination = re.sub(r"[（(].*$", "", destination).strip() or destination
                else:
                    origin, destination = prev_place or "", s.get("place") or s["name"]
            transport = "飞机" if "✈" in (s.get("icon") or "") + (s.get("transport") or "") else ("汽车" if transit else None)
            title = f"{d.get('day', 'Day')}-{k}: {s.get('icon') or '📍'} {s['name']}"
            notes = "\n".join(x for x in [s.get("caption"), (d.get("summary") if k == 1 else None)] if x)
            body_html = build_body(
                notes=notes or None, project=project, origin=origin, destination=destination,
                transport=normalize_transport(transport) if transport else None,
                dwell=str(s["dwell_min"]) if (s.get("dwell_min") and not transit) else None,
                note=s.get("note"), guard=s.get("guard"), cost=s.get("cost"),
            )
            ev = {
                "subject": title,
                "body": {"contentType": "HTML", "content": body_html},
                "start": to_graph_dt(start.strftime("%Y-%m-%dT%H:%M")),
                "end": to_graph_dt(end.strftime("%Y-%m-%dT%H:%M")),
                "location": {"displayName": s.get("place") or destination or ""},
                "isReminderOn": True,
                "reminderMinutesBeforeStart": 30,
            }
            if transport:
                ev["categories"] = [normalize_transport(transport)]
            out.append(ev)
            prev_place = s.get("place") or destination or prev_place
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("guide")
    ap.add_argument("--project", required=True)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--keep-old", action="store_true", help="不删旧事件，只新建")
    a = ap.parse_args()
    g = json.loads(Path(a.guide).read_text())
    m = g["meta"]
    start, end = m["start"], m["end"]
    events = stop_events(g, a.project)
    print(f"guide {m.get('title')}：{start} → {end}，{len(events)} 个事件待创建")
    if a.dry_run:
        for e in events:
            print(f"  {e['start']['dateTime'][:16]} → {e['end']['dateTime'][11:16]}  {e['subject']}  @{e['location']['displayName']}  {e.get('categories', '')}")
        return
    if not a.keep_old:
        old = fetch_events(f"{start}T00:00:00+08:00", f"{(datetime.fromisoformat(end) + timedelta(days=1)).date()}T00:00:00+08:00")
        bk = Path.home() / ".cache" / "trip-manager" / f"outlook-backup-{time.strftime('%Y%m%d-%H%M%S')}.json"
        bk.parent.mkdir(parents=True, exist_ok=True)
        bk.write_text(json.dumps(old, ensure_ascii=False, indent=1, default=str))
        print(f"备份 {len(old)} 个旧事件 → {bk}")
        for e in old:
            graph_request("DELETE", f"/me/events/{e['id']}")
        print(f"✓ 已删除 {len(old)} 个旧事件")
    n = 0
    for e in events:
        r = graph_request("POST", "/me/events", e)
        n += 1
        print(f"✓ {e['start']['dateTime'][:16]}  {r.get('subject')}")
    print(f"✓ 已创建 {n} 个事件")


if __name__ == "__main__":
    main()
