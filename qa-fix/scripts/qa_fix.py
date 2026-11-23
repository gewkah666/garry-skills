#!/usr/bin/env python3
"""Needs Fix 任务的 Test log 修复工具：读 QA 项、写修复记录、转 Testing。

  list     列出 Needs Fix 任务和每条 QA 项的状态（--project 按项目名过滤，--page 只看一页）
  show     打印一页的 Goal、Docs、Work log 和 Test log 各项；截图下载到 --out 目录
  start    Work log 记一行「修复开始」，作为认领
  record   在某条 QA 项末尾插入一个「修复」记录块（已修复 / 不修改 / 未复现）
  log      Work log 记一行，按页面现有顺序插入（新的在上或新的在下）
  testing  所有 QA 项的最后一块都是修复记录时，Status → Testing，Work log 记「转 Testing」
  watch    后台轮询；出现状态文件里没有的待修 QA 项（新的 open，或 QA 复验后 reopened）
           就打印它们并退出。状态文件不存在时，先把当前的待修项记为基线，不报

QA 项的状态：open（没有修复记录）、fixed（修复记录是这一项的最后一块）、
reopened（修复记录之后 QA 又写了内容，读 after_fix）。

token 来自 $NOTION_TOKEN 或 ~/.hermes/notion-relay.json，不打印。
"""
import argparse
import http.client
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime

API = "https://api.notion.com/v1"
VERSION = "2025-09-03"
TASKS_DS = "3f2616ff-95e7-837b-8444-074b10e56064"
NEEDS_FIX = "Needs Fix"
TESTING = "Testing"
FIX_TAG = "修复"
START_TAG = "修复开始"
TESTING_TAG = "转 Testing"
TRANSIENT = (429, 500, 502, 503, 504)
RESULTS = {
    "已修复": ("🛠️", "green_background", ("根因", "改动", "回归", "复验")),
    "不修改": ("📌", "gray_background", ("原因", "结论", "证据", "复验")),
    "未复现": ("🔍", "gray_background", ("原因", "结论", "证据", "复验")),
}


def token():
    t = os.environ.get("NOTION_TOKEN")
    if t:
        return t
    with open(os.path.expanduser("~/.hermes/notion-relay.json")) as f:
        return json.load(f)["notion_token"]


def call(method, path, body=None):
    req = urllib.request.Request(
        API + path,
        method=method,
        data=None if body is None else json.dumps(body).encode(),
        headers={
            "Authorization": "Bearer " + token(),
            "Notion-Version": VERSION,
            "Content-Type": "application/json",
        },
    )
    for attempt in range(5):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code in TRANSIENT and attempt < 4:
                time.sleep(int(e.headers.get("Retry-After") or 2 ** attempt))
                continue
            sys.exit(f"Notion {method} {path} -> {e.code}: {e.read().decode()[:300]}")
        except (OSError, http.client.HTTPException) as e:
            if attempt < 4:
                time.sleep(2 ** attempt)
                continue
            sys.exit(f"Notion {method} {path} unreachable: {getattr(e, 'reason', e)}")


def page_id(ref):
    m = re.search(r"([0-9a-f]{32})(?:[?#]|$)", ref.replace("-", ""))
    if not m:
        sys.exit(f"not a Notion page id or url: {ref}")
    h = m.group(1)
    return f"{h[:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:]}"


def children(block_id):
    out, cursor = [], None
    while True:
        q = f"/blocks/{block_id}/children?page_size=100" + (f"&start_cursor={cursor}" if cursor else "")
        r = call("GET", q)
        out += r["results"]
        if not r.get("has_more"):
            return out
        cursor = r["next_cursor"]


def plain(block):
    return "".join(t["plain_text"] for t in block.get(block["type"], {}).get("rich_text", []))


def linked(block):
    """Plain text with each link's target after its text, so 复验入口 keeps its address."""
    out = []
    for t in block.get(block["type"], {}).get("rich_text", []):
        out.append(t["plain_text"])
        if t.get("href") and t["href"] != t["plain_text"]:
            out.append(f" <{t['href']}>")
    return "".join(out)


def all_bold(block):
    rt = block.get(block["type"], {}).get("rich_text", [])
    return bool(rt) and all(t["annotations"]["bold"] for t in rt if t["plain_text"].strip())


def now():
    return datetime.now().astimezone().strftime("%Y-%m-%d %H:%M %z")


def text(s, bold=False):
    return {"type": "text", "text": {"content": s}, "annotations": {"bold": bold}}


def bullet(s):
    return {"type": "bulleted_list_item", "bulleted_list_item": {"rich_text": [text(s)]}}


def is_section_heading(b):
    return b["type"] in ("heading_1", "heading_2")


