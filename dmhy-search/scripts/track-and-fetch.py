#!/usr/bin/env python3
"""
track-and-fetch.py - 追剧自动搜磁力

给定剧名列表 → Bangumi 判定连载中 → DMHY 搜磁力 → aria2 RPC 提交

用法:
  python track-and-fetch.py "葬送的芙莉莲"
  python track-and-fetch.py "剧名1" "剧名2" ... --dry-run
  python track-and-fetch.py "葬送的芙莉莲" --subdir "Frieren"
"""
import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

SKILL_DIR = Path(__file__).parent
sys.path.insert(0, str(SKILL_DIR.parent.parent / "bangumi-resolve" / "scripts"))
sys.path.insert(0, str(SKILL_DIR.parent / "scripts"))

from bg_ongoing import is_ongoing  # noqa: E402
from bg_search import search as bg_search  # noqa: E402
from dmhy_list import fetch_rss, parse_items  # noqa: E402

ARIA2_URL = "http://localhost:6800/jsonrpc"
ARIA2_TOKEN = "hermes_rpc_2026"


def call_aria2_add(magnet: str, target_dir: str) -> str:
    """通过 RPC 提交磁力到 aria2 daemon。返回 GID。"""
    payload = json.dumps({
        "jsonrpc": "2.0", "id": 1, "method": "aria2.addUri",
        "params": [f"token:{ARIA2_TOKEN}", [magnet], {"dir": target_dir}]
    })
    result = subprocess.run(
        ["curl", "-s", "-X", "POST", ARIA2_URL, "-H", "Content-Type: application/json", "-d", payload],
        capture_output=True, text=True, timeout=30,
    )
    try:
        data = json.loads(result.stdout)
        return data.get("result", f"error: {result.stdout[:100]}")
    except Exception as e:
        return f"parse-error: {e}"


def search_dmhy(name: str, limit: int = 3) -> list:
    """调用 dmhy-search 的 RSS 解析（直接复用 fetch_rss+parse_items）"""
    xml = fetch_rss(force=False)
    items = parse_items(xml)
    matches = [it for it in items if name.lower() in it["title"].lower()]
    return matches[:limit]


def process(name: str, dry_run: bool = True, subdir: str = None) -> dict:
    """单剧处理流水线。返回 dict 含状态/magnet/gid。"""
    # Step 1: Bangumi 判定
    bg_hits = bg_search(name, stype=2, limit=5)
    if not bg_hits:
        return {"name": name, "status": "bangumi-not-found"}

    best = bg_hits[0]
    ongoing = is_ongoing(best, 2)
    if not ongoing:
        return {
            "name": name,
            "status": "already-finished",
            "name_cn": best.get("name_cn"),
            "eps": best.get("eps"),
        }

    # Step 2: DMHY 搜最新磁力
    dmhy_hits = search_dmhy(best.get("name_cn") or name, limit=3)
    if not dmhy_hits:
        # 兜底：用原名再搜
        dmhy_hits = search_dmby(name, limit=3)
    if not dmhy_hits:
        return {
            "name": name,
            "status": "dmhy-no-match",
            "name_cn": best.get("name_cn"),
        }

    # 取最近一条
    latest = dmhy_hits[0]
    magnet = latest.get("magnet", "")
    if not magnet.startswith("magnet:"):
        return {"name": name, "status": "no-magnet", "hit": latest}

    # Step 3: 提交 aria2 (dry_run 跳过)
    target_dir = "/Volumes/sata11-157XXXX5549/电影&电视剧/Anime"
    if subdir:
        target_dir = f"{target_dir}/{subdir}"
    else:
        target_dir = f"{target_dir}/{best.get('name_cn') or name}"

    if dry_run:
        return {
            "name": name,
            "status": "dry-run",
            "name_cn": best.get("name_cn"),
            "dmhy_title": latest["title"],
            "magnet": magnet[:80] + "...",
            "target": target_dir,
        }

    gid = call_aria2_add(magnet, target_dir)
    return {
        "name": name,
        "status": "submitted",
        "name_cn": best.get("name_cn"),
        "dmhy_title": latest["title"],
        "gid": gid,
        "target": target_dir,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("names", nargs="+", help="剧名列表（多个）")
    ap.add_argument("--dry-run", action="store_true", help="仅查询不下载")
    ap.add_argument("--subdir", help="指定子目录名（覆盖默认）")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    results = []
    for name in args.names:
        r = process(name, dry_run=args.dry_run, subdir=args.subdir)
        results.append(r)
        time.sleep(0.5)

    if args.json:
        print(json.dumps(results, ensure_ascii=False, indent=2))
    else:
        for r in results:
            status = r["status"]
            name = r.get("name_cn") or r.get("name")
            print(f"[{status}] {name}")
            if status == "dry-run":
                print(f"  磁力: {r['magnet']}")
                print(f"  目标: {r['target']}")
            elif status == "submitted":
                print(f"  GID: {r['gid']}")
                print(f"  目标: {r['target']}")
            elif status == "already-finished":
                print(f"  eps={r.get('eps')} (已完结,跳过)")
            elif status == "dmhy-no-match":
                print(f"  Bangumi 判定追剧中,但 DMHY 无最新磁力")
            elif status == "bangumi-not-found":
                print(f"  Bangumi 数据库无此剧")


if __name__ == "__main__":
    main()