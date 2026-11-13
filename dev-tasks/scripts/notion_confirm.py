#!/usr/bin/env python3
"""Ask the user to confirm something on a Notion task page, wait, and record the answer.

  ask      append a 待确认 block (背景, options, 意见) to the page end and set Status
           to "Pending for Confirm"
  wait     poll Status until it leaves "Pending for Confirm", then print the answer as JSON
  read     print the latest 待确认 block and the current Status as JSON, once
  resolve  append a 确认 line and restore the status the task had before ask

The token comes from $NOTION_TOKEN or ~/.hermes/notion-relay.json and is never printed.
"""
import argparse
import http.client
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime

API = "https://api.notion.com/v1"
VERSION = "2025-09-03"
PENDING = "Pending for Confirm"
ASK_TAG = "待确认"
DONE_TAG = "确认"
NOTE_TAG = "意见"
TRANSIENT = (429, 500, 502, 503, 504)


class Unreachable(Exception):
    """Notion did not answer after the retries: network down, TLS cut, or 429/5xx."""


def token():
    t = os.environ.get("NOTION_TOKEN")
    if t:
        return t
    with open(os.path.expanduser("~/.hermes/notion-relay.json")) as f:
        return json.load(f)["notion_token"]


def call(method, path, body=None, tolerate=()):
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
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code in tolerate:
                return None
            if e.code in TRANSIENT and attempt < 4:
                time.sleep(int(e.headers.get("Retry-After") or 2 ** attempt))
                continue
            if e.code in TRANSIENT:
                raise Unreachable(f"Notion {method} {path} -> {e.code}")
            sys.exit(f"Notion {method} {path} -> {e.code}: {e.read().decode()[:300]}")
        except (OSError, http.client.HTTPException) as e:  # DNS, refused, TLS EOF, timeout, reset
            if attempt < 4:
                time.sleep(2 ** attempt)
                continue
            raise Unreachable(f"Notion {method} {path} unreachable: {getattr(e, 'reason', e)}")


def page_id(ref):
    m = re.search(r"([0-9a-f]{32})(?:\?|$)", ref.replace("-", ""))
    if not m:
        sys.exit(f"not a Notion page id or url: {ref}")
    h = m.group(1)
    return f"{h[:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:]}"


def status(pid):
    return call("GET", f"/pages/{pid}")["properties"]["Status"]["status"]["name"]


def set_status(pid, name):
    call("PATCH", f"/pages/{pid}", {"properties": {"Status": {"status": {"name": name}}}})


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


def lead(block):
    rt = block.get(block["type"], {}).get("rich_text", [])
    return rt[0]["plain_text"].strip() if rt else ""


def subtree_text(block):
    if not block.get("has_children"):
        return []
    lines = []
    for c in children(block["id"]):
        if plain(c).strip():
            lines.append(plain(c).strip())
        lines += subtree_text(c)
    return lines


def comments(block_id):
    r = call("GET", f"/comments?block_id={block_id}&page_size=100", tolerate=(403, 404))
    if not r:
        return []
    return ["".join(t["plain_text"] for t in c["rich_text"]).strip() for c in r["results"]]


def now():
    return datetime.now().astimezone().strftime("%Y-%m-%d %H:%M")


def text(s, bold=False):
    return {"type": "text", "text": {"content": s}, "annotations": {"bold": bold}}


def bullet(*rich, kids=None):
    b = {"type": "bulleted_list_item", "bulleted_list_item": {"rich_text": list(rich)}}
    if kids:
        b["bulleted_list_item"]["children"] = kids
    return b


def todo(*rich):
    return {"type": "to_do", "to_do": {"rich_text": list(rich), "checked": False}}


def latest_ask(pid):
    asks = [b for b in children(pid) if b["type"] == "bulleted_list_item" and lead(b) == ASK_TAG]
    return asks[-1] if asks else None


