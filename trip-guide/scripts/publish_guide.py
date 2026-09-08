#!/usr/bin/env python3
"""
publish_guide.py - 把 guide.html 上传到 Hermes dashboards plugin，拿公网 URL

复用 dashboards skill 的上传契约（scripts/config.py：DASHBOARDS_PLUGIN_URL / API_SERVER_KEY / DASHBOARDS_PAGE_BASE）。

用法: publish_guide.py output/<slug>/guide.html --title "川西 · 国庆自驾" [--description "…"]
环境: set -a; source ~/.hermes/.env; set +a   （API_SERVER_KEY / DASHBOARDS_PLUGIN_URL / DASHBOARDS_PAGE_BASE）
      用 ~/.hermes/hermes-agent/venv/bin/python 跑（需要 requests）；每次上传都是新 id，发布记录写在 published.json；--update <id> 原地覆盖保持链接不变
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
DASH_SCRIPTS = HERE.parent.parent / "dashboards" / "scripts"
sys.path.insert(0, str(DASH_SCRIPTS))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("html")
    ap.add_argument("--title", required=True)
    ap.add_argument("--description", default="旅行手册（trip-guide）")
    ap.add_argument("--update", metavar="DASH_ID", help="原地覆盖已发布的报告（plugin 与本机同一台时直接写 ~/dashboards/<id>/index.html，链接不变）")
    args = ap.parse_args()

    if args.update:
        import os, shutil
        ddir = Path(os.environ.get("DASHBOARDS_DIR", "~/dashboards")).expanduser() / args.update
        target = ddir / "index.html"
        if not target.exists():
            sys.exit(f"❌ {target} 不存在：id 不对，或 plugin 不在本机（改用普通上传）")
        shutil.copy(args.html, target)
        rec = Path(args.html).with_name("published.json")
        old = json.loads(rec.read_text()) if rec.exists() else {}
        print(f"✓ 已原地更新 {target}")
        if old.get("url"):
            print(f"  链接不变: {old['url']}")
        return

    try:
        from config import PAGE_BASE, PLUGIN_URL, upload_headers  # noqa: E402
        import requests  # noqa: E402
    except ImportError as e:
        sys.exit(f"❌ 需要 dashboards skill 的 config.py 与 requests：{e}\n   试试 ~/.hermes/hermes-agent/venv/bin/python 运行")

    html = Path(args.html).read_text()
    session = requests.Session()
    session.trust_env = False  # 本地 / WireGuard 服务不走系统代理
    resp = session.post(f"{PLUGIN_URL}/upload", json={"html": html, "meta": {
        "title": args.title, "description": args.description, "data_source": "trip-guide", "kind": "trip-guide",
    }}, headers=upload_headers(), timeout=60)
    if resp.status_code >= 300:
        sys.exit(f"❌ 上传失败 {resp.status_code}: {resp.text[:300]}")
    data = resp.json()
    dash_id = data.get("id") or data.get("dash_id") or ""
    url = data.get("public_url") or data.get("url") or ""
    if (not url or url.startswith("/")) and dash_id:
        url = f"{PAGE_BASE.rstrip('/')}/{dash_id}"  # 返回的是相对路径时，用 DASHBOARDS_PAGE_BASE 拼成公网地址
    print(f"✓ 已发布: {url or data}")
    if dash_id:
        rec = Path(args.html).with_name("published.json")
        rec.write_text(json.dumps({"id": dash_id, "url": url, "title": args.title}, ensure_ascii=False, indent=2))
        print(f"  记录: {rec}")


if __name__ == "__main__":
    main()
