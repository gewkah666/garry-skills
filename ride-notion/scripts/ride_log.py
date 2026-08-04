"""ride-notion 核心脚本"""
import json
import sys
import argparse
import urllib.request
import urllib.parse
import re
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from config import Config

# === 运动类型映射 ===
ACTIVITY_ALIASES = {
    "骑行": "骑行", "bike": "骑行", "cycling": "骑行", "公路车": "骑行",
    "折叠车": "骑行", "山地车": "骑行", "夜骑": "骑行",
    "跑步": "跑步", "run": "跑步", "running": "跑步", "慢跑": "跑步",
    "游泳": "游泳", "swim": "游泳", "swimming": "游泳",
    "徒步": "徒步", "hike": "徒步", "hiking": "徒步", "健走": "徒步",
    "健身": "健身", "gym": "健身", "力量": "健身", "撸铁": "健身",
    "跳绳": "跳绳", "rope": "跳绳",
    "瑜伽": "瑜伽", "yoga": "瑜伽",
}

ACTIVITY_EMOJI = {
    "骑行": "🚴", "跑步": "🏃", "游泳": "🏊", "徒步": "🥾",
    "健身": "💪", "跳绳": "🤸", "瑜伽": "🧘",
}


def resolve_activity(text: str) -> str:
    """从文本识别运动类型"""
    text_lower = text.lower()
    for alias, name in ACTIVITY_ALIASES.items():
        if alias in text_lower or alias.lower() in text_lower:
            return name
    return "骑行"  # 默认


def parse_duration(s: str) -> timedelta:
    """解析 '1h13m44s' 或 '3600' (秒)"""
    if isinstance(s, (int, float)):
        return timedelta(seconds=int(s))
    s = str(s).strip()
    # 1h13m44s
    m = re.match(r'(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s)?$', s)
    if m:
        h, mi, se = m.groups()
        return timedelta(hours=int(h or 0), minutes=int(mi or 0), seconds=int(se or 0))
    # 纯数字秒
    try:
        return timedelta(seconds=int(s))
    except Exception:
        raise ValueError(f"无法解析时长: {s}")


def format_duration(td: timedelta) -> str:
    """timedelta → '1h13m' 或 '13m44s'"""
    s = int(td.total_seconds())
    h = s // 3600
    m = (s % 3600) // 60
    sec = s % 60
    if h:
        return f"{h}h{m}m"
    return f"{m}m{sec}s"


def intensity_zone(avg_hr: int, max_hr: int = 190) -> str:
    """根据心率评估强度"""
    if not avg_hr:
        return ""
    pct = avg_hr / max_hr
    if pct < 0.6:
        return "热身"
    if pct < 0.7:
        return "燃脂"
    if pct < 0.8:
        return "有氧"
    if pct < 0.9:
        return "无氧"
    return "极限"


