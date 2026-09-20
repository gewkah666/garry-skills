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


def inline_images(obj, base: Path) -> int:
    """image / cover 字段若是 guide.json 旁的相对路径，读文件转成 data URI，保持单文件离线可看。"""
    import base64, mimetypes
    n = 0
    if isinstance(obj, dict):
        for k, v in list(obj.items()):
            if k in ("image", "cover") and isinstance(v, str) and v and not v.startswith(("http://", "https://", "data:")):
                p = base / v
                if p.exists():
                    mime = mimetypes.guess_type(p.name)[0] or "image/jpeg"
                    obj[k] = f"data:{mime};base64,{base64.b64encode(p.read_bytes()).decode()}"
                    n += 1
                else:
                    print(f"⚠️ 图片不存在: {v}")
            else:
                n += inline_images(v, base)
    elif isinstance(obj, list):
        for x in obj:
            n += inline_images(x, base)
    return n


def collab_cfg(src: Path) -> dict | None:
    """同行协作的接线（output/<slug>/collab.json 存在才有）。

    只注入 api 前缀和 notion-relay 的资源名，不注入任何 token —— 页面从自己 URL 上的
    ?t= 取，所以同一份 HTML 两处通用：分享副本带 token → 协作激活；dashboards 那份
    没有 token → collabOn() 为假，退回本机勾选。既不用 CORS，也不用构建两次。
    """
    if not src.with_name("collab.json").exists():
        return None
    pub = src.with_name("published.json")
    slug = ""
    if pub.exists():
        slug = (json.loads(pub.read_text()).get("share") or {}).get("slug") or ""
    return {"api": "/s/api", "resource": slug or src.parent.name}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("guide")
    ap.add_argument("-o", "--out")
    ap.add_argument("--open", action="store_true")
    ap.add_argument("--serve-copy", action="store_true")
    ap.add_argument("--no-collab", action="store_true", help="即使有 collab.json 也不接同行协作")
    args = ap.parse_args()

    src = Path(args.guide)
    guide = json.loads(src.read_text())
    guide.setdefault("meta", {})["built_at"] = datetime.now().strftime("%Y-%m-%d %H:%M")
    if not args.no_collab:
        cc = collab_cfg(src)
        if cc:
            guide["collab"] = cc
            print(f"  同行协作: {cc['api']}/n/{cc['resource']}（分享链接带 ?t= 时激活）")
    n = inline_images(guide, src.parent)
    if n:
        print(f"  内嵌图片 {n} 张（guide.json 里的相对路径 → data URI）")
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
