#!/Users/garry/.hermes/hermes-agent/venv/bin/python
"""M4 历史治理一次性跑批（可重复执行，每步幂等）。日志 ~/.cache/finance-manager/backfill.log"""
import importlib.util, json, os, sys, time
from pathlib import Path
HOME = Path(os.environ.get("HERMES_HOME", os.path.expanduser("~/.hermes")))
PKG = HOME / "plugins" / "finance"
spec = importlib.util.spec_from_file_location("finance", PKG / "__init__.py", submodule_search_locations=[str(PKG)])
m = importlib.util.module_from_spec(spec); sys.modules["finance"] = m; spec.loader.exec_module(m)
from finance import backfill, ops
LOG = Path.home() / ".cache/finance-manager/backfill.log"; LOG.parent.mkdir(parents=True, exist_ok=True)
def log(*a):
    line = time.strftime("%H:%M:%S ") + " ".join(str(x) for x in a)
    print(line, flush=True); LOG.open("a").write(line + "\n")
t0 = time.time()
log("== M4 backfill start")
snap = backfill.anchors_snapshot(); log("anchors snapshot:", len(snap))
json.dump(snap, open(LOG.parent / "anchors_snapshot.json", "w"), ensure_ascii=False)
plan = backfill.plan_categories(); log("category changes:", len(plan["changes"]), plan["how"])
n = backfill.apply_categories(plan["changes"], progress=lambda i, t: log(f"  categories {i}/{t}"))
log("categories applied:", n)
pp = backfill.plan_pairs(); log("pair rows to create:", len(pp["to_create"]), "skipped:", pp["skipped"])
n = backfill.apply_pairs(pp["to_create"], progress=lambda i, t: log(f"  pairs {i}/{t}")); log("pairs created:", n)
ops.sync(); fixed = backfill.resolve_anchors(snap); log("anchors re-solved:", len(fixed))
for f in fixed: log("  ", f)
ops.sync(); pr = backfill.prune_legacy_options(); log("legacy 类型 options dropped:", pr["dropped"])
s = ops.sync(full=True); log("health:", s["health"])
log("== done in %.0fs" % (time.time() - t0))
