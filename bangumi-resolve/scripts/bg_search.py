#!/usr/bin/env python3
"""
bg_search.py - 按剧名搜索 Bangumi subject
用法:
  python bg_search.py "转生史莱姆" --type 2
  python bg_search.py "高木同学" --json
"""
import argparse
import json
import sys
import time
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

API = "https://api.bgm.tv/v0/search/subjects"
UA = "hermes-mcp/1.0 (https://github.com/hermes-agent)"
CACHE_DIR = Path.home() / ".cache" / "bangumi-resolve"
CACHE_TTL_SEC = 3600  # 1 hour

# type 编码
TYPES = {"1": "书籍", "2": "动画", "3": "音乐", "4": "游戏", "6": "三次元"}


def search(keyword: str, stype: int = 2, limit: int = 10) -> list:
    """搜索 Bangumi。type 默认为 2(动画)。"""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_file = CACHE_DIR / f"search_{stype}_{keyword}.json"
    if cache_file.exists() and (time.time() - cache_file.stat().st_mtime) < CACHE_TTL_SEC:
        return json.loads(cache_file.read_text())

    payload = json.dumps({"keyword": keyword, "type": stype}).encode("utf-8")
    req = Request(API, data=payload, headers={
        "User-Agent": UA,
        "Content-Type": "application/json",
    })
    try:
        with urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read())
    except HTTPError as e:
        sys.stderr.write(f"[error] HTTP {e.code}: {e.reason}\n")
        if e.code == 412:
            sys.stderr.write("  → UA 被拒,尝试更换 User-Agent\n")
        return []
    except URLError as e:
        sys.stderr.write(f"[error] {e}\n")
        return []

    results = data.get("data", [])[:limit]
    cache_file.write_text(json.dumps(results, ensure_ascii=False))
    return results


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("keyword", help="剧名关键词")
    ap.add_argument("--type", type=int, default=2, choices=[1, 2, 3, 4, 6],
                    help="类型: 1=书籍 2=动画 3=音乐 4=游戏 6=三次元 (默认 2)")
    ap.add_argument("--limit", type=int, default=10)
    ap.add_argument("--ongoing-only", action="store_true", help="仅显示连载中")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    results = search(args.keyword, args.type, args.limit)
    if args.ongoing_only:
        results = [r for r in results if r.get("series") is True]

    if args.json:
        print(json.dumps(results, ensure_ascii=False, indent=2))
    else:
        if not results:
            print(f"未找到 \"{args.keyword}\" (type={TYPES[str(args.type)]})")
            return
        print(f"搜索 \"{args.keyword}\" ({TYPES[str(args.type)]}), 命中 {len(results)} 条:\n")
        for i, r in enumerate(results, 1):
            status = "连载中" if r.get("series") else "已完结"
            cn = r.get("name_cn") or r.get("name")
            print(f"{i}. [id={r['id']}] [{status}] {cn}")
            print(f"   原名: {r.get('name')}")
            print(f"   类型: {TYPES[str(r.get('type', 0))]}  "
                  f"集数: {r.get('eps', 0)}/{r.get('total_episodes', 0)}  "
                  f"评分: {r.get('rating', {}).get('score', 0)}")


if __name__ == "__main__":
    main()