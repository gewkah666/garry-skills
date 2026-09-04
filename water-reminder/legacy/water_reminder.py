#!/usr/bin/env python3
"""
water-reminder 核心逻辑
1. 加载 .env (garry-skills + hermes fallback)
2. 检查 Notion 日程（是否会议/专注）
3. 检查 miloco 感知（是否在家）
4. 检查本地 state（暂停/已达目标）
5. 触发提醒：TTS + 飞书
6. 等 15 分钟没确认 → 升级
"""

import json
import os
import sys
import subprocess
import urllib.request
import urllib.parse
from datetime import datetime, timedelta, time
from pathlib import Path
from typing import Optional, Dict, List

# === 路径配置 ===
SKILL_DIR = Path(__file__).parent.parent
STATE_FILE = Path.home() / ".hermes" / "miloco" / "water_state.json"
HERMES_BIN = Path.home() / "Library/Application Support/cn.org.hermesagent.desktop/runtime/desktop-bin/hermes"
# miloco-tts 脚本（在兄弟 skill 目录）
MILOCO_TTS_SCRIPT = Path.home() / "Projects" / "garry-skills" / "miloco-tts" / "scripts" / "miloco_tts.py"

# === .env 加载（garry-skills → ~/.hermes → Hermes Desktop fallback） ===
def _load_env() -> Dict[str, str]:
    env: Dict[str, str] = {}

    def _parse(path: Path) -> None:
        try:
            for line in open(path):
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    env[k.strip()] = v.strip().strip('"').strip("'")
        except (FileNotFoundError, PermissionError):
            pass

    # 优先级（后面的覆盖前面的）：
    # 1. garry-skills/.env (用户级自定义)
    # 2. ~/.hermes/.env (Hermes 主配置)
    # 3. Hermes Desktop runtime .env (可能含 NOTION_API_KEY)
    _parse(SKILL_DIR / ".env")
    _parse(Path.home() / ".hermes" / ".env")
    _parse(Path.home() / "Library/Application Support/cn.org.hermesagent.desktop/runtime/hermes-home/.env")

    # 别名 fallback
    if "MINIMAX_API_KEY" not in env and "MINIMAX_CN_API_KEY" in env:
        env["MINIMAX_API_KEY"] = env["MINIMAX_CN_API_KEY"]
    return env

ENV = _load_env()

# === 配置 ===
class Config:
    NOTION_API_KEY = ENV.get("NOTION_API_KEY", "")
    # 阅览世界数据库（足迹/日常/记录型）
    NOTION_DIARY_DB_ID = ENV.get("NOTION_DIARY_DB_ID", "747e9f3b-0bbf-4f03-b678-7fc62a093790")
    # 名称
    SELECT_TYPE_DAILY = "日常"        # 喝水 = "日常"
    SELECT_STATUS_LOGGED = "已记录"   # 状态 = "已记录"
    # TTS
    TTS_DEVICE = "书房"
    # 饮水目标
    DAILY_TARGET_CUPS = 8
    CUP_VOLUME_ML = 200
    # 提醒频率
    REMIND_FREQUENCY_HOURS = 2
    ESCALATE_AFTER_MIN = 15
    CRITICAL_AFTER_MIN = 30
    # 时间窗口
    WEEKDAY_HOURS = (9, 22)
    WEEKEND_HOURS = (10, 23)
    # 飞书
    FEISHU_TARGET = "feishu"

# === 工具函数 ===
def now_cn() -> datetime:
    """当前本地时间"""
    return datetime.now()


def today_key() -> str:
    return now_cn().strftime("%Y-%m-%d")


def is_weekend() -> bool:
    return now_cn().weekday() >= 5  # 周六周日


def in_active_hours() -> bool:
    """当前是否在提醒时段"""
    start, end = Config.WEEKEND_HOURS if is_weekend() else Config.WEEKDAY_HOURS
    h = now_cn().hour
    return start <= h < end


# === 状态管理 ===
def load_state() -> dict:
    """加载今日状态"""
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    if not STATE_FILE.exists():
        return _new_state()
    try:
        with open(STATE_FILE) as f:
            state = json.load(f)
        if state.get("date") != today_key():
            return _new_state()
        return state
    except Exception:
        return _new_state()


