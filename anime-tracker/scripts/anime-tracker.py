#!/usr/bin/env python3
"""
anime-tracker.py - 追剧自动搜磁力 (主入口)

读 ~/.config/anime-tracker/watchlist.yaml →
Bangumi 判定连载状态 → DMHY 搜磁力 → NAS qBittorrent WebAPI 提交
（--fallback-aria2 可退回本机 aria2；默认不再往 rclone 挂载目录写）

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
from typing import Optional
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
# 旧版事故目录（rclone 挂载直写会产生 0 字节占位假文件）——仅在 --fallback-aria2 时用
NAS_BASE = "/Users/garry/临时/zspace/ZSPACE/sata11-15700085549/电影&电视剧/Anime"
CONFIG_PATH = Path.home() / ".config" / "anime-tracker" / "watchlist.yaml"
ENV_PATH = Path.home() / ".hermes" / ".env"


def load_env_file(path: Path = ENV_PATH) -> dict:
    """极简 .env 解析（KEY=VALUE，忽略注释/空行），不覆盖已有环境变量。"""
    import os
    env = dict(os.environ)
    if path.exists():
        for line in path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            env.setdefault(k.strip(), v.strip().strip('"').strip("'"))
    return env


ENV = load_env_file()
QB_URL = ENV.get("QBT_URL", "http://192.168.31.149:8089")
QB_KEY = ENV.get("QBT_API_KEY", "")
QB_BASE_DIR = "/downloads"  # qb 容器内路径 = NAS /sata11/my/data/qb/Downloads（极影视扫描范围内）


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
    """【备用】通过 RPC 提交磁力到本机 aria2 daemon。返回 GID。"""
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


def qb_request(path: str, form: Optional[dict] = None) -> str:
    """qBittorrent WebAPI：GET 或表单 POST，Bearer key 认证（御主明令勿用密码）。"""
    data = None
    headers = {"Authorization": f"Bearer {QB_KEY}"}
    if form is not None:
        from urllib.parse import urlencode
        data = urlencode(form).encode()
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    req = Request(QB_URL + path, data=data, headers=headers)
    with urlopen(req, timeout=30) as resp:
        return resp.read().decode().strip()


def call_qb_add(magnet: str, save_path: str) -> str:
    """提交磁力到 NAS qBittorrent。返回回执串或 'error: ...'。
    qb≤4 返回 'ok'；qb5+ 返回 JSON（added_torrent_ids / failure_count）。"""
    if not QB_KEY:
        return "error: QBT_API_KEY 未配置（~/.hermes/.env）"
    try:
        r = qb_request("/api/v2/torrents/add", {"urls": magnet, "savepath": save_path})
        if r == "ok" or r == "":
            return "ok"
        try:
            data = json.loads(r)
            if data.get("failure_count"):
                return f"error: {r[:150]}"
            ids = data.get("added_torrent_ids") or []
            return "ok" if ids else f"error: empty reply {r[:100]}"
        except json.JSONDecodeError:
            return f"error: {r[:100]}"
    except Exception as e:
        return f"error: {e}"


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


def process_item(item: dict, dry_run: bool = True, fallback_aria2: bool = False) -> dict:
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

    if fallback_aria2:
        target_dir = f"{NAS_BASE}/{target_name}"
    else:
        target_dir = f"{QB_BASE_DIR}/{target_name}"

    if dry_run:
        return {
            "name": name,
            "status": "dry-run",
            "subject_id": status["subject_id"],
            "name_cn": status["name_cn"],
            "dmhy_title": latest["title"],
            "magnet": magnet[:80] + "...",
            "target": target_dir,
            "engine": "aria2" if fallback_aria2 else "qb",
        }

    if fallback_aria2:
        gid = call_aria2_add(magnet, target_dir)
    else:
        gid = call_qb_add(magnet, target_dir)
        if gid.startswith("error"):
            return {"name": name, "status": "submit-failed", "reason": gid,
                    "subject_id": status["subject_id"], "name_cn": status["name_cn"]}
    return {
        "name": name,
        "status": "submitted",
        "subject_id": status["subject_id"],
        "name_cn": status["name_cn"],
        "dmhy_title": latest["title"],
        "gid": gid,
        "target": target_dir,
        "engine": "aria2" if fallback_aria2 else "qb",
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--watchlist", default=str(CONFIG_PATH))
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--fallback-aria2", action="store_true",
                    help="退回本机 aria2 + rclone 挂载目录（默认 NAS qb）")
    args = ap.parse_args()

    watchlist = load_watchlist(Path(args.watchlist).expanduser())
    if not watchlist:
        sys.stderr.write(f"watchlist 为空或未找到: {args.watchlist}\n")
        sys.exit(1)

    results = []
    for item in watchlist:
        r = process_item(item, dry_run=args.dry_run, fallback_aria2=args.fallback_aria2)
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
                print(f"  目标: {r['target']} ({r.get('engine','qb')})")
            elif status == "submitted":
                print(f"  回执: {r['gid']}")
                print(f"  目标: {r['target']} ({r.get('engine','qb')})")
            elif status == "submit-failed":
                print(f"  提交失败: {r.get('reason')}")
            elif status == "already-finished":
                print(f"  eps={r.get('eps')}/{r.get('total_episodes')} (已完结,跳过)")
            elif status in ("no-dmhy-match", "resolve-failed"):
                print(f"  原因: {r.get('reason')}")
            elif status == "no-magnet":
                print(f"  命中但无磁力")


if __name__ == "__main__":
    main()