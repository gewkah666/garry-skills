#!/usr/bin/env python3
"""
anime-tracker.py - 追剧自动搜磁力 (主入口)

读 ~/.config/anime-tracker/watchlist.yaml →
Bangumi 判定连载状态 → DMHY 搜磁力 → aria2 RPC 提交

用法:
  python anime-tracker.py --dry-run
  python anime-tracker.py --watchlist ~/my-watchlist.yaml
"""
import argparse
import json
import subprocess
import sys
import time
from pathlib import Path
from urllib.request import Request, urlopen

# 把 bangumi-resolve 和 dmhy-search 加进 sys.path
SKILL_DIR = Path(__file__).parent
RESOLVE_DIR = (SKILL_DIR.parent.parent / "bangumi-resolve" / "scripts").resolve()
DMHY_DIR = (SKILL_DIR.parent.parent / "dmhy-search" / "scripts").resolve()
sys.path.insert(0, str(RESOLVE_DIR))
sys.path.insert(0, str(DMHY_DIR))

from bg_search import search as bg_search  # noqa: E402
from bg_subject import fetch_subject  # noqa: E402
from bg_ongoing import is_ongoing  # noqa: E402
from dmhy_list import fetch_rss, parse_items  # noqa: E402

ARIA2_URL = "http://localhost:6800/jsonrpc"
ARIA2_TOKEN = "hermes_rpc_2026"
NAS_BASE = "/Volumes/sata11-157XXXX5549/电影&电视剧/Anime"
CONFIG_PATH = Path.home() / ".config" / "anime-tracker" / "watchlist.yaml"


def load_watchlist(path: Path) -> list:
    """简单 YAML 解析（避免引入 pyyaml 依赖）"""
    if not path.exists():
        return []
    text = path.read_text()
    items = []
    current = None
    for line in text.splitlines():
        # 跳过空行和注释
        if not line.strip() or line.strip().startswith("#"):
            continue
        # 顶层缩进为 0 的 "- " 表示新条目
        if line.startswith("- "):
            if current:
                items.append(current)
            current = {}
            # 同一行可能有 "key: value" 形式
            kv = line[2:].strip()
            if ":" in kv:
                key, val = kv.split(":", 1)
                current[key.strip()] = val.strip().strip("'\"")
            else:
                current["name_cn"] = kv.strip("'\"")
        # 缩进的 "key: value" 属于当前条目
        elif current is not None and ":" in line:
            stripped = line.strip()
            key, val = stripped.split(":", 1)
            current[key.strip()] = val.strip().strip("'\"")
    if current:
        items.append(current)
    return items


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
    """复用 dmhy_list 的 RSS 解析。"""
    xml = fetch_rss(force=False)
    items = parse_items(xml)
    matches = [it for it in items if name.lower() in it["title"].lower()]
    return matches[:limit]


