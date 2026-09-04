#!/usr/bin/env python3
"""
bg_ongoing.py - 给定剧名列表,识别哪些仍在连载(追剧中)
用法:
  python bg_ongoing.py "转生史莱姆" "高木同学" "怪奇物语"
  python bg_ongoing.py "剧名1" "剧名2" ... --json
"""
import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from bg_search import search


def is_ongoing(item: dict, item_type: int = 2) -> bool:
    """
    判定连载中。

    Bangumi 的 series 字段语义是"属于系列"，对动画/漫画/书籍
    即使完结 series 也可能为 true。需结合 type 和 eps 判断:

    - type=2 动画: 已完结 = (series=false 且 eps>0) 或 (eps==total_episodes 且 total_episodes>0)
    - 其他类型 (书籍/漫画): 通常 series=true 即连载
    """
    series = item.get("series")
    eps = item.get("eps", 0) or 0
    total = item.get("total_episodes", 0) or 0

    if item_type == 2:  # 动画
        # 如果 series 字段明确为 False,表示不连载(完结/已完结/单季结束)
        if series is False:
            return False
        # 如果集数 == 总集数且 >0,已播完
        if total > 0 and eps >= total:
            return False
        # 否则视为仍在追
        return True
    else:  # 书籍/漫画/三次元等
        # series=True 表示连载中
        return series is True


def find_best_match(keyword: str, results: list):
    """从搜索结果挑最匹配的（一般第 0 条）"""
    if not results:
        return None
    # 优先 name_cn 完全包含关键词
    for r in results:
        cn = (r.get("name_cn") or "").lower()
        if keyword.lower() in cn:
            return r
    return results[0]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("names", nargs="+", help="剧名列表（多个）")
    ap.add_argument("--type", type=int, default=2, help="类型（默认 2=动画）")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    results = []
    for name in args.names:
        hits = search(name, args.type)
        best = find_best_match(name, hits)
        if not best:
            results.append({"name": name, "found": False})
            continue
        results.append({
            "name": name,
            "found": True,
            "subject_id": best["id"],
            "name_cn": best.get("name_cn") or best.get("name"),
            "ongoing": is_ongoing(best, args.type),
            "eps": best.get("eps"),
            "total_episodes": best.get("total_episodes"),
            "rating": best.get("rating", {}).get("score"),
        })
        time.sleep(0.5)  # 礼貌限速

    if args.json:
        print(json.dumps(results, ensure_ascii=False, indent=2))
    else:
        ongoing = [r for r in results if r.get("ongoing")]
        finished = [r for r in results if r.get("found") and not r.get("ongoing")]
        not_found = [r for r in results if not r.get("found")]

        print(f"=== 追剧中 ({len(ongoing)} 部) ===")
        for r in ongoing:
            print(f"  ✓ {r['name_cn']} [id={r['subject_id']}] eps={r['eps']}/{r['total_episodes']} score={r['rating']}")

        print(f"\n=== 已完结 ({len(finished)} 部) ===")
        for r in finished:
            print(f"  ✗ {r['name_cn']} [id={r['subject_id']}] eps={r['eps']}/{r['total_episodes']} score={r['rating']}")

        if not_found:
            print(f"\n=== 未找到 ({len(not_found)} 部) ===")
            for r in not_found:
                print(f"  ? {r['name']}")


if __name__ == "__main__":
    main()