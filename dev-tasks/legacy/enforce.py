#!/usr/bin/env python3
"""dev-tasks 强提醒扩展
为高优先级任务提供：
1. 强提醒（5 分钟一次）
2. 必须确认（用户必须回 "完成" 才停止）
3. 多通道通知：TTS + 飞书
4. 持久化（cron 自动重发）

用法：
  python3 enforce.py add "吃药" --reason "饭后 30 分钟" --priority high
  python3 enforce.py list
  python3 enforce.py done "吃药"
  python3 enforce.py cancel "吃药"
"""
import json
import os
import sys
import subprocess
import time
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List

# === 路径 ===
SKILL_DIR = Path(__file__).parent.parent
ENFORCE_STATE_FILE = Path.home() / ".hermes/dev-tasks/enforce_state.json"
HERMES_BIN = Path.home() / "Library/Application Support/cn.org.hermesagent.desktop/runtime/desktop-bin/hermes"
MILOCO_CLI = "/Users/garry/.local/bin/miloco-cli"
TTS_DEVICE = "书房"  # 总管 mini


def load_state() -> dict:
    """加载强提醒状态"""
    ENFORCE_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    if not ENFORCE_STATE_FILE.exists():
        return {"active": {}, "history": []}
    try:
        return json.loads(ENFORCE_STATE_FILE.read_text())
    except Exception:
        return {"active": {}, "history": []}


def save_state(state: dict) -> None:
    ENFORCE_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    ENFORCE_STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False))


def tts_announce(message: str) -> bool:
    """通过 miloco-tts 强制 TTS"""
    try:
        result = subprocess.run(
            ["/Library/Developer/CommandLineTools/usr/bin/python3",
             str(SKILL_DIR / "miloco-tts" / "scripts" / "miloco_tts.py"),
             f"对{TTS_DEVICE}说 {message}"],
            capture_output=True, text=True, timeout=15
        )
        return result.returncode == 0
    except Exception as e:
        print(f"[TTS failed] {e}")
        return False


def feishu_send(message: str) -> bool:
    """发飞书"""
    try:
        result = subprocess.run(
            [str(HERMES_BIN), "send", "-t", "feishu", message],
            capture_output=True, text=True, timeout=15
        )
        return result.returncode == 0
    except Exception as e:
        print(f"[Feishu failed] {e}")
        return False


def add_enforce(task: str, reason: str = "", priority: str = "high",
                interval_min: int = 5, max_remind: int = 0) -> Dict:
    """添加强提醒任务"""
    state = load_state()
    task_id = f"{task}_{int(time.time())}"

    state["active"][task_id] = {
        "task": task,
        "reason": reason,
        "priority": priority,
        "interval_min": interval_min,
        "max_remind": max_remind,
        "created_at": datetime.now().isoformat(),
        "last_remind_at": None,
        "remind_count": 0,
        "status": "pending"  # pending / done / cancelled
    }
    save_state(state)

    # 立即提醒一次
    send_remind(task_id)

    return {"status": "ok", "task_id": task_id, "task": task}


def send_remind(task_id: str) -> bool:
    """发送一次提醒"""
    state = load_state()
    task = state["active"].get(task_id)
    if not task or task["status"] != "pending":
        return False

    msg = (
        f"⚠️ 强提醒 [{task['task']}]\n"
        f"原因: {task.get('reason', '未填')}\n"
        f"已提醒 {task['remind_count'] + 1} 次（每 {task['interval_min']} 分钟）\n"
        f"完成后飞书回 '完成 {task['task']}' 取消提醒"
    )

    # 多通道
    tts_text = f"强提醒：{task['task']}，请立即完成"
    tts_announce(tts_text)
    feishu_send(msg)

    task["last_remind_at"] = datetime.now().isoformat()
    task["remind_count"] += 1
    save_state(state)

    return True