def section(blocks, names):
    """(heading block, body blocks) of the first heading_2 whose text is one of names."""
    for i, b in enumerate(blocks):
        if is_section_heading(b) and plain(b).strip().lower() in names:
            body = []
            for c in blocks[i + 1:]:
                if is_section_heading(c):
                    break
                body.append(c)
            return b, body
    return None, []


def is_record(b):
    if b["type"] != "callout":
        return False
    rt = b["callout"]["rich_text"]
    return bool(rt) and rt[0]["plain_text"].strip() == FIX_TAG and rt[0]["annotations"]["bold"]


def block_lines(b):
    t = linked(b).strip()
    if b["type"] == "numbered_list_item":
        return [f"# {t}"]
    if b["type"] in ("bulleted_list_item", "to_do"):
        return [f"- {t}"]
    return [t] if t else []


def record_text(b):
    lines = [plain(b).strip()]
    if b.get("has_children"):
        lines += ["  " + plain(c).strip() for c in children(b["id"]) if plain(c).strip()]
    return lines


def qa_items(blocks):
    _, body = section(blocks, {"test log", "测试日志"})
    items, cur = [], None
    for b in body:
        if b["type"] == "heading_3":
            title = plain(b).strip()
            m = re.match(r"(QA-[\w.-]+)\s*(.*)", title)
            cur = {"id": m.group(1) if m else title, "title": m.group(2) if m else title,
                   "heading": b, "blocks": []}
            items.append(cur)
        elif cur:
            cur["blocks"].append(b)
    for it in items:
        recs = [i for i, b in enumerate(it["blocks"]) if is_record(b)]
        if not recs:
            it["state"] = "open"
        elif recs[-1] == len(it["blocks"]) - 1:
            it["state"] = "fixed"
        else:
            it["state"] = "reopened"
        it["last_record"] = recs[-1] if recs else None
        it["records"] = len(recs)
        fields = {}
        first = next((b for b in it["blocks"] if b["type"] == "paragraph"), None)
        if first:
            for line in linked(first).split("\n"):
                k, _, v = line.strip().partition(" ")
                if k and v:
                    fields[k] = v.strip()
        it["fields"] = fields
    return items


def item_summary(it):
    return {"id": it["id"], "title": it["title"], "state": it["state"], "records": it["records"],
            "priority": it["fields"].get("优先级"), "slice": it["fields"].get("切片")}


TS = re.compile(r"(?:(\d{4})-)?(\d{1,2})-(\d{1,2})[ T](\d{1,2}):(\d{2})")


def stamp(s):
    m = TS.search(s)
    return tuple(int(x) for x in m.groups()[1:]) if m else None


def worklog_insert_after(blocks):
    """Block id to insert a new Work log line after, matching the page's order."""
    head, body = section(blocks, {"work log"})
    if not head:
        sys.exit("no ## Work log heading on this page")
    stamped = [stamp(plain(b)) for b in body if b["type"] == "bulleted_list_item"]
    stamped = [s for s in stamped if s]
    if len(stamped) >= 2 and stamped[0] > stamped[-1]:
        return head["id"]  # newest first
    return (body[-1] if body else head)["id"]


def claim(blocks):
    _, body = section(blocks, {"work log"})
    starts, ends = [], []
    for b in body:
        rt = b.get(b["type"], {}).get("rich_text", [])
        lead = rt[0]["plain_text"].strip() if rt else ""
        s = stamp(plain(b))
        if lead == START_TAG and s:
            starts.append((s, plain(b)))
        elif lead == TESTING_TAG and s:
            ends.append(s)
    if not starts:
        return None
    last = max(starts)
    return last[1] if not ends or last[0] > max(ends) else None


def add_worklog(pid, label, line, blocks=None):
    blocks = blocks or children(pid)
    after = worklog_insert_after(blocks)
    call("PATCH", f"/blocks/{pid}/children", {"after": after, "children": [
        {"type": "bulleted_list_item", "bulleted_list_item": {"rich_text": [text(label, True), text(" " + line)]}}
    ]})


_titles = {}


def page_title(pid):
    if pid not in _titles:
        p = call("GET", f"/pages/{pid}")
        t = next((v for v in p["properties"].values() if v["type"] == "title"), None)
        _titles[pid] = "".join(x["plain_text"] for x in t["title"]) if t else pid
    return _titles[pid]


def task_row(p, blocks):
    props = p["properties"]
    return {
        "page_id": p["id"],
        "url": p["url"],
        "title": page_title(p["id"]),
        "status": props["Status"]["status"]["name"],
        "priority": (props.get("Priority", {}).get("select") or {}).get("name"),
        "project": [page_title(r["id"]) for r in props.get("Project", {}).get("relation", [])],
        "claimed": claim(blocks),
        "items": [item_summary(i) for i in qa_items(blocks)],
    }


