#!/usr/bin/env python3
"""
publish_guide.py - 把 guide.html 发成一条「有链接就能看」的公网分享地址

只走 phantom-infra/share.sh 这一条路：VM 上 nginx 的 /s/<slug>/?t=<token>，微信 / Safari
直接打开，同行者不需要任何令牌以外的东西。

**为什么不再发 Hermes dashboards**：手册本来同时发到 dashboards 和分享链接两处，
两份拷贝各自更新，结果漂了（dashboards 那份一度停在四天前、不含同行协作代码）。
手册的受众是同行者，分享链接对你自己也一样能看，所以只留一处。
报表类产物该发 dashboards 的照旧走 dashboards skill，与本脚本无关。

用法:
  publish_guide.py output/<slug>/guide.html --title "川西 · 国庆自驾" [--share <slug>]
  publish_guide.py output/<slug>/guide.html --title … --revoke-share
记录: 发布结果写在同目录的 published.json 的 share 字段。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SHARE_SH = Path.home() / "Projects" / "phantom" / "phantom-infra" / "share.sh"


def share(args):
    """有链接就能看的副本：VM nginx /s/<slug>/?t=<token>，不经家里 gatekeeper。"""
    import subprocess
    html = Path(args.html)
    rec = html.with_name("published.json")
    old = json.loads(rec.read_text()) if rec.exists() else {}
    slug = args.share or old.get("share", {}).get("slug") or html.parent.name
    if not SHARE_SH.exists():
        sys.exit(f"❌ 找不到 {SHARE_SH}")
    if args.revoke_share:
        subprocess.run([str(SHARE_SH), "revoke", slug], check=True)
        old.pop("share", None)
        rec.write_text(json.dumps(old, ensure_ascii=False, indent=2))
        print(f"✓ 已撤销分享 {slug}")
        return
    mode = "update" if old.get("share", {}).get("slug") == slug else "add"
    out = subprocess.run([str(SHARE_SH), mode, slug, str(html)], check=True, capture_output=True, text=True).stdout
    url = next((l.strip() for l in out.splitlines() if l.startswith("http")), "")
    if not url:
        sys.exit(f"❌ share.sh 没有返回链接：{out}")
    old["share"] = {"slug": slug, "url": url}
    rec.write_text(json.dumps(old, ensure_ascii=False, indent=2))
    print(f"✓ 分享链接（{'链接不变' if mode == 'update' else '新链接'}）: {url}")
    print("  http 明文、令牌在 URL 里：只适合手册这类内容；撤销用 --revoke-share")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("html")
    ap.add_argument("--title", required=True)
    ap.add_argument("--share", nargs="?", const="", metavar="SLUG",
                    help="分享 slug，默认取 output/<slug>；已分享过则原地更新、链接不变")
    ap.add_argument("--revoke-share", action="store_true", help="撤销分享链接并删掉 VM 上的副本")
    args = ap.parse_args()
    share(args)


if __name__ == "__main__":
    main()
