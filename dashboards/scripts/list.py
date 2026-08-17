"""List all dashboards.

通过 plugin API 列出所有已生成的报表。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from config import PLUGIN_URL, upload_headers


def main() -> None:
    parser = argparse.ArgumentParser(description="List dashboards.")
    parser.add_argument("--limit", type=int, default=50, help="Max results")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    import requests

    try:
        resp = requests.get(
            f"{PLUGIN_URL}/list",
            params={"limit": args.limit},
            headers=upload_headers(),
            timeout=10,
        )
        resp.raise_for_status()
        items = resp.json()
    except requests.RequestException as e:
        # fallback: 列本地目录
        local = Path.home() / "dashboards"
        if not local.exists():
            print(f"Plugin unreachable ({e}) and no local directory.", file=sys.stderr)
            sys.exit(1)
        items = []
        for d in sorted(local.iterdir(), reverse=True):
            if d.is_dir() and (d / "index.html").exists():
                meta = {}
                mfile = d / "meta.json"
                if mfile.exists():
                    meta = json.loads(mfile.read_text(encoding="utf-8"))
                items.append({
                    "id": d.name,
                    "title": meta.get("title", d.name),
                    "public_url": f"/api/plugins/dashboards/page/{d.name}",
                    "created_at": meta.get("created_at", ""),
                    "source": "local-fallback",
                })

    if args.json:
        print(json.dumps(items, ensure_ascii=False, indent=2))
    else:
        for it in items:
            url = it.get("public_url", "")
            title = it.get("title", "")
            ts = it.get("created_at", "")
            print(f"  {ts}  {title}\n    {url}")


if __name__ == "__main__":
    main()