def needs_fix_rows(project=None, page=None):
    if page:
        pages = [call("GET", f"/pages/{page_id(page)}")]
    else:
        pages, cursor = [], None
        while True:
            body = {"filter": {"property": "Status", "status": {"equals": NEEDS_FIX}}, "page_size": 100}
            if cursor:
                body["start_cursor"] = cursor
            r = call("POST", f"/data_sources/{TASKS_DS}/query", body)
            pages += r["results"]
            if not r.get("has_more"):
                break
            cursor = r["next_cursor"]
    rows = []
    for p in pages:
        _titles[p["id"]] = "".join(
            x["plain_text"] for x in p["properties"]["Task name"]["title"])
        if project:
            names = [page_title(r["id"]) for r in p["properties"]["Project"]["relation"]]
            if not any(project.lower() in n.lower() for n in names):
                continue
        rows.append(task_row(p, children(p["id"])))
    order = {"High": 0, "Medium": 1, "Low": 2}
    rows.sort(key=lambda r: order.get(r["priority"], 3))
    return rows


def cmd_list(a):
    print(json.dumps(needs_fix_rows(a.project, a.page), ensure_ascii=False, indent=2))


def cmd_watch(a):
    path = os.path.abspath(a.state)
    seen = set(json.load(open(path))) if os.path.exists(path) else None
    while True:
        try:
            cur = {}
            for r in needs_fix_rows(a.project):
                for it in r["items"]:
                    if it["state"] in ("open", "reopened"):
                        cur[f"{r['page_id']}|{it['id']}|{it['records']}|{it['state']}"] = (r, it)
            if seen is None:
                seen = set(cur)
                print(f"{now()} baseline {len(seen)} item(s) -> {path}", file=sys.stderr, flush=True)
            new = [k for k in cur if k not in seen]
            if new:
                seen |= set(new)
            with open(path, "w") as f:
                json.dump(sorted(seen), f)
            if new:
                print(json.dumps([{"task": cur[k][0]["title"], "url": cur[k][0]["url"],
                                   "qa": cur[k][1]["id"], "title": cur[k][1]["title"],
                                   "state": cur[k][1]["state"], "claimed": cur[k][0]["claimed"]}
                                  for k in new], ensure_ascii=False, indent=2), flush=True)
                return
        except SystemExit as e:  # call() gave up: network down or a Notion error; keep watching
            print(f"{now()} {e}", file=sys.stderr, flush=True)
        time.sleep(a.interval)


def download(url, path):
    with urllib.request.urlopen(url, timeout=120) as r, open(path, "wb") as f:
        f.write(r.read())


def cmd_show(a):
    pid = page_id(a.page)
    p = call("GET", f"/pages/{pid}")
    blocks = children(pid)
    out = os.path.abspath(a.out) if a.out else None
    if out:
        os.makedirs(out, exist_ok=True)
    row = task_row(p, blocks)
    for key, names in (("goal", {"goal"}), ("docs", {"docs"}), ("worklog", {"work log"})):
        row[key] = [ln for b in section(blocks, names)[1] for ln in block_lines(b)]
    detail = []
    for it in qa_items(blocks):
        parts, cur, n = [], {"label": "字段", "lines": [], "images": []}, 0
        parts.append(cur)
        for i, b in enumerate(it["blocks"]):
            if is_record(b):
                parts.append({"label": "修复记录", "lines": record_text(b), "images": []})
                cur = {"label": "修复记录之后", "lines": [], "images": []}
                parts.append(cur)
                continue
            if b["type"] == "image":
                n += 1
                img = b["image"]
                url = (img.get("file") or img.get("external") or {}).get("url")
                entry = {"caption": "".join(t["plain_text"] for t in img.get("caption", [])) or cur["label"]}
                if out and url:
                    ext = os.path.splitext(urllib.parse.urlparse(url).path)[1] or ".png"
                    path = os.path.join(out, f"{it['id']}-{n}{ext}")
                    download(url, path)
                    entry["file"] = path
                cur["images"].append(entry)
            elif b["type"] == "paragraph" and all_bold(b) and len(plain(b)) <= 30 and i > 0:
                cur = {"label": plain(b).strip(), "lines": [], "images": []}
                parts.append(cur)
            else:
                cur["lines"] += block_lines(b)
        after = []
        if it["state"] == "reopened":
            after = [ln for b in it["blocks"][it["last_record"] + 1:] for ln in block_lines(b)]
        detail.append({**item_summary(it), "fields": it["fields"], "heading_block": it["heading"]["id"],
                       "parts": [x for x in parts if x["lines"] or x["images"]], "after_fix": after})
    row["items"] = detail
    print(json.dumps(row, ensure_ascii=False, indent=2))


