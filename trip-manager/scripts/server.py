#!/usr/bin/env python3
"""
travel-guide server.py - 交互式地图本地服务器

职责:
  * 静态服务 travel-guide/ 目录 (index.html, data.json)
  * GET /api/poi?lng=..&lat=..&radius=..&types=..   → 高德周边搜索代理 (Web 服务 API)

用法:
  python3 server.py [--port 8899] [--dir travel-guide]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.parse
import urllib.request
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
# 页面与数据位于 skill 根目录 travel-guide/（scripts/travel-guide/ 仅为 build_data.py 的中间产物）
DEFAULT_DIR = HERE.parent / "travel-guide"
AMAP_PLACE_AROUND = "https://restapi.amap.com/v3/place/around"


def get_amap_key() -> str:
    key = os.environ.get("AMAP_API_KEY", "")
    if key:
        return key
    # 兜底: 从 trip-env.sh 读取
    env_file = Path.home() / ".hermes" / "trip-env.sh"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            if line.startswith("export AMAP_API_KEY="):
                key = line.split("=", 1)[1].strip().strip('"').strip("'")
                break
    return key


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, directory=None, **kwargs):
        self._amap_key = get_amap_key()
        super().__init__(*args, directory=str(DEFAULT_DIR), **kwargs)

    def log_message(self, fmt, *args):
        sys.stderr.write("[%s] %s\n" % (self.log_date_time_string(), fmt % args))

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/api/poi":
            self.handle_poi(parsed)
            return
        super().do_GET()

    def handle_poi(self, parsed):
        qs = urllib.parse.parse_qs(parsed.query)
        try:
            lng = float(qs.get("lng", [""])[0])
            lat = float(qs.get("lat", [""])[0])
        except ValueError:
            self.send_json({"error": "bad lng/lat"}, 400)
            return
        radius = qs.get("radius", ["3000"])[0]
        types = qs.get("types", ["风景名胜|餐饮服务"])[0]
        keyword = qs.get("keyword", [""])[0]

        if not self._amap_key:
            self.send_json({"error": "AMAP_API_KEY 未配置"}, 500)
            return

        params = {
            "location": f"{lng},{lat}",
            "key": self._amap_key,
            "radius": radius,
            "types": types,
            "offset": "10",
            "page": "1",
            "extensions": "base",
        }
        if keyword:
            params["keywords"] = keyword
        url = AMAP_PLACE_AROUND + "?" + urllib.parse.urlencode(params)
        try:
            with urllib.request.urlopen(url, timeout=12) as resp:
                data = json.loads(resp.read())
        except Exception as e:
            self.send_json({"error": f"amap request failed: {e}"}, 502)
            return

        if data.get("status") != "1":
            self.send_json({"error": data.get("info", "amap error")}, 502)
            return

        pois = []
        for p in data.get("pois", []):
            pois.append({
                "name": p.get("name", ""),
                "address": p.get("address", ""),
                "distance": p.get("distance", ""),
                "type": p.get("type", ""),
            })
        self.send_json({"pois": pois})

    def send_json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8899)
    ap.add_argument("--dir", default=str(DEFAULT_DIR))
    args = ap.parse_args()

    if not (Path(args.dir) / "index.html").exists():
        print(f"❌ {args.dir}/index.html 不存在", file=sys.stderr)
        sys.exit(1)

    server = ThreadingHTTPServer(("0.0.0.0", args.port), Handler)
    print(f"✅ 行程地图服务已启动:  http://localhost:{args.port}/")
    print(f"   静态目录: {args.dir}")
    key = get_amap_key()
    print(f"   AMAP_API_KEY: {'✓ 已配置' if key else '✗ 未配置 (周边 POI 不可用)'}")
    print("   Ctrl+C 停止")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n⏹ 已停止")


if __name__ == "__main__":
    main()