def read(pid):
    st = status(pid)
    ask = latest_ask(pid)
    if not ask:
        return {"status": st, "ask": None}
    head = plain(ask)
    m = re.search(r"原状态 ([^）)]+)[）)]\s*$", head)
    question = re.sub(rf"^{ASK_TAG}\s*\S+ \S+ — ", "", head)
    question = re.sub(r"（原状态 [^）]+）\s*$", "", question)
    options, note = [], {"text": "", "checked": False, "block_id": None}
    for c in children(ask["id"]):
        if c["type"] != "to_do":
            continue
        rt = c["to_do"]["rich_text"]
        label = rt[0]["plain_text"].strip() if rt else ""
        rest = "".join(t["plain_text"] for t in rt[1:]).strip()
        if label.startswith(NOTE_TAG):
            body = [re.sub(rf"^{NOTE_TAG}[:：]?\s*", "", plain(c)).strip()] + subtree_text(c) + comments(c["id"])
            note = {"text": "\n".join(x for x in body if x), "checked": c["to_do"]["checked"], "block_id": c["id"]}
        else:
            options.append({"label": label, "text": rest, "checked": c["to_do"]["checked"], "block_id": c["id"]})
    page_notes = [x for x in comments(ask["id"]) if x]
    if page_notes:
        note["text"] = "\n".join(x for x in [note["text"]] + page_notes if x)
    return {
        "status": st,
        "ask": {
            "block_id": ask["id"],
            "question": question,
            "previous_status": m.group(1) if m else None,
            "options": options,
            "chosen": [o["label"] for o in options if o["checked"]],
            "comment": note["text"],
        },
    }


def cmd_ask(a):
    pid = page_id(a.page)
    prev = status(pid)
    if prev == PENDING:
        sys.exit("this task already has an open confirmation; resolve it first")
    kids = [bullet(text("背景：", True), text(a.background))]
    kids += [todo(text(label, True), text(" " + desc)) for label, desc in a.option]
    kids.append(todo(text(NOTE_TAG + "：", True)))
    r = call("PATCH", f"/blocks/{pid}/children", {"children": [
        bullet(text(ASK_TAG, True), text(f" {now()} — {a.question}（原状态 {prev}）"), kids=kids)
    ]})
    set_status(pid, PENDING)
    print(json.dumps({"block_id": r["results"][0]["id"], "previous_status": prev,
                      "options": [o[0] for o in a.option]}, ensure_ascii=False))


def cmd_wait(a):
    pid = page_id(a.page)
    deadline = time.time() + a.timeout_hours * 3600
    while True:
        try:
            if status(pid) != PENDING:
                print(json.dumps(read(pid), ensure_ascii=False, indent=2))
                return
        except Unreachable as e:
            # a network drop or the machine waking from sleep: keep polling until the deadline
            print(f"{now()} {e}; still waiting", file=sys.stderr, flush=True)
        if time.time() > deadline:
            print(json.dumps({"status": PENDING, "timeout": True}, ensure_ascii=False))
            sys.exit(3)
        time.sleep(a.interval)


def cmd_read(a):
    print(json.dumps(read(page_id(a.page)), ensure_ascii=False, indent=2))


def cmd_resolve(a):
    pid = page_id(a.page)
    info = read(pid)
    ask = info["ask"]
    if not ask:
        sys.exit("no 待确认 block on this page")
    for label in a.check or []:
        hit = [o for o in ask["options"] if o["label"] == label]
        hit = hit or [o for o in ask["options"] if o["label"].startswith(label)]
        if len(hit) != 1:
            sys.exit(f"no option labelled {label!r}; have {[o['label'] for o in ask['options']]}")
        call("PATCH", f"/blocks/{hit[0]['block_id']}", {"to_do": {"checked": True}})
    restore = a.status or ask["previous_status"]
    if not restore:
        sys.exit("previous status unknown; pass --status")
    call("PATCH", f"/blocks/{pid}/children", {"children": [
        bullet(text(DONE_TAG, True), text(f" {now()} — {a.summary}"))
    ]})
    set_status(pid, restore)
    print(json.dumps({"status": restore}, ensure_ascii=False))


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("ask")
    s.add_argument("page")
    s.add_argument("--question", required=True)
    s.add_argument("--background", required=True)
    s.add_argument("--option", nargs=2, action="append", required=True, metavar=("LABEL", "DESCRIPTION"))
    s.set_defaults(fn=cmd_ask)
    s = sub.add_parser("wait")
    s.add_argument("page")
    s.add_argument("--interval", type=int, default=60)
    s.add_argument("--timeout-hours", type=float, default=24)
    s.set_defaults(fn=cmd_wait)
    s = sub.add_parser("read")
    s.add_argument("page")
    s.set_defaults(fn=cmd_read)
    s = sub.add_parser("resolve")
    s.add_argument("page")
    s.add_argument("--summary", required=True)
    s.add_argument("--status")
    s.add_argument("--check", action="append", metavar="LABEL")
    s.set_defaults(fn=cmd_resolve)
    a = p.parse_args()
    if a.cmd == "ask" and len(a.option) < 2:
        p.error("ask needs at least two --option")
    try:
        a.fn(a)
    except Unreachable as e:
        sys.exit(str(e))


if __name__ == "__main__":
    main()
