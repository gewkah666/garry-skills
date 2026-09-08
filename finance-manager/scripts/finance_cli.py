#!/Users/garry/.hermes/hermes-agent/venv/bin/python
"""finance_cli — the finance plugin from the shell (Claude Code, cron, debugging).

  finance_cli.py sync [--full]
  finance_cli.py status [--month YYYY-MM]
  finance_cli.py query [--from D] [--to D] [--io X] [--category C] [--sub S] [--account A] [--keyword K] [--limit N]
  finance_cli.py record --json '[{"amount":28,"io":"支出","category":"餐饮","subcategory":"午餐","account":"支付宝"}]' [--source 手工]
  finance_cli.py record --amount 28 --io 支出 --category 餐饮 --sub 午餐 --account 支付宝 [--name 面馆] [--date "2026-09-08 12:10"] [--to-account X] [--note ..]
  finance_cli.py update --id ID|--latest|--text T [--days N] --set key=value [...]
  finance_cli.py delete --id ID|--latest|--text T [--no-pair]
  finance_cli.py reconcile --account A --balance N [--at "YYYY-MM-DD HH:MM"] [--evidence ..]
  finance_cli.py import --file bills.csv        (M4)
  finance_cli.py report --month YYYY-MM|last    (M3)

Loads ~/.hermes/plugins/finance directly (no Hermes needed). Output is JSON.
"""
import argparse
import importlib.util
import json
import os
import sys
from pathlib import Path

HOME = Path(os.environ.get("HERMES_HOME", os.path.expanduser("~/.hermes")))
PKG = HOME / "plugins" / "finance"


def load():
    spec = importlib.util.spec_from_file_location("finance", PKG / "__init__.py", submodule_search_locations=[str(PKG)])
    pkg = importlib.util.module_from_spec(spec)
    sys.modules["finance"] = pkg
    spec.loader.exec_module(pkg)
    from finance import ops
    return ops


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("sync"); s.add_argument("--full", action="store_true")
    s = sub.add_parser("status"); s.add_argument("--month")
    s = sub.add_parser("query")
    for k in ("from", "to", "io", "category", "sub", "account", "keyword"):
        s.add_argument("--" + k)
    s.add_argument("--limit", type=int, default=50)
    s = sub.add_parser("record")
    s.add_argument("--json"); s.add_argument("--source", default="手工"); s.add_argument("--allow-duplicate", action="store_true")
    for k in ("amount", "io", "category", "sub", "account", "to-account", "name", "date", "note"):
        s.add_argument("--" + k)
    for name in ("update", "delete"):
        s = sub.add_parser(name)
        s.add_argument("--id"); s.add_argument("--latest", action="store_true"); s.add_argument("--text"); s.add_argument("--days", type=int)
        if name == "update":
            s.add_argument("--set", action="append", default=[], help="key=value，可多次")
        else:
            s.add_argument("--no-pair", action="store_true")
    s = sub.add_parser("reconcile")
    s.add_argument("--account", required=True); s.add_argument("--balance", type=float, required=True)
    s.add_argument("--at"); s.add_argument("--evidence")
    s = sub.add_parser("import"); s.add_argument("--file", required=True)
    s = sub.add_parser("report"); s.add_argument("--month", default="last")
    a = ap.parse_args()
    ops = load()

    if a.cmd == "sync":
        out = ops.sync(full=a.full)
    elif a.cmd == "status":
        out = ops.status(a.month)
    elif a.cmd == "query":
        out = ops.query(from_=getattr(a, "from"), to=a.to, io=a.io, category=a.category, subcategory=a.sub,
                        account=a.account, keyword=a.keyword, limit=a.limit)
    elif a.cmd == "record":
        if a.json:
            items = json.loads(a.json)
        else:
            items = [{k: v for k, v in {"amount": float(a.amount) if a.amount else None, "io": a.io, "category": a.category,
                                        "subcategory": a.sub, "account": a.account, "to_account": a.to_account,
                                        "name": a.name, "date": a.date, "note": a.note}.items() if v is not None}]
        out = ops.record(items, source=a.source, allow_duplicate=a.allow_duplicate)
    elif a.cmd in ("update", "delete"):
        loc = {k: v for k, v in {"id": a.id, "latest": a.latest or None, "text": a.text, "days": a.days}.items() if v}
        if a.cmd == "update":
            patch = {}
            for kv in a.set:
                k, v = kv.split("=", 1)
                patch["subcategory" if k == "sub" else k] = float(v) if k == "amount" else v
            out = ops.update(loc, patch)
        else:
            out = ops.delete(loc, with_pair=not a.no_pair)
    elif a.cmd == "reconcile":
        out = ops.reconcile(a.account, a.balance, a.at, a.evidence)
    else:
        out = {"ok": False, "error": f"{a.cmd}: M3/M4 尚未实现"}
    print(json.dumps(out, ensure_ascii=False, indent=2, default=str))
    return 0 if out.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
