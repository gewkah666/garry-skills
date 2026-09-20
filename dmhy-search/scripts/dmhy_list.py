#!/usr/bin/env python3
"""
dmhy_list.py - 列出 DMHY RSS 最新种子
用法:
  python dmhy_list.py [--limit 20] [--category 动画] [--json]
"""
import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from urllib.request import urlopen, Request
from urllib.error import URLError
from xml.etree import ElementTree as ET

RSS_URL = "https://share.dmhy.org/topics/rss/rss.xml"
CACHE = Path.home() / ".cache" / "dmhy-search" / "rss.xml"
CACHE_TTL_MIN = 30

CATEGORY_NAMES = {
    "2": "動畫", "3": "漫畫", "4": "動漫音樂", "6": "日劇",
    "7": "ＲＡＷ", "8": "遊戲", "9": "ＴＶ剧", "10": "特攝",
    "12": "動畫（下載區）", "13": "漫畫（下載區）",
}


def _local_proxy():
    """找可用的本机代理（cron 直连 DMHY 常被墙/超时，须走代理兜底）。"""
    import socket
    cand = []
    for k in ("HTTPS_PROXY", "https_proxy", "ALL_PROXY", "all_proxy"):
        v = os.environ.get(k, "")
        if "127.0.0.1" in v or "localhost" in v:
            cand.append(v.rsplit("://", 1)[-1])
    cand.append("127.0.0.1:12334")
    cand += ["127.0.0.1:7890", "127.0.0.1:7897"]
    for c in cand:
        try:
            host, port = c.rsplit(":", 1)
            with socket.create_connection((host, int(port)), timeout=1):
                return "http://" + host + ":" + port
        except Exception:
            continue
    return None


def _open_rss(use_proxy=False):
    req = Request(RSS_URL, headers={"User-Agent": "Mozilla/5.0"})
    if use_proxy:
        import urllib.request
        px = _local_proxy()
        if not px:
            raise URLError("no local proxy available")
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({"https": px, "http": px}))
        return opener.open(req, timeout=30)
    return urlopen(req, timeout=20)


def fetch_rss(force: bool = False) -> bytes:
    """读取 RSS，缓存 30 分钟；直连失败自动走本机代理。"""
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    if not force and CACHE.exists():
        age = (datetime.now().timestamp() - CACHE.stat().st_mtime) / 60
        if age < CACHE_TTL_MIN:
            return CACHE.read_bytes()
    for use_proxy in (False, True):
        try:
            with _open_rss(use_proxy=use_proxy) as resp:
                data = resp.read()
            CACHE.write_bytes(data)
            if use_proxy:
                sys.stderr.write("[info] direct failed, fetched RSS via local proxy\n")
            return data
        except (URLError, OSError) as e:
            if not use_proxy:
                continue
            if CACHE.exists():
                sys.stderr.write(f"[warn] fetch failed, using stale cache: {e}\n")
                return CACHE.read_bytes()
            raise
    raise URLError("fetch_rss: direct and proxy both failed")


def parse_items(xml_bytes: bytes) -> list:
    """解析 RSS items 为 list[dict]."""
    root = ET.fromstring(xml_bytes)
    items = []
    for item in root.findall(".//item"):
        title = item.findtext("title") or ""
        link = item.findtext("link") or ""
        pub = item.findtext("pubDate") or ""
        author = item.findtext("author") or ""
        enclosure = item.find("enclosure")
        magnet = enclosure.get("url") if enclosure is not None else ""
        cat_el = item.find("category")
        category = cat_el.text if cat_el is not None else ""
        cat_domain = cat_el.get("domain", "") if cat_el is not None else ""
        # 提取 sort_id
        sort_id = ""
        if "sort_id/" in cat_domain:
            sort_id = cat_domain.split("sort_id/")[-1].rstrip("/")
        items.append({
            "title": title.strip(),
            "link": link,
            "pubDate": pub,
            "author": author,
            "category": category,
            "sort_id": sort_id,
            "magnet": magnet,
        })
    return items


def format_row(item: dict) -> str:
    """格式化为单行表格。"""
    pub = item["pubDate"][:16] if item["pubDate"] else "?"
    title = item["title"]
    if len(title) > 80:
        title = title[:77] + "..."
    return f"{pub}  [{item['category']}]  {title}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=20, help="最多显示多少条")
    ap.add_argument("--category", help="按分类筛选（动画/漫画/日剧 等中文名）")
    ap.add_argument("--force", action="store_true", help="强制刷新缓存")
    ap.add_argument("--json", action="store_true", help="输出 JSON")
    args = ap.parse_args()

    # 中文名 → sort_id (支持简繁模糊匹配)
    target_sort_id = None
    if args.category:
        # 简单简繁映射
        aliases = {"动画": "動畫", "漫画": "漫畫", "日剧": "日劇", "游戏": "遊戲",
                   "动漫音乐": "動漫音樂"}
        canonical = aliases.get(args.category, args.category)
        for sid, name in CATEGORY_NAMES.items():
            if name == canonical or canonical in name or args.category in name:
                target_sort_id = sid
                break
        if target_sort_id is None:
            sys.stderr.write(f"未识别分类: {args.category}, 可选: {list(CATEGORY_NAMES.values())}\n")
            sys.exit(1)

    xml = fetch_rss(force=args.force)
    items = parse_items(xml)

    if target_sort_id:
        items = [it for it in items if it["sort_id"] == target_sort_id]

    items = items[:args.limit]

    if args.json:
        print(json.dumps(items, ensure_ascii=False, indent=2))
    else:
        print(f"DMHY 最新 {len(items)} 条 (源: share.dmhy.org):\n")
        for it in items:
            print(format_row(it))
        print(f"\n提示: 加上 --json 输出 JSON, 或加 --category 筛选分类")


if __name__ == "__main__":
    main()