#!/usr/bin/env python3
"""anime_download_notify.py — NAS qb 新番下载完成 → Bark 推送。

（观看记录监控曾在此脚本系列中上线，御主 2026-09-14 撤销：不追踪看了什么。）

状态: ~/.cache/anime-tracker/download_notify_state.json 记已推送 hash, 只推增量。
用法: python3 anime_download_notify.py [--dry-run]
"""
import os, sys, json, argparse, urllib.request, datetime, subprocess

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

def bark_push(env, title, body):
    srv = env["BARK_SERVER_URL"].rstrip("/")
    payload = {"device_key": env["BARK_DEVICE_KEY"], "title": title, "body": body,
               "group": env.get("BARK_GROUP", "phantom"), "level": "active", "isArchive": 1,
               "sound": "minuet", "url": "phantom://chat"}
    req = urllib.request.Request(srv + "/push", data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"})
    try:
        urllib.request.urlopen(req, timeout=15); return True
    except Exception as e:
        print(f"[bark-fail] {e}", file=sys.stderr); return False

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
        bark_push(env, "📥 新番下载完成", " ｜ ".join(fresh[:3]) + ("…" if len(fresh) > 3 else ""))
    if not args.dry_run:
        save_state(st)
    print(json.dumps({"checked": len(ts), "new": len(fresh), "names": fresh[:5],
                      "dry_run": args.dry_run}, ensure_ascii=False))

if __name__ == "__main__":
    main()
