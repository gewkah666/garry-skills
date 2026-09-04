#!/usr/bin/env python3
"""
dmhy_pick.py - 智能匹配剧名磁链（解析季数、集数、分辨率、Fin 标记）
用法:
  python dmhy_pick.py "葬送的芙莉莲" --season 2 --resolution 1080p --json
  python dmhy_pick.py "高木同学" --fin --resolution 1080p
  python dmhy_pick.py "鬼灭之刃" --latest
"""
import argparse
import json
import re
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from dmhy_list import fetch_rss, parse_items


# 季数正则: S2 / 第2季 / Season 2 / S02 / 2nd Season
SEASON_RE = re.compile(
    r"(?:\[(?:S|Season|第)\s*(\d{1,2})\]|\[(\d{1,2})(?:nd|rd|th|st)\s*Season\]|\bS(\d{2})\b)",
    re.IGNORECASE,
)
# 集数正则: [12] / -12 / 01-12 / E12 / 第12话
EPISODE_RE = re.compile(
    r"[\[-]\s*(\d{1,3})(?:[\]\-v]|話|话|END|v2)?\s*[\]]?",
)
# 分辨率
RESOLUTION_RE = re.compile(r"(2160p|1080p|720p|480p|4K|WEBrip|BDRip|DVDrip|HDrip)", re.IGNORECASE)
# Fin 标记
FIN_RE = re.compile(r"\bFin\b|\[Fin\]|Complete", re.IGNORECASE)


def score_item(item: dict, args) -> int:
    """打分:满足约束越多分越高。"""
    title = item["title"]
    score = 0
    if args.season is not None:
        m = SEASON_RE.search(title)
        if not m:
            return -1
        season_nums = [int(g) for g in m.groups() if g]
        if not season_nums or season_nums[0] != args.season:
            return -1
        score += 10
    if args.resolution:
        if args.resolution.lower() not in title.lower():
            return -1
        score += 5
    if args.episode is not None:
        m = EPISODE_RE.search(title)
        if not m:
            return -1
        ep_nums = [int(g) for g in m.groups() if g and g.isdigit()]
        if not ep_nums or ep_nums[0] != args.episode:
            return -1
        score += 8
    if args.fin:
        if not FIN_RE.search(title):
            return -1
        score += 3
    # 默认偏好:更精细的视频源
    if "BDRip" in title or "WEB-DL" in title:
        score += 2
    if "HEVC" in title or "H265" in title:
        score += 1
    return score


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("name", help="剧名关键词")
    ap.add_argument("--season", type=int, help="季数 (如 2)")
    ap.add_argument("--episode", type=int, help="单集集数 (如 8)")
    ap.add_argument("--resolution", help="分辨率 (1080p / 720p / WEBrip / BDRip)")
    ap.add_argument("--fin", action="store_true", help="仅匹配完结版 (Fin)")
    ap.add_argument("--latest", action="store_true", help="返回最新一条（不论季/集）")
    ap.add_argument("--limit", type=int, default=5, help="最多返回多少条（默认 5）")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--force", action="store_true", help="强制刷新 RSS")
    args = ap.parse_args()

    xml = fetch_rss(force=args.force)
    items = parse_items(xml)

    # 名称预过滤
    candidates = [it for it in items if args.name.lower() in it["title"].lower()]
    if not candidates:
        print(f"未找到任何匹配 \"{args.name}\" 的种子")
        sys.exit(1)

    if args.latest:
        hit = candidates[0]
        results = [hit]
    else:
        scored = [(score_item(it, args), it) for it in candidates]
        # 过滤掉 -1（不满足约束）
        scored = [(s, it) for s, it in scored if s >= 0]
        scored.sort(key=lambda x: (-x[0], x[1]["pubDate"]), reverse=False)
        # 排序后按 pubDate 倒序
        scored.sort(key=lambda x: x[1]["pubDate"], reverse=True)
        # 重新按分数倒序但同分按日期
        scored.sort(key=lambda x: (-x[0], x[1]["pubDate"]), reverse=True)
        results = [it for s, it in scored[:args.limit]]

    if args.json:
        print(json.dumps(results, ensure_ascii=False, indent=2))
    else:
        print(f"匹配 \"{args.name}\" 找到 {len(results)} 条:\n")
        for it in results:
            print(f"[{it['pubDate'][:16]}]  {it['title']}")
            print(f"  magnet: {it['magnet'][:100]}...")
            print()


if __name__ == "__main__":
    main()