#!/usr/bin/env python3
"""
validate_guide.py - 审计 guide.json（借鉴 personalized-travel-guide 的 release validation，缩成个人行程够用的版本）

  ⛔ 硬伤：缺标题 / 日期 / 站点；note / guard / 须知里的套话；转场车程比到下一站的空档还长；日期顺序错
  ⚠️ 不足：章节数量低于下限、站点没坐标也没标 pending、须知太短、每日 photo 缺
  💡 提示：缺 source、TODO / 待补、景点缺营业信息

用法: validate_guide.py guide.json [--strict]     --strict 时 ⚠️ 也算失败
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path

FILLER = re.compile(r"注意安全|量力而行|合理安排|保持体力|提前规划|劳逸结合|多拍照|注意休息|谨慎出行")
TODO = re.compile(r"TODO|待补|xxx|待填", re.IGNORECASE)
MIN = {"sights": 6, "restaurants": 4, "snacks": 4, "prep": 12, "notes_per_fold": 3, "note_len": 34}


def hm(s: str) -> int:
    try:
        h, m = s.split(":")
        return int(h) * 60 + int(m)
    except Exception:  # noqa: BLE001
        return -1


def walk_strings(obj, path=""):
    if isinstance(obj, str):
        yield path, obj
    elif isinstance(obj, dict):
        for k, v in obj.items():
            yield from walk_strings(v, f"{path}.{k}" if path else k)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from walk_strings(v, f"{path}[{i}]")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("guide")
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args()
    g = json.loads(Path(args.guide).read_text())
    hard, warn, tip = [], [], []

    meta = g.get("meta", {})
    for k in ("title", "start", "end"):
        if not meta.get(k):
            hard.append(f"meta.{k} 为空")
    if not meta.get("destination"):
        warn.append("meta.destination 为空（封面用）")

    days = g.get("days", [])
    if not days:
        hard.append("没有 days")
    last_date = ""
    for d in days:
        label = d.get("day") or d.get("date")
        if not d.get("date"):
            hard.append(f"{label}: 缺 date")
        elif d["date"] < last_date:
            hard.append(f"{label}: 日期顺序错（{d['date']} < {last_date}）")
        last_date = d.get("date", last_date)
        stops = d.get("stops", [])
        if not stops:
            hard.append(f"{label}: 没有站点")
        if not d.get("summary"):
            warn.append(f"{label}: 缺 summary（写清顺序与转场理由）")
        if not d.get("photo"):
            tip.append(f"{label}: 没有 photo 提示（每天 2–3 条，各天不同）")
        for a, b in zip(stops, stops[1:]):
            tr = a.get("transfer") or {}
            gap = hm(b.get("time", "")) - hm(a.get("end_time") or a.get("time", ""))
            if tr.get("minutes") and gap >= 0 and tr["minutes"] > gap + 10 and not a.get("is_transit") and not b.get("is_transit"):
                hard.append(f"{label}: {a.get('place')} → {b.get('place')} 车程 {tr['minutes']} 分钟，只留了 {gap} 分钟")
        for s in stops:
            sn = f"{label} {s.get('time', '')} {s.get('name', '')}"
            if s.get("is_transit"):
                continue
            if not s.get("coords") and s.get("status") != "pending":
                warn.append(f"{sn}: 没坐标也没标 status=pending")
            if not (s.get("note") or s.get("guard")):
                warn.append(f"{sn}: 没有 note / guard")
            for k in ("note", "guard"):
                if s.get(k) and FILLER.search(s[k]):
                    hard.append(f"{sn}: {k} 是套话「{s[k]}」")
            if s.get("note") and len(s["note"]) < 8:
                tip.append(f"{sn}: note 太短")

    sights = g.get("sights", [])
    if len(sights) < MIN["sights"]:
        warn.append(f"sights 只有 {len(sights)} 个（建议 ≥ {MIN['sights']}）")
    for s in sights:
        if s.get("status") not in ("scheduled", "optional"):
            warn.append(f"景点 {s.get('name')}: status 应为 scheduled / optional")
        missing = [k for k in ("hours", "duration", "why") if not s.get(k)]
        if missing:
            tip.append(f"景点 {s.get('name')}: 缺 {'/'.join(missing)}")
        if not s.get("source") and (s.get("hours") or s.get("ticket")):
            tip.append(f"景点 {s.get('name')}: 有营业 / 门票信息但没 source")

    food = g.get("food", {})
    rs, sn = food.get("restaurants", []), food.get("snacks", [])
    if len(rs) < MIN["restaurants"]:
        warn.append(f"restaurants 只有 {len(rs)} 家（建议 ≥ {MIN['restaurants']}）")
    if sn and len(sn) != MIN["snacks"]:
        warn.append(f"snacks 有 {len(sn)} 个（模型要求恰好 {MIN['snacks']}）")
    for r in rs:
        if not (r.get("dishes") and r.get("price")):
            tip.append(f"餐厅 {r.get('name')}: 缺招牌菜或人均")
    if rs and len({r.get("cuisine") for r in rs}) < 3:
        tip.append("餐厅菜系不足 3 种")

    prep = g.get("prep", {})
    n_prep = len(prep.get("essentials", [])) + len(prep.get("confirm", []))
    if n_prep < MIN["prep"]:
        warn.append(f"prep 共 {n_prep} 条（建议 ≥ {MIN['prep']}）")

    notes = g.get("notes", {})
    for fold in ("weather", "culture", "transport", "safety", "payment"):
        items = notes.get(fold, [])
        if len(items) < MIN["notes_per_fold"]:
            warn.append(f"notes.{fold} 只有 {len(items)} 条（每折 3–4 条）")
        for it in items:
            if re.match(r"^提示\s*\d", it.get("title", "")):
                hard.append(f"notes.{fold}: 小标题「{it['title']}」是模板词")
            if FILLER.search(it.get("text", "")):
                hard.append(f"notes.{fold}「{it.get('title')}」: 套话")
            elif len(it.get("text", "")) < MIN["note_len"]:
                warn.append(f"notes.{fold}「{it.get('title')}」: 太短（≥ {MIN['note_len']} 字，两句：情况 + 动作）")

    for grp in g.get("language", []):
        if len(grp.get("items", [])) < 5:
            warn.append(f"language「{grp.get('group')}」不足 5 条")

    if not g.get("legs"):
        warn.append("legs 为空（航段 / 车次；没订就写 status=pending）")
    if not g.get("stays"):
        warn.append("stays 为空（住宿；没订就写 status=pending）")

    for path, s in walk_strings(g):
        if TODO.search(s):
            tip.append(f"{path}: 含 TODO / 待补")

    for sym, items in (("⛔", hard), ("⚠️", warn), ("💡", tip)):
        for it in items:
            print(f"{sym} {it}")
    print(f"\n{len(hard)} 硬伤 · {len(warn)} 不足 · {len(tip)} 提示")
    bad = bool(hard) or (args.strict and bool(warn))
    print("❌ 未通过，先修再 build" if bad else "✓ 可以 build")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