def cmd_start(a):
    pid = page_id(a.page)
    add_worklog(pid, START_TAG, f"{now()} — {a.text}")
    print(json.dumps({"ok": True}, ensure_ascii=False))


def cmd_record(a):
    pid = page_id(a.page)
    blocks = children(pid)
    items = [i for i in qa_items(blocks) if i["id"].lower() == a.qa.lower()]
    if len(items) != 1:
        have = [i["id"] for i in qa_items(blocks)]
        sys.exit(f"{a.qa}: {'not found' if not items else 'ambiguous'}; Test log has {have}")
    it = items[0]
    icon, color, labels = RESULTS[a.result]
    values = (a.cause, a.change, a.test, a.retest)
    anchor = (it["blocks"][-1] if it["blocks"] else it["heading"])["id"]
    call("PATCH", f"/blocks/{pid}/children", {"after": anchor, "children": [{
        "type": "callout",
        "callout": {
            "rich_text": [text(FIX_TAG, True), text(f" {now()} — {a.result}")],
            "icon": {"type": "emoji", "emoji": icon},
            "color": color,
            "children": [bullet(f"{k}：{v}") for k, v in zip(labels, values)],
        },
    }]})
    print(json.dumps({"ok": True, "qa": it["id"], "result": a.result}, ensure_ascii=False))


def cmd_log(a):
    pid = page_id(a.page)
    add_worklog(pid, a.label, f"{now()} — {a.text}")
    print(json.dumps({"ok": True}, ensure_ascii=False))


def cmd_testing(a):
    pid = page_id(a.page)
    p = call("GET", f"/pages/{pid}")
    st = p["properties"]["Status"]["status"]["name"]
    blocks = children(pid)
    items = qa_items(blocks)
    problems = []
    if st != NEEDS_FIX:
        problems.append(f"Status is {st!r}, not {NEEDS_FIX!r}")
    if not items:
        problems.append("no QA items under ## Test log")
    problems += [f"{i['id']} is {i['state']}" for i in items if i["state"] != "fixed"]
    if problems:
        print(json.dumps({"ok": False, "problems": problems}, ensure_ascii=False, indent=2))
        sys.exit(2)
    ids = "、".join(i["id"] for i in items)
    if a.dry_run:
        print(json.dumps({"ok": True, "dry_run": True, "items": ids}, ensure_ascii=False))
        return
    add_worklog(pid, TESTING_TAG, f"{now()} — {ids} 已处理，交 QA 复验。{a.text or ''}".rstrip(), blocks)
    call("PATCH", f"/pages/{pid}", {"properties": {"Status": {"status": {"name": TESTING}}}})
    print(json.dumps({"ok": True, "status": TESTING, "items": ids}, ensure_ascii=False))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("list")
    s.add_argument("--project")
    s.add_argument("--page")
    s.set_defaults(fn=cmd_list)
    s = sub.add_parser("watch")
    s.add_argument("--state", required=True, help="已报过的待修项记录（JSON）；删掉它会把当前所有待修项重新记为基线")
    s.add_argument("--interval", type=int, default=300)
    s.add_argument("--project")
    s.set_defaults(fn=cmd_watch)
    s = sub.add_parser("show")
    s.add_argument("page")
    s.add_argument("--out", help="截图下载目录（Notion 文件链接一小时后失效，用时现取）")
    s.set_defaults(fn=cmd_show)
    s = sub.add_parser("start")
    s.add_argument("page")
    s.add_argument("--text", required=True)
    s.set_defaults(fn=cmd_start)
    s = sub.add_parser("record")
    s.add_argument("page")
    s.add_argument("qa")
    s.add_argument("--result", choices=list(RESULTS), default="已修复")
    s.add_argument("--cause", required=True, help="已修复：根因；其他：原因")
    s.add_argument("--change", required=True, help="已修复：改动、PR 和合并提交；其他：结论")
    s.add_argument("--test", required=True, help="已修复：回归用例；其他：证据")
    s.add_argument("--retest", required=True, help="复验入口、步骤、环境需要的最低提交")
    s.set_defaults(fn=cmd_record)
    s = sub.add_parser("log")
    s.add_argument("page")
    s.add_argument("--label", required=True)
    s.add_argument("--text", required=True)
    s.set_defaults(fn=cmd_log)
    s = sub.add_parser("testing")
    s.add_argument("page")
    s.add_argument("--text")
    s.add_argument("--dry-run", action="store_true")
    s.set_defaults(fn=cmd_testing)
    a = ap.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
