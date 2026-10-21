#!/usr/bin/env python3
"""anime_download_notify.py — NAS qb 新番下载完成 → phantom_notify L2（App 推送）。

（观看记录监控曾在此脚本系列中上线，御主 2026-09-14 撤销：不追踪看了什么。）

状态: ~/.cache/anime-tracker/download_notify_state.json 记已见过的 hash, 只推增量。
推送走 ~/.hermes/scripts/phantom_notify.py --hold（打扰预算 → reach → 投递账本），不再直推 Bark。
预算 defer（睡觉/开会）或投递失败时由 phantom_notify 暂存，cron phantom-notify-flush 到点补发。
用法: python3 anime_download_notify.py [--dry-run]
"""
import os, sys, json, argparse, datetime, subprocess

STATE_FILE = os.path.expanduser("~/.cache/anime-tracker/download_notify_state.json")
ENV_FILE = os.path.expanduser("~/.hermes/.env")
WATCH_DIRS = ("/无职转生/", "/转生史莱姆", "Frieren", "芙莉莲")
NOW_TZ = datetime.timezone(datetime.timedelta(hours=8))

def load_env():
    env = dict(os.environ)
    for line in open(ENV_FILE):
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1); env.setdefault(k, v)
    return env

def load_state():
    if os.path.exists(STATE_FILE):
        return json.load(open(STATE_FILE))
    return {"notified": {}}

def save_state(st):
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    tmp = STATE_FILE + ".tmp"
    json.dump(st, open(tmp, "w"), ensure_ascii=False, indent=1)
    os.replace(tmp, STATE_FILE)

NOTIFY = os.path.expanduser("~/.hermes/scripts/phantom_notify.py")

def notify(title, body):
    r = subprocess.run([NOTIFY, "--level", "L2", "--kind", "anime", "--hold",
                        "--title", title, "--message", body],
                       capture_output=True, text=True, timeout=90)
    if r.returncode != 0:
        print(f"[notify-fail] rc={r.returncode} {r.stdout.strip()[:300]}", file=sys.stderr)

def qb_torrents(env):
    out = subprocess.run(["curl", "-s", "--connect-timeout", "8",
                          "-H", f"Authorization: Bearer {env['QBT_API_KEY']}",
                          env["QBT_URL"] + "/api/v2/torrents/info"],
                         capture_output=True, text=True)
    try:
        return json.loads(out.stdout)
    except Exception:
        return None

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    env = load_env()
    st = load_state()
    ts = qb_torrents(env)
    if ts is None:
        print(json.dumps({"error": "qb 不可达"})); return
    fresh = []
    for t in ts:
        if not any(d in t.get("save_path", "") for d in WATCH_DIRS):
            continue
        if t["progress"] >= 1.0 and t["state"] not in ("checkingUP", "checkingDOWN"):
            h = t["hash"]
            if h not in st["notified"]:
                st["notified"][h] = {"name": t["name"][:90],
                                     "at": datetime.datetime.now(NOW_TZ).isoformat()}
                fresh.append(t["name"][:90])
    if fresh and not args.dry_run:
        notify("📥 新番下载完成", " ｜ ".join(fresh[:3]) + ("…" if len(fresh) > 3 else ""))
    if not args.dry_run:
        save_state(st)
    print(json.dumps({"checked": len(ts), "new": len(fresh), "names": fresh[:5],
                      "dry_run": args.dry_run}, ensure_ascii=False))

if __name__ == "__main__":
    main()