def mark_done(task: str) -> Dict:
    """标记任务完成"""
    state = load_state()

    # 通过 task 名称找（最近匹配的）
    target_id = None
    target_task = None
    for tid, t in state["active"].items():
        if t["task"] == task and t["status"] == "pending":
            target_id = tid
            target_task = t
            break

    if not target_id:
        return {"status": "not_found", "task": task}

    target_task["status"] = "done"
    target_task["completed_at"] = datetime.now().isoformat()
    state["history"].append(target_task)
    save_state(state)

    tts_announce(f"已确认 {task} 完成")
    feishu_send(f"✅ {task} 已完成（共提醒 {target_task['remind_count']} 次）")

    return {
        "status": "ok",
        "task": task,
        "remind_count": target_task["remind_count"],
        "duration": (
            datetime.fromisoformat(target_task["completed_at"]) -
            datetime.fromisoformat(target_task["created_at"])
        ).total_seconds() / 60
    }


def cancel_task(task: str) -> Dict:
    """取消任务"""
    return mark_done(task)  # 同 mark_done


def list_active() -> List:
    """列出所有 active 强提醒"""
    state = load_state()
    return [
        {"task_id": tid, **t}
        for tid, t in state["active"].items()
        if t["status"] == "pending"
    ]


def watch_loop(check_interval_sec: int = 30):
    """watch 循环：定期检查是否需要提醒"""
    print(f"[enforce-watch] 启动（每 {check_interval_sec}s 检查）")
    last_check = {}
    while True:
        try:
            state = load_state()
            now = datetime.now()
            for tid, t in list(state["active"].items()):
                if t["status"] != "pending":
                    continue
                last = t.get("last_remind_at")
                if not last:
                    # 从未提醒过 → 立即提醒
                    send_remind(tid)
                    continue
                last_dt = datetime.fromisoformat(last)
                next_due = last_dt + timedelta(minutes=t["interval_min"])
                if now >= next_due:
                    if t["max_remind"] > 0 and t["remind_count"] >= t["max_remind"]:
                        # 达到上限，停止提醒
                        t["status"] = "timeout"
                        t["timeout_at"] = now.isoformat()
                        save_state(state)
                        feishu_send(
                            f"⏰ {t['task']} 强提醒超时（{t['remind_count']} 次未确认）"
                        )
                    else:
                        send_remind(tid)
        except KeyboardInterrupt:
            break
        except Exception as e:
            print(f"[enforce-watch] 错误: {e}")
        time.sleep(check_interval_sec)


def main():
    import argparse
    p = argparse.ArgumentParser(description="dev-tasks 强提醒扩展")
    sub = p.add_subparsers(dest="cmd", required=True)

    # add
    add_p = sub.add_parser("add", help="添加强提醒")
    add_p.add_argument("task", help="任务名称")
    add_p.add_argument("--reason", default="", help="原因")
    add_p.add_argument("--interval", type=int, default=5, help="提醒间隔（分钟）")
    add_p.add_argument("--max-remind", type=int, default=0, help="最大提醒次数（0=无限）")

    # done
    done_p = sub.add_parser("done", help="标记完成")
    done_p.add_argument("task", help="任务名称")

    # cancel
    cancel_p = sub.add_parser("cancel", help="取消任务")
    cancel_p.add_argument("task", help="任务名称")

    # list
    sub.add_parser("list", help="列出 active 强提醒")

    # watch
    watch_p = sub.add_parser("watch", help="watch 模式（每 N 秒检查）")
    watch_p.add_argument("--interval", type=int, default=30, help="检查间隔（秒）")

    # check-now（手动触发一次检查）
    sub.add_parser("check", help="立即检查一次（手动触发提醒）")

    args = p.parse_args()

    if args.cmd == "add":
        result = add_enforce(args.task, args.reason, "high",
                            args.interval, args.max_remind)
        print(json.dumps(result, indent=2, ensure_ascii=False))
    elif args.cmd == "done":
        result = mark_done(args.task)
        print(json.dumps(result, indent=2, ensure_ascii=False))
    elif args.cmd == "cancel":
        result = cancel_task(args.task)
        print(json.dumps(result, indent=2, ensure_ascii=False))
    elif args.cmd == "list":
        active = list_active()
        print(json.dumps(active, indent=2, ensure_ascii=False))
    elif args.cmd == "watch":
        watch_loop(args.interval)
    elif args.cmd == "check":
        # 立即触发所有 pending 的检查
        state = load_state()
        for tid, t in state["active"].items():
            if t["status"] == "pending":
                send_remind(tid)


if __name__ == "__main__":
    main()