def log_to_notion(activity: str, distance_km: float, duration: str,
                  avg_speed: float, avg_hr: int, calories: int,
                  elevation: int, location: str, start_time: str,
                  end_time: str = "", segments: list = None,
                  note: str = "", link: str = "") -> dict:
    """写入 Notion 阅览世界"""
    if not Config.NOTION_API_KEY:
        return {"status": "error", "message": "NOTION_API_KEY 未配置"}

    # 解析数据
    activity = resolve_activity(activity)
    td = parse_duration(duration)
    emoji = ACTIVITY_EMOJI.get(activity, "🏃")

    # 标题
    if distance_km:
        title = f"{emoji} {activity} - {distance_km} km - {format_duration(td)}"
    else:
        title = f"{emoji} {activity} - {format_duration(td)}"

    # 短评
    parts = []
    if location:
        parts.append(f"📍 {location}")
    if avg_speed:
        parts.append(f"{avg_speed} km/h")
    if avg_hr:
        parts.append(f"{avg_hr} bpm")
        zone = intensity_zone(avg_hr, Config.DEFAULT_MAX_HR)
        if zone:
            parts.append(f"({zone})")
    if calories:
        parts.append(f"{calories} kcal")
    if elevation:
        parts.append(f"⛰{elevation}m")
    short = " · ".join(parts)
    if note:
        short += f"\n💡 {note}"

    # 时间线
    timeline_start = start_time
    timeline_end = end_time
    if not end_time:
        # 自动计算
        dt = datetime.fromisoformat(start_time)
        dt_end = dt + td
        timeline_end = dt_end.isoformat()

    # 写 Notion
    url = "https://api.notion.com/v1/pages"
    headers = {
        "Authorization": f"Bearer {Config.NOTION_API_KEY}",
        "Notion-Version": "2022-06-28",
        "Content-Type": "application/json"
    }

    properties = {
        "名字": {"title": [{"text": {"content": title}}]},
        "类型": {"select": {"name": Config.SELECT_TYPE_DAILY}},
        "状态": {"select": {"name": Config.SELECT_STATUS_LOGGED}},
        "时间线": {"date": {"start": timeline_start, "end": timeline_end}},
        "短评": {"rich_text": [{"text": {"content": short}}]},
    }
    if link:
        properties["链接"] = {"url": link}

    body = {
        "parent": {"database_id": Config.NOTION_DIARY_DB_ID},
        "properties": properties
    }

    # 段数据写入页面正文
    if segments:
        body["children"] = [
            {
                "object": "block",
                "type": "heading_2",
                "heading_2": {"rich_text": [{"type": "text", "text": {"content": "段数据"}}]}
            }
        ]
        for i, seg in enumerate(segments, 1):
            seg_text = f"段 {i}: {seg.get('time', '')} | {seg.get('speed', '')} km/h | {seg.get('hr', '')} bpm"
            body["children"].append({
                "object": "block",
                "type": "bulleted_list_item",
                "bulleted_list_item": {"rich_text": [{"type": "text", "text": {"content": seg_text}}]}
            })

    try:
        req = urllib.request.Request(
            url, data=json.dumps(body).encode(), method="POST",
            headers=headers
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
            if data.get("object") == "page":
                return {
                    "status": "ok",
                    "page_id": data.get("id"),
                    "url": data.get("url"),
                    "title": title,
                    "short": short
                }
            return {"status": "error", "data": data}
    except Exception as e:
        return {"status": "error", "error": str(e)}


def parse_args_log(args):
    """解析 log 子命令参数"""
    return {
        "activity": args.activity,
        "distance_km": args.distance,
        "duration": args.duration,
        "avg_speed": args.avg_speed,
        "avg_hr": args.avg_hr,
        "calories": args.calories,
        "elevation": args.elevation,
        "location": args.location,
        "start_time": args.start_time,
        "end_time": args.end_time,
        "segments": json.loads(args.segments) if args.segments else None,
        "note": args.note,
        "link": args.link,
    }


def main():
    p = argparse.ArgumentParser(description="ride-notion")
    sub = p.add_subparsers(dest="cmd")

    # log
    log_p = sub.add_parser("log", help="记录一次运动")
    log_p.add_argument("--activity", default="骑行", help="运动类型")
    log_p.add_argument("--distance", type=float, help="距离 (km)")
    log_p.add_argument("--duration", help="时长 (1h13m44s 或秒数)")
    log_p.add_argument("--avg-speed", type=float, help="平均速度 (km/h)")
    log_p.add_argument("--avg-hr", type=int, help="平均心率 (bpm)")
    log_p.add_argument("--calories", type=int, help="总千卡")
    log_p.add_argument("--elevation", type=int, help="爬升 (m)")
    log_p.add_argument("--location", default="", help="地点")
    log_p.add_argument("--start-time", required=True, help="开始时间 ISO")
    log_p.add_argument("--end-time", help="结束时间 ISO（可选）")
    log_p.add_argument("--segments", help="段数据 JSON")
    log_p.add_argument("--note", default="", help="备注")
    log_p.add_argument("--link", default="", help="Strava/链接")

    # test
    sub.add_parser("test", help="用示例数据测试")

    args = p.parse_args()

    if args.cmd == "log":
        data = parse_args_log(args)
        result = log_to_notion(**data)
        print(json.dumps(result, indent=2, ensure_ascii=False))
    elif args.cmd == "test":
        # 用你刚才截图里的数据测试
        result = log_to_notion(
            activity="骑行",
            distance_km=20.59,
            duration="1h13m44s",
            avg_speed=16.7,
            avg_hr=131,
            calories=440,
            elevation=33,
            location="杭州",
            start_time="2026-08-04T22:02:00",
            end_time="2026-08-04T23:16:00",
            segments=[
                {"time": "17:11", "speed": 17.4, "hr": 124},
                {"time": "18:52", "speed": 15.8, "hr": 127},
                {"time": "17:39", "speed": 16.9, "hr": 133},
                {"time": "16:2?", "speed": 10.0, "hr": 131},
                {"time": "03:??", "speed": 9.4, "hr": None},
            ],
            note="夜骑绕西湖"
        )
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        p.print_help()


if __name__ == "__main__":
    main()
