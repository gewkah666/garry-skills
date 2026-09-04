#!/usr/bin/env python3
"""
dmhy_search.py - 按关键词搜索 DMHY RSS 中的种子
支持多关键词 AND 匹配。
用法:
  python dmhy_search.py "鬼灭之刃"
  python dmhy_search.py "高木同学" "WEBrip"  --json --limit 5
  python dmhy_search.py "葬送的芙莉莲" --filter fin
"""
import argparse
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from dmhy_list import fetch_rss, parse_items, format_row


def search(items: list, keywords: list, filter_fin: bool = False) -> list:
    """关键词 AND 匹配 (大小写不敏感),可选只保留 Fin 完结版。"""
    keywords_lower = [k.lower() for k in keywords]
    results = []
    for it in items:
        title = it["title"]
        title_lower = title.lower()
        if not all(k in title_lower for k in keywords_lower):
            continue
        if filter_fin and "Fin" not in title and "[Fin]" not in title:
            continue
        results.append(it)
    return results


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("keywords", nargs="+", help="关键词 (多个表示 AND)")
    ap.add_argument("--limit", type=int, default=10)
    ap.add_argument("--filter-fin", action="store_true", help="仅显示 Fin 完结版")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--force", action="store_true", help="强制刷新 RSS 缓存")
    args = ap.parse_args()

    xml = fetch_rss(force=args.force)
    items = parse_items(xml)
    hits = search(items, args.keywords, filter_fin=args.filter_fin)
    hits = hits[:args.limit]

    if args.json:
        print(json.dumps(hits, ensure_ascii=False, indent=2))
    else:
        print(f"搜索: {' '.join(args.keywords)}, 命中 {len(hits)} 条\n")
        for it in hits:
            print(format_row(it))
            if it.get("magnet"):
                m = it["magnet"]
                if len(m) > 100:
                    m = m[:97] + "..."
                print(f"  magnet: {m}")
            print()


if __name__ == "__main__":
    main()