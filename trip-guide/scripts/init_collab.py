#!/usr/bin/env python3
"""
init_collab.py - 同行协作的 Notion 侧：建库、管名单、种个人物品清单

数据模型（唯一数据源就是这张 Notion database，页面通过 trip-collab 代理读写它）：

    database「<行程标题> · 同行准备」
      行  = 一个同行者
      属性 姓名(title) / 已加入(checkbox) / 饮食忌口 / 住宿偏好(select) / 住宿备注 / 紧急联系人
      正文 = 这个人的物品 to_do 清单（每条 to_do 的灰色斜体尾巴是「为什么带」）

「已加入」控制谁出现在分享页的认领下拉里 —— 这就是御主要的「admin 选择哪些人加入旅程」。

用法:
  init_collab.py init   output/<slug>/guide.json --parent-page <page_id> --members "老王,小李,阿珍"
  init_collab.py list   output/<slug>/guide.json
  init_collab.py add    output/<slug>/guide.json "阿强" [--no-seed]
  init_collab.py join   output/<slug>/guide.json "阿强"      # 放进下拉
  init_collab.py leave  output/<slug>/guide.json "阿强"      # 从下拉拿掉（数据保留）
  init_collab.py seed   output/<slug>/guide.json [--all | "老王"] [--replace]

环境: source ~/.hermes/trip-env.sh   （NOTION_TOKEN）
记录: output/<slug>/collab.json —— database_id 与成员 id，被 build_guide.py 和 deploy 读取
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

NOTION_API = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"

PROPS = {
    "姓名": {"title": {}},
    "已加入": {"checkbox": {}},
    "饮食忌口": {"rich_text": {}},
    "住宿偏好": {"select": {"options": [
        {"name": "单人间", "color": "blue"},
        {"name": "可拼房", "color": "green"},
        {"name": "无所谓", "color": "gray"},
    ]}},
    "住宿备注": {"rich_text": {}},
    "紧急联系人": {"rich_text": {}},
}


def notion(method: str, path: str, data: dict | None = None) -> dict:
    tok = os.environ.get("NOTION_TOKEN")
    if not tok:
        sys.exit("❌ NOTION_TOKEN 未设置（source ~/.hermes/trip-env.sh）")
    req = urllib.request.Request(
        f"{NOTION_API}{path}",
        method=method,
        data=json.dumps(data).encode() if data is not None else None,
        headers={"Authorization": f"Bearer {tok}", "Notion-Version": NOTION_VERSION,
                 "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode()[:400]
        sys.exit(f"❌ Notion {method} {path} → {e.code}: {body}")


def todo_block(text: str, why: str = "", checked: bool = False) -> dict:
    rich = [{"type": "text", "text": {"content": text}}]
    if why:
        rich.append({"type": "text", "text": {"content": f"  · {why}"},
                     "annotations": {"italic": True, "color": "gray"}})
    return {"object": "block", "type": "to_do", "to_do": {"rich_text": rich, "checked": checked}}


def rec_path(guide: Path) -> Path:
    return guide.with_name("collab.json")


def load_rec(guide: Path) -> dict:
    p = rec_path(guide)
    if not p.exists():
        sys.exit(f"❌ 还没初始化：{p} 不存在，先跑 init")
    return json.loads(p.read_text())


def save_rec(guide: Path, rec: dict) -> None:
    rec_path(guide).write_text(json.dumps(rec, ensure_ascii=False, indent=2))


def seed_items(guide_data: dict) -> list[dict]:
    """通用物品清单种子 = guide.json 的 prep.essentials。"""
    return [{"text": it.get("text", ""), "why": it.get("why", "")}
            for it in (guide_data.get("prep") or {}).get("essentials", []) if it.get("text")]


def create_member(db_id: str, name: str, items: list[dict]) -> str:
    page = notion("POST", "/pages", {
        "parent": {"database_id": db_id},
        "properties": {"姓名": {"title": [{"type": "text", "text": {"content": name}}]},
                       "已加入": {"checkbox": True}},
        "children": [todo_block(i["text"], i.get("why", "")) for i in items[:100]],
    })
    return page["id"]


def query_rows(db_id: str) -> list[dict]:
    rows, cursor = [], None
    while True:
        body = {"page_size": 100}
        if cursor:
            body["start_cursor"] = cursor
        d = notion("POST", f"/databases/{db_id}/query", body)
        rows += d.get("results", [])
        if not d.get("has_more"):
            return rows
        cursor = d.get("next_cursor")


def row_name(row: dict) -> str:
    t = row.get("properties", {}).get("姓名", {}).get("title", [])
    return "".join(x.get("plain_text", "") for x in t)


def find_row(db_id: str, name: str) -> dict:
    for r in query_rows(db_id):
        if row_name(r) == name:
            return r
    sys.exit(f"❌ 名单里没有「{name}」")


def cmd_init(args, guide: Path, g: dict):
    if rec_path(guide).exists() and not args.force:
        sys.exit(f"❌ {rec_path(guide)} 已存在（--force 重建一张新表）")
    title = g.get("meta", {}).get("title", guide.parent.name)
    db = notion("POST", "/databases", {
        "parent": {"type": "page_id", "page_id": args.parent_page},
        "title": [{"type": "text", "text": {"content": f"{title} · 同行准备"}}],
        "properties": PROPS,
    })
    db_id = db["id"]
    items = seed_items(g)
    members = []
    for name in [n.strip() for n in args.members.split(",") if n.strip()]:
        members.append({"name": name, "id": create_member(db_id, name, items)})
        print(f"  + {name}")
    save_rec(guide, {"database_id": db_id, "database_url": db.get("url", ""),
                     "parent_page": args.parent_page, "members": members})
    print(f"✓ 已建表 {db.get('url', db_id)}")
    print(f"  {len(members)} 人 · 每人种了 {len(items)} 条物品")
    print(f"  记录: {rec_path(guide)}")


def cmd_list(args, guide: Path, g: dict):
    rec = load_rec(guide)
    for r in query_rows(rec["database_id"]):
        p = r["properties"]
        joined = "✓" if p.get("已加入", {}).get("checkbox") else "·"
        diet = "".join(x.get("plain_text", "") for x in p.get("饮食忌口", {}).get("rich_text", []))
        room = (p.get("住宿偏好", {}).get("select") or {}).get("name", "")
        print(f" {joined} {row_name(r):8} {room:6} {diet}")
    print(f"\n✓ 勾选的 {len([1 for r in query_rows(rec['database_id']) if r['properties'].get('已加入',{}).get('checkbox')])} 人会出现在分享页的认领下拉里")


def cmd_add(args, guide: Path, g: dict):
    rec = load_rec(guide)
    items = [] if args.no_seed else seed_items(g)
    mid = create_member(rec["database_id"], args.name, items)
    rec.setdefault("members", []).append({"name": args.name, "id": mid})
    save_rec(guide, rec)
    print(f"✓ 已加入 {args.name}（{len(items)} 条物品）")


def cmd_joinleave(args, guide: Path, g: dict, value: bool):
    rec = load_rec(guide)
    row = find_row(rec["database_id"], args.name)
    notion("PATCH", f"/pages/{row['id']}", {"properties": {"已加入": {"checkbox": value}}})
    print(f"✓ {args.name} {'已放进' if value else '已移出'}认领下拉")


def cmd_seed(args, guide: Path, g: dict):
    rec = load_rec(guide)
    items = seed_items(g)
    if not items:
        sys.exit("❌ guide.json 的 prep.essentials 是空的，没东西可种")
    targets = query_rows(rec["database_id"]) if args.all else [find_row(rec["database_id"], args.name)]
    for row in targets:
        existing = notion("GET", f"/blocks/{row['id']}/children?page_size=100").get("results", [])
        todos = [b for b in existing if b["type"] == "to_do"]
        if args.replace:
            for b in todos:
                notion("DELETE", f"/blocks/{b['id']}")
            have = set()
        else:
            have = {"".join(x.get("plain_text", "") for x in b["to_do"]["rich_text"]).split("  · ")[0]
                    for b in todos}
        new = [i for i in items if i["text"] not in have]
        if new:
            notion("PATCH", f"/blocks/{row['id']}/children",
                   {"children": [todo_block(i["text"], i.get("why", "")) for i in new]})
        print(f"  {row_name(row):8} +{len(new)} 条" + (" (清空重种)" if args.replace else ""))
    print("✓ 完成")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("init", help="建表 + 建成员")
    p.add_argument("guide"); p.add_argument("--parent-page", required=True)
    p.add_argument("--members", required=True, help="逗号分隔的姓名")
    p.add_argument("--force", action="store_true")

    p = sub.add_parser("list", help="看名单"); p.add_argument("guide")
    p = sub.add_parser("add", help="加人"); p.add_argument("guide"); p.add_argument("name")
    p.add_argument("--no-seed", action="store_true", help="不种通用物品清单")
    p = sub.add_parser("join", help="放进认领下拉"); p.add_argument("guide"); p.add_argument("name")
    p = sub.add_parser("leave", help="移出认领下拉"); p.add_argument("guide"); p.add_argument("name")
    p = sub.add_parser("seed", help="按 guide.json 的 prep.essentials 补种物品")
    p.add_argument("guide"); p.add_argument("name", nargs="?")
    p.add_argument("--all", action="store_true"); p.add_argument("--replace", action="store_true")

    args = ap.parse_args()
    guide = Path(args.guide)
    g = json.loads(guide.read_text())
    if args.cmd in ("seed",) and not args.all and not args.name:
        sys.exit("❌ seed 要么给名字，要么 --all")
    {"init": cmd_init, "list": cmd_list, "add": cmd_add, "seed": cmd_seed,
     "join": lambda a, gu, gd: cmd_joinleave(a, gu, gd, True),
     "leave": lambda a, gu, gd: cmd_joinleave(a, gu, gd, False)}[args.cmd](args, guide, g)


if __name__ == "__main__":
    main()
