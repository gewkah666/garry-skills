#!/usr/bin/env python3
"""
bg_subject.py - 查询 Bangumi subject 详情
用法:
  python bg_subject.py 388134
  python bg_subject.py 388134 --json
"""
import argparse
import json
import sys
import time
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

API = "https://api.bgm.tv/v0/subjects/{id}"
UA = "hermes-mcp/1.0 (https://github.com/hermes-agent)"
CACHE_DIR = Path.home() / ".cache" / "bangumi-resolve"
CACHE_TTL_SEC = 3600


def fetch_subject(subject_id: int) -> dict:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_file = CACHE_DIR / f"subject_{subject_id}.json"
    if cache_file.exists() and (time.time() - cache_file.stat().st_mtime) < CACHE_TTL_SEC:
        return json.loads(cache_file.read_text())

    url = API.format(id=subject_id)
    req = Request(url, headers={"User-Agent": UA})
    try:
        with urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read())
    except HTTPError as e:
        sys.stderr.write(f"[error] HTTP {e.code}: {e.reason}\n")
        if cache_file.exists():
            sys.stderr.write("  → 用 stale cache\n")
            return json.loads(cache_file.read_text())
        return {}
    except URLError as e:
        sys.stderr.write(f"[error] {e}\n")
        return {}

    cache_file.write_text(json.dumps(data, ensure_ascii=False))
    return data


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("subject_id", type=int, help="Bangumi subject ID")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    data = fetch_subject(args.subject_id)
    if not data:
        print(f"未找到 subject {args.subject_id}")
        sys.exit(1)

    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return

    print(f"Subject {data.get('id')} — {data.get('name_cn') or data.get('name')}\n")
    print(f"  原名:       {data.get('name')}")
    print(f"  中文名:     {data.get('name_cn', '(无)')}")
    print(f"  类型:       {data.get('type')}")
    print(f"  连载状态:   {'连载中' if data.get('series') else '已完结'}")
    print(f"  已发布集数: {data.get('eps')}")
    print(f"  总集数:     {data.get('total_episodes')}")
    print(f"  开始日期:   {data.get('date', '(未知)')}")
    rating = data.get("rating", {})
    print(f"  评分:       {rating.get('score', 0)} (rank #{rating.get('rank', 0)})")
    print(f"  平台:       {data.get('platform', '(未知)')}")


if __name__ == "__main__":
    main()