"""Ingest data into Notion database.

Usage:
    python3 scripts/ingest.py --notion-db <id> --file data.csv
    python3 scripts/ingest.py --notion-db <id> --file data.json

CSV/JSON 数据按 Notion schema 自动转换并写入。

注意：
  - 在 Hermes 会话内运行时，Notion 写入应通过 Notion MCP（mcp__notion__API_post_page）。
    本脚本仅在独立运行时使用（需要 NOTION_API_KEY 环境变量）。
  - v0.1 只支持简单字段类型（title、number、date、select、multi_select、rich_text）。
  - 数据格式约定：每行一个记录，列名（或 JSON 顶层 key）映射到 Notion 属性名。
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from pathlib import Path
from typing import Any


NOTION_API_BASE = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"


def load_csv(path: Path) -> list[dict[str, Any]]:
    with open(path, "r", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def load_json(path: Path) -> list[dict[str, Any]]:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        raise ValueError("JSON must be an array of objects")
    return data


def infer_value(field_name: str, value: Any) -> dict[str, Any]:
    """根据值类型推断 Notion 属性格式."""
    if value is None or value == "":
        return {}
    s = str(value).strip()

    # 日期
    if _looks_like_date(s):
        return {field_name: {"date": {"start": s}}}

    # 数字
    try:
        float(s.replace(",", ""))
        return {field_name: {"number": float(s.replace(",", ""))}}
    except ValueError:
        pass

    # 布尔
    if s.lower() in ("true", "false", "yes", "no"):
        return {field_name: {"checkbox": s.lower() in ("true", "yes")}}

    # 多选（用 | 或 , 分隔）
    if "|" in s or ("," in s and len(s.split(",")) > 1):
        sep = "|" if "|" in s else ","
        opts = [x.strip() for x in s.split(sep) if x.strip()]
        return {field_name: {"multi_select": [{"name": x} for x in opts]}}

    # 单选 vs 富文本：第一个属性且没数字特征 → 当 title，否则 select，再否则 rich_text
    # 这里简化：含"名字"/"name"/"title"/"标题" → title
    lname = field_name.lower()
    if any(kw in lname for kw in ["名字", "name", "title", "标题"]):
        return {field_name: {"title": [{"text": {"content": s}}]}}

    # 默认当 select
    return {field_name: {"select": {"name": s}}}


def _looks_like_date(s: str) -> bool:
    import re
    return bool(re.match(r"^\d{4}-\d{2}-\d{2}", s))


def insert_via_api(notion_db: str, record: dict[str, Any], api_key: str) -> dict[str, Any]:
    """直接调 Notion REST API（独立运行时 fallback）."""
    import requests

    properties: dict[str, Any] = {}
    for k, v in record.items():
        properties.update(infer_value(k, v))

    resp = requests.post(
        f"{NOTION_API_BASE}/pages",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Notion-Version": NOTION_VERSION,
            "Content-Type": "application/json",
        },
        json={
            "parent": {"database_id": notion_db},
            "properties": properties,
        },
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest data into Notion.")
    parser.add_argument("--notion-db", required=True, help="Notion database ID")
    parser.add_argument("--file", required=True, help="CSV or JSON file path")
    parser.add_argument("--dry-run", action="store_true", help="Print mapped properties only")
    args = parser.parse_args()

    path = Path(args.file)
    if not path.exists():
        print(f"ERROR: file not found: {path}", file=sys.stderr)
        sys.exit(1)

    if path.suffix.lower() == ".csv":
        records = load_csv(path)
    elif path.suffix.lower() == ".json":
        records = load_json(path)
    else:
        print(f"ERROR: unsupported file type: {path.suffix} (use .csv or .json)",
              file=sys.stderr)
        sys.exit(1)

    print(f"Loaded {len(records)} records from {path}", file=sys.stderr)

    if args.dry_run:
        # 只展示第一行的映射结果
        if records:
            mapped = {}
            for k, v in records[0].items():
                mapped.update(infer_value(k, v))
            print(json.dumps(mapped, ensure_ascii=False, indent=2))
        return

    api_key = os.environ.get("NOTION_API_KEY", "")
    if not api_key:
        print("ERROR: NOTION_API_KEY not set. In Hermes session, use Notion MCP instead.",
              file=sys.stderr)
        sys.exit(1)

    success = 0
    failed = 0
    for i, r in enumerate(records, 1):
        try:
            insert_via_api(args.notion_db, r, api_key)
            success += 1
        except Exception as e:
            print(f"[{i}/{len(records)}] failed: {e}", file=sys.stderr)
            failed += 1

    print(f"\nDone: {success} success, {failed} failed", file=sys.stderr)


if __name__ == "__main__":
    main()