def save_state(state: dict) -> None:
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)


def _new_state() -> dict:
    return {
        "date": today_key(),
        "cups": 0,
        "last_remind": None,
        "last_confirm": None,
        "paused_until": None,
        "skip_today": False,
        "remind_count": 0,
        "escalate_count": 0
    }


# === 检查函数 ===
def check_skip_reasons() -> Optional[str]:
    """返回跳过原因（None 表示不跳过）"""
    state = load_state()

    # 1. 整天跳过
    if state.get("skip_today"):
        return "skip_today"

    # 2. 暂停中
    paused_until = state.get("paused_until")
    if paused_until:
        until = datetime.fromisoformat(paused_until)
        if now_cn() < until:
            return f"paused_until_{paused_until}"

    # 3. 不在活跃时段
    if not in_active_hours():
        return "out_of_hours"

    # 4. 已达目标
    if state.get("cups", 0) >= Config.DAILY_TARGET_CUPS:
        return "goal_reached"

    # 5. 频率太近（不到 1 小时）
    last = state.get("last_remind")
    if last:
        last_dt = datetime.fromisoformat(last)
        if now_cn() - last_dt < timedelta(minutes=60):
            return f"too_soon_after_{last}"

    return None


def check_notion_focus() -> bool:
    """查询 Notion 当前是否在会议/专注块"""
    if not Config.NOTION_API_KEY or not Config.NOTION_CALENDAR_DB_ID:
        return False  # 没配置，默认不视为专注

    try:
        now = now_cn()
        # Notion API: query database for events covering now
        url = f"https://api.notion.com/v1/databases/{Config.NOTION_CALENDAR_DB_ID}/query"
        headers = {
            "Authorization": f"Bearer {Config.NOTION_API_KEY}",
            "Notion-Version": "2022-06-28",
            "Content-Type": "application/json"
        }
        # 查过去 5 分钟到未来 5 分钟
        start = (now - timedelta(minutes=5)).isoformat()
        end = (now + timedelta(minutes=30)).isoformat()
        body = {
            "filter": {
                "and": [
                    {"property": "Start", "date": {"on_or_after": start}},
                    {"property": "Start", "date": {"on_or_before": end}}
                ]
            },
            "page_size": 3
        }
        req = urllib.request.Request(
            url, data=json.dumps(body).encode(), method="POST",
            headers=headers
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
            results = data.get("results", [])
            for r in results:
                title_prop = r.get("properties", {}).get("Name", {}) or r.get("properties", {}).get("Title", {})
                title = ""
                if title_prop.get("title"):
                    title = "".join(t.get("plain_text", "") for t in title_prop["title"])
                if any(kw in title.lower() for kw in ["focus", "deep work", "专注", "会议", "meeting"]):
                    return True
    except Exception as e:
        print(f"[Notion check failed] {e}")
    return False


def check_miloco_home() -> bool:
    """查询 miloco 摄像头是否检测到人（最近 5 分钟）"""
    try:
        url = "http://127.0.0.1:1810/api/perception/recent"
        req = urllib.request.Request(url, method="GET",
            headers={"Authorization": f"Bearer {ENV.get('MILOCO_TOKEN', '10ef1a3b-85e1-4645-ae28-95d2f96e92ca')}"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read())
            # 简化的判断
            return data.get("has_person", False)
    except Exception:
        return True  # 默认在家（避免误跳过）


# === 提醒动作 ===
def tts_announce(text: str) -> bool:
    """通过 miloco-tts 调用书房 mini"""
    try:
        result = subprocess.run(
            ["/Library/Developer/CommandLineTools/usr/bin/python3",
             str(MILOCO_TTS_SCRIPT),
             f"对{Config.TTS_DEVICE}说 {text}"],
            capture_output=True, text=True, timeout=15
        )
        if result.returncode != 0:
            print(f"[TTS] stderr: {result.stderr[:200]}")
        return result.returncode == 0
    except Exception as e:
        print(f"[TTS failed] {e}")
        return False


def feishu_send(message: str) -> bool:
    """通过 hermes send 发飞书消息"""
    try:
        result = subprocess.run(
            [str(HERMES_BIN), "send", "-t", Config.FEISHU_TARGET, message],
            capture_output=True, text=True, timeout=30
        )
        return result.returncode == 0
    except Exception as e:
        print(f"[Feishu failed] {e}")
        return False


def notion_log_water(cup_index: int, total_cups: int) -> Dict:
    """写入喝水记录到 Notion 阅览世界数据库

    只有 cups 真的增加时才调用（用户确认后）
    """
    if not Config.NOTION_API_KEY:
        return {"status": "skipped", "reason": "no_notion_key"}

    try:
        now = now_cn()
        # 标题格式: "🚰 喝水 - 2026-07-31 16:30 (3/8)"
        title = f"🚰 喝水 - {now.strftime('%Y-%m-%d %H:%M')} ({total_cups}/{Config.DAILY_TARGET_CUPS})"
        # 短评: 进度
        short = f"第 {cup_index} 杯，累计 {total_cups * Config.CUP_VOLUME_ML}ml"
        # 时间线: 喝水的瞬间（用 start 字段，date 含时分）
        timeline_start = now.strftime("%Y-%m-%dT%H:%M:%S+08:00")

        url = "https://api.notion.com/v1/pages"
        headers = {
            "Authorization": f"Bearer {Config.NOTION_API_KEY}",
            "Notion-Version": "2022-06-28",
            "Content-Type": "application/json"
        }
        body = {
            "parent": {"database_id": Config.NOTION_DIARY_DB_ID},
            "properties": {
                "名字": {
                    "title": [{"text": {"content": title}}]
                },
                "类型": {
                    "select": {"name": Config.SELECT_TYPE_DAILY}
                },
                "状态": {
                    "select": {"name": Config.SELECT_STATUS_LOGGED}
                },
                "时间线": {
                    "date": {"start": timeline_start}
                },
                "短评": {
                    "rich_text": [{"text": {"content": short}}]
                }
            }
        }
        req = urllib.request.Request(
            url, data=json.dumps(body).encode(), method="POST",
            headers=headers
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
            if data.get("object") == "page":
                return {
                    "status": "ok",
                    "page_id": data.get("id"),
                    "url": data.get("url"),
                    "title": title,
                    "timeline": timeline_start
                }
            return {"status": "error", "data": data}
    except Exception as e:
        print(f"[Notion log failed] {e}")
        return {"status": "error", "error": str(e)}


# === 主流程 ===
def trigger_remind() -> Dict:
    """触发一次提醒"""
    state = load_state()

    # 跳过检查
    skip = check_skip_reasons()
    if skip:
        return {"status": "skipped", "reason": skip}

    # Notion 会议检查
    if check_notion_focus():
        return {"status": "skipped", "reason": "notion_focus_block"}

    # miloco 在家检查
    if not check_miloco_home():
        return {"status": "skipped", "reason": "not_home"}

    # 触发提醒
    cups = state.get("cups", 0)
    next_cup = cups + 1
    progress_pct = int(cups / Config.DAILY_TARGET_CUPS * 100)

    # 升级判断
    is_escalate = state.get("remind_count", 0) > 0 and not state.get("last_confirm")

    if is_escalate:
        # 升级版
        message_feishu = (
            f"🚨 还没喝水！{cups}/{Config.DAILY_TARGET_CUPS} 杯\n"
            f"已经提醒 {state.get('remind_count', 0)} 次了\n"
            f"⏰ 喝水不会打断工作太久，但脱水会"
        )
        message_tts = "你还没喝水，现在，立刻"
        state["escalate_count"] = state.get("escalate_count", 0) + 1
    else:
        # 普通提醒
        message_feishu = (
            f"🚰 喝水时间！\n"
            f"当前: {cups}/{Config.DAILY_TARGET_CUPS} 杯 ({cups*Config.CUP_VOLUME_ML}ml)\n"
            f"⏰ 15 分钟内回 'ok' 确认"
        )
        message_tts = "喝口水，别等渴了才喝"

    # 记录本次提醒
    state["last_remind"] = now_cn().isoformat()
    state["remind_count"] = state.get("remind_count", 0) + 1
    save_state(state)

    # 触发 TTS + 飞书
    tts_ok = tts_announce(message_tts)
    feishu_ok = feishu_send(message_feishu)

    return {
        "status": "ok",
        "cups": cups,
        "target": Config.DAILY_TARGET_CUPS,
        "tts": tts_ok,
        "feishu": feishu_ok,
        "escalate": is_escalate
    }


def handle_user_reply(reply: str) -> Dict:
    """处理用户飞书回复"""
    state = load_state()
    reply = reply.strip().lower()

    # 确认命令
    if reply in ["ok", "喝了", "喝", "👌", "好的", "已喝"]:
        state["cups"] = state.get("cups", 0) + 1
        state["last_confirm"] = now_cn().isoformat()
        # 写 Notion 记录（仅在确认时）
        notion_result = notion_log_water(state["cups"], state["cups"])
        save_state(state)
        msg = f"✓ 记下了！当前 {state['cups']}/{Config.DAILY_TARGET_CUPS} 杯"
        if notion_result.get("status") == "ok":
            msg += f"\n📝 Notion 已记录: {notion_result.get('title', '')}"
        elif notion_result.get("status") == "skipped":
            msg += "\n⚠ Notion 跳过（无 key）"
        else:
            msg += f"\n⚠ Notion 记录失败: {notion_result.get('error', '?')}"
        feishu_send(msg)
        return {"status": "confirmed", "cups": state["cups"], "notion": notion_result}

    # 主动加一杯
    if "加一杯" in reply or "+1" in reply:
        state["cups"] = state.get("cups", 0) + 1
        state["last_confirm"] = now_cn().isoformat()
        notion_result = notion_log_water(state["cups"], state["cups"])
        save_state(state)
        msg = f"✓ 加一杯！当前 {state['cups']}/{Config.DAILY_TARGET_CUPS} 杯"
        if notion_result.get("status") == "ok":
            msg += f"\n📝 Notion 已记录"
        feishu_send(msg)
        return {"status": "added", "cups": state["cups"], "notion": notion_result}

    # 暂停
    if reply in ["暂停", "开会", "别打扰", "忙"]:
        until = now_cn() + timedelta(hours=2)
        state["paused_until"] = until.isoformat()
        save_state(state)
        msg = f"⏸ 暂停到 {until.strftime('%H:%M')}"
        feishu_send(msg)
        return {"status": "paused", "until": until.isoformat()}

    # 整天跳过
    if "今天不" in reply or "别提醒" in reply:
        state["skip_today"] = True
        save_state(state)
        msg = "✓ 今天不再提醒。明早恢复。"
        feishu_send(msg)
        return {"status": "skip_today"}

    # 进度查询
    if "几点了" in reply or "进度" in reply or "状态" in reply:
        cups = state.get("cups", 0)
        msg = (
            f"今日饮水: {cups}/{Config.DAILY_TARGET_CUPS} 杯 "
            f"({cups*Config.CUP_VOLUME_ML}ml)\n"
            f"达成: {int(cups/Config.DAILY_TARGET_CUPS*100)}%"
        )
        feishu_send(msg)
        return {"status": "report", "cups": cups}

    # 重置
    if "重置" in reply:
        save_state(_new_state())
        msg = "✓ 今日重置"
        feishu_send(msg)
        return {"status": "reset"}

    return {"status": "unknown_command"}


# === CLI ===
def main():
    import argparse
    p = argparse.ArgumentParser(description="Water reminder")
    p.add_argument("--trigger", action="store_true", help="触发一次提醒")
    p.add_argument("--reply", help="处理用户飞书回复")
    p.add_argument("--status", action="store_true", help="看当前状态")
    p.add_argument("--check", action="store_true", help="检查是否应该提醒（不实际触发）")
    args = p.parse_args()

    if args.status:
        s = load_state()
        print(json.dumps(s, indent=2, ensure_ascii=False))
        return

    if args.check:
        skip = check_skip_reasons()
        in_focus = check_notion_focus()
        home = check_miloco_home()
        print(json.dumps({
            "should_remind": skip is None and not in_focus and home,
            "skip_reason": skip,
            "in_focus": in_focus,
            "at_home": home,
            "now": now_cn().isoformat(),
        }, indent=2, ensure_ascii=False))
        return

    if args.reply:
        result = handle_user_reply(args.reply)
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return

    if args.trigger:
        result = trigger_remind()
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return

    # 默认：触发提醒
    result = trigger_remind()
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
