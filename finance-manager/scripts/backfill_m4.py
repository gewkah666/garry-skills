#!/Users/garry/.hermes/hermes-agent/venv/bin/python
"""M4 历史治理一次性跑批（可重复执行，每步幂等）。日志 ~/.cache/finance-manager/backfill.log

锚点（期初余额 / 对账调整）不用跑批前快照，而是在翻正 / 补对手行之后用公式还原「翻正前」的余额再求解，
这样中途断掉重跑也不会把半成品固化。"""
import importlib.util, json, os, sys, time
from pathlib import Path
HOME = Path(os.environ.get("HERMES_HOME", os.path.expanduser("~/.hermes")))
PKG = HOME / "plugins" / "finance"
spec = importlib.util.spec_from_file_location("finance", PKG / "__init__.py", submodule_search_locations=[str(PKG)])
m = importlib.util.module_from_spec(spec); sys.modules["finance"] = m; spec.loader.exec_module(m)
from finance import backfill, ops
LOG = Path.home() / ".cache/finance-manager/backfill.log"; LOG.parent.mkdir(parents=True, exist_ok=True)
RUN_STARTED_UTC = "2026-09-08T07:00:00.000Z"   # 第一次跑批开始时刻（北京 15:00），用于识别本次补的对手行
def log(*a):
    line = time.strftime("%H:%M:%S ") + " ".join(str(x) for x in a)
    print(line, flush=True); LOG.open("a").write(line + "\n")
only = sys.argv[1] if len(sys.argv) > 1 else "all"
t0 = time.time(); log("== M4 backfill start", only)
if only in ("all", "categories"):
    plan = backfill.plan_categories(); log("category changes:", len(plan["changes"]), plan["how"])
    n = backfill.apply_categories(plan["changes"], progress=lambda i, t: log(f"  categories {i}/{t}")); log("categories applied:", n)
if only in ("all", "pairs"):
    pp = backfill.plan_pairs(); log("pair rows to create:", len(pp["to_create"]), "skipped:", pp["skipped"])
    n = backfill.apply_pairs(pp["to_create"], progress=lambda i, t: log(f"  pairs {i}/{t}")); log("pairs created:", n)
if only in ("all", "anchors"):
    ops.sync(); snap = backfill.original_anchor_snapshot(RUN_STARTED_UTC)
    json.dump(snap, open(LOG.parent / "anchors_original.json", "w"), ensure_ascii=False, indent=1)
    log("anchors:", len(snap), "with flips:", sum(1 for a in snap if a["flipped_sum"] or a["paired_sum"]))
    fixed = backfill.resolve_anchors(snap); log("anchors re-solved:", len(fixed))
    for f in fixed: log("  ", f)
    ops.sync()
    with ops.ledger.connect() as con:  # compare against the targets resolve_anchors used, not a recomputed snapshot
        bad = [(a["name"], ops.ledger.balance(con, a["account_id"], a["at"]), a["balance"]) for a in snap
               if abs(ops.ledger.balance(con, a["account_id"], a["at"]) - a["balance"]) > 0.01]
    log("anchor check mismatches:", bad or "none")
if only in ("all", "prune"):
    pr = backfill.prune_legacy_options(); log("legacy 类型 options dropped:", pr["dropped"])
s = ops.sync(full=True); log("health:", s["health"])
log("== done in %.0fs" % (time.time() - t0))
