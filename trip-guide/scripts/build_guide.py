#!/usr/bin/env python3
"""
build_guide.py - guide.json + assets/template.html → 单文件 guide.html（数据内嵌，离线可看）

用法:
  build_guide.py output/<slug>/guide.json [-o guide.html] [--open] [--serve-copy]
    --open        用系统浏览器打开
    --serve-copy  复制到 trip-manager/travel-guide/guide.html（server.py 起来后手机在局域网访问 /guide.html）
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
TEMPLATE = HERE.parent / "assets" / "template.html"
SERVE_DIR = HERE.parent.parent / "trip-manager" / "travel-guide"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("guide")
    ap.add_argument("-o", "--out")
    ap.add_argument("--open", action="store_true")
    ap.add_argument("--serve-copy", action="store_true")
    args = ap.parse_args()

    src = Path(args.guide)
    guide = json.loads(src.read_text())
    guide.setdefault("meta", {})["built_at"] = datetime.now().strftime("%Y-%m-%d %H:%M")
    payload = json.dumps(guide, ensure_ascii=False).replace("</", "<\\/")
    html = TEMPLATE.read_text()
    if "/*__GUIDE_JSON__*/" not in html:
        sys.exit("❌ template.html 缺少 /*__GUIDE_JSON__*/ 占位")
    html = html.replace("/*__GUIDE_JSON__*/null", payload, 1)
    title = guide["meta"].get("title", "行程")
    html = html.replace("<title>行程手册</title>", f"<title>{title}</title>", 1)

    out = Path(args.out) if args.out else src.with_name("guide.html")
    out.write_text(html)
    print(f"✓ {out}  ({out.stat().st_size // 1024} KB)")

    if args.serve_copy:
        SERVE_DIR.mkdir(exist_ok=True)
        shutil.copy(out, SERVE_DIR / "guide.html")
        print(f"  → {SERVE_DIR / 'guide.html'}（python3 trip-manager/scripts/server.py 后访问 /guide.html）")
    if args.open:
        subprocess.run(["open", str(out)], check=False)


if __name__ == "__main__":
    main()