def resolve_status(item: dict) -> dict:
    """
    根据 item 决定追剧状态。

    支持多种 bangumi_id 形式:
      - bangumi_id: 515594  (单值)
      - bangumi_ids: [515594, 616596, 616597]  (任一未完结即追剧)
      - force_ongoing: true  (跳过 Bangumi 判定,直接当追剧处理)

    force_ongoing 适用于:
      - Bangumi 数据滞后/不准确(如年番切季度)
      - Master 自有渠道已知在追
    """
    # 1) force_ongoing 优先级最高
    if item.get("force_ongoing"):
        return {
            "found": True,
            "subject_id": None,
            "name_cn": item.get("name_cn"),
            "ongoing": True,
            "eps": item.get("last_known_eps"),  # Master 已知进度
            "total_episodes": None,
            "forced": True,
        }

    bg_ids = []
    if item.get("bangumi_id"):
        bg_ids.append(int(item["bangumi_id"]))
    if item.get("bangumi_ids"):
        bg_ids.extend(int(x) for x in item["bangumi_ids"])

    if bg_ids:
        # 多 Bangumi ID: 任一未完结 → 追剧
        subjects = []
        for bg_id in bg_ids:
            try:
                s = fetch_subject(bg_id)
                if s:
                    subjects.append(s)
            except Exception:
                continue
        if not subjects:
            return {"found": False, "reason": f"bangumi_ids={bg_ids} not found"}
        # 任一未完结
        any_ongoing = any(is_ongoing(s, 2) for s in subjects)
        # 收集集数最大值
        max_eps = max((s.get("eps", 0) or 0) for s in subjects)
        # name 选第一个
        first = subjects[0]
        return {
            "found": True,
            "subject_id": first["id"],
            "name_cn": first.get("name_cn") or first.get("name"),
            "ongoing": any_ongoing,
            "eps": max_eps,
            "total_episodes": first.get("total_episodes"),
        }

    # 否则用关键词搜
    name = item.get("name_cn", "")
    bg_hits = bg_search(name, stype=2, limit=5)
    if not bg_hits:
        return {"found": False, "reason": "no bangumi hit"}
    best = bg_hits[0]
    return {
        "found": True,
        "subject_id": best["id"],
        "name_cn": best.get("name_cn") or best.get("name"),
        "ongoing": is_ongoing(best, 2),
        "eps": best.get("eps"),
        "total_episodes": best.get("total_episodes"),
    }


def process_item(item: dict, dry_run: bool = True) -> dict:
    """单剧处理流水线。"""
    name = item.get("name_cn", "?")
    status = resolve_status(item)
    if not status.get("found"):
        return {"name": name, "status": "resolve-failed", "reason": status.get("reason")}

    if not status["ongoing"]:
        return {
            "name": name,
            "status": "already-finished",
            "subject_id": status["subject_id"],
            "name_cn": status["name_cn"],
            "eps": status.get("eps"),
            "total_episodes": status.get("total_episodes"),
        }

    # 追剧中 → DMHY 搜
    target_name = item.get("subdir") or status["name_cn"] or name
    dmhy_hits = search_dmhy(target_name, limit=5)
    if not dmhy_hits:
        dmhy_hits = search_dmhy(status["name_cn"], limit=5)
    if not dmhy_hits:
        return {
            "name": name,
            "status": "no-dmhy-match",
            "subject_id": status["subject_id"],
            "name_cn": status["name_cn"],
        }

    latest = dmhy_hits[0]
    magnet = latest.get("magnet", "")
    if not magnet.startswith("magnet:"):
        return {"name": name, "status": "no-magnet", "hit": latest}

    target_dir = f"{NAS_BASE}/{target_name}"

    if dry_run:
        return {
            "name": name,
            "status": "dry-run",
            "subject_id": status["subject_id"],
            "name_cn": status["name_cn"],
            "dmhy_title": latest["title"],
            "magnet": magnet[:80] + "...",
            "target": target_dir,
        }

    gid = call_aria2_add(magnet, target_dir)
    return {
        "name": name,
        "status": "submitted",
        "subject_id": status["subject_id"],
        "name_cn": status["name_cn"],
        "dmhy_title": latest["title"],
        "gid": gid,
        "target": target_dir,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--watchlist", default=str(CONFIG_PATH))
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    watchlist = load_watchlist(Path(args.watchlist).expanduser())
    if not watchlist:
        sys.stderr.write(f"watchlist 为空或未找到: {args.watchlist}\n")
        sys.exit(1)

    results = []
    for item in watchlist:
        r = process_item(item, dry_run=args.dry_run)
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
                print(f"  eps={r.get('eps')}/{r.get('total_episodes')} (已完结,跳过)")
            elif status in ("no-dmhy-match", "resolve-failed"):
                print(f"  原因: {r.get('reason')}")
            elif status == "no-magnet":
                print(f"  命中但无磁力")


if __name__ == "__main__":
    main()