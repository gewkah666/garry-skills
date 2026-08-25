#!/usr/bin/env python3
"""ride-notion 截图识别 + 写入 Notion
流程:
1. macOS Vision OCR 提取文本
2. 正则解析得到关键数值
3. 写 Notion 阅览世界
"""
import json
import re
import sys
import subprocess
import tempfile
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent))
from config import Config
from ride_log import log_to_notion, ACTIVITY_EMOJI


# OCR 工具路径
OCR_TOOL = "/tmp/ocr_vision"


def ocr_image(image_path: Path) -> str:
    """调 macOS Vision OCR"""
    if not Path(OCR_TOOL).exists():
        # 临时编译
        subprocess.run(["swiftc", "-o", OCR_TOOL, "/tmp/_ocr.swift"], check=False)
    result = subprocess.run(
        [OCR_TOOL, str(image_path)],
        capture_output=True, text=True, timeout=30
    )
    if result.returncode != 0:
        raise RuntimeError(f"OCR 失败: {result.stderr}")
    return result.stdout


def parse_apple_fitness(text: str) -> dict:
    """解析 Apple Fitness App 截图的文本

    关键字位置参考截图:
    - 体能训练时间
    - 距离
    - 平均速度
    - 平均心率
    - 动态千卡 / 总千卡数
    - 总爬升高度
    """
    # 清理 OCR 噪声（图标/UI 伪影）
    cleaned = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        # 过滤明显 UI 噪声
        if line in ("<", ">", "摘要", "单段>", "×"):
            continue
        # 过滤掉纯标点
        if re.match(r'^[<>×]+$', line):
            continue
        cleaned.append(line)

    text_j = "\n".join(cleaned)

    result = {
        "activity": "骑行",
        "date": None,
        "start_time": None,
        "end_time": None,
        "duration_sec": 0,
        "distance_km": 0.0,
        "avg_speed_kmh": 0.0,
        "avg_hr": 0,
        "calories": 0,
        "elevation_m": 0,
        "location": "",
        "raw_text": text_j,
    }

    # 1. 运动类型
    type_map = {
        "户外单车": ("骑行", "🚴"),
        "户外跑步": ("跑步", "🏃"),
        "户外步行": ("徒步", "🥾"),
        "户外徒步": ("徒步", "🥾"),
        "户外游泳": ("游泳", "🏊"),
        "户外跑": ("跑步", "🏃"),
        "户外骑行": ("骑行", "🚴"),
        "室内单车": ("骑行", "🚴"),
        "室内跑步": ("跑步", "🏃"),
        "室内行走": ("徒步", "🥾"),
    }
    for key, (name, _) in type_map.items():
        if key in text_j:
            result["activity"] = name
            break

    # 2. 日期（"8月4日周二"）
    m = re.search(r'(\d{1,2})月(\d{1,2})日(?:周[一二三四五六日])?', text_j)
    if m:
        month, day = int(m.group(1)), int(m.group(2))
        year = datetime.now().year
        # 如果月份比当前大一岁以上，可能是去年
        now = datetime.now()
        if month > now.month + 1 or (month == now.month + 1 and day > now.day):
            year -= 1
        result["date"] = f"{year:04d}-{month:02d}-{day:02d}"

    # 3. 起止时间（"22:02-23:16"）
    m = re.search(r'(\d{1,2}):(\d{2})\s*[-~—]\s*(\d{1,2}):(\d{2})', text_j)
    if m:
        sh, sm, eh, em = map(int, m.groups())
        result["start_time"] = f"{sh:02d}:{sm:02d}"
        result["end_time"] = f"{eh:02d}:{em:02d}"

    # 4. 体能训练时间 (1:13:44)
    # 注意：可能是 "1:13:44" 或 "01:13:44"
    m = re.search(r'体能训练时间\s*[\n\r]?\s*(\d{1,2}):(\d{2}):(\d{2})', text_j)
    if not m:
        # 备用：纯匹配 hh:mm:ss
        m = re.search(r'(?<!\d)(\d{1,2}):(\d{2}):(\d{2})(?!\d)', text_j)
    if m:
        h, mi, se = map(int, m.groups())
        result["duration_sec"] = h * 3600 + mi * 60 + se

    # 5. 距离 (20.59 公里)
    m = re.search(r'距离\s*[\n\r]?\s*(\d+\.?\d*)\s*公里', text_j)
    if m:
        result["distance_km"] = float(m.group(1))

    # 6. 平均速度 (16.7 公里/时)
    m = re.search(r'平均速度\s*[\n\r]?\s*(\d+\.?\d*)\s*公里', text_j)
    if m:
        result["avg_speed_kmh"] = float(m.group(1))

    # 7. 平均心率 (131 次/分)
    m = re.search(r'平均心率\s*[\n\r]?\s*(\d+)\s*次', text_j)
    if m:
        result["avg_hr"] = int(m.group(1))

    # 8. 动态千卡 (337 千卡) 或 总千卡数
    for field in ["动态千卡", "总千卡", "总千卡数", "耗能"]:
        m = re.search(rf'{field}\s*[\n\r]?\s*(\d+)\s*千卡', text_j)
        if m:
            result["calories"] = int(m.group(1))
            break

    # 9. 爬升（总爬升高度 33米）
    m = re.search(r'(?:总)?(?:爬升|爬升高度)\s*[\n\r]?\s*(\d+)\s*米', text_j)
    if m:
        result["elevation_m"] = int(m.group(1))

    # 10. 位置（爬前面的"X市"）
    # 中文位置：杭州市/北京市/某某区
    m = re.search(r'(\d{1,}[市县区]|[一二三四五六七八九十]市|[A-Z][a-z]+ City)', text_j)
    if m:
        result["location"] = m.group(1)

    # 11. ISO 起始时间
    if result["date"] and result["start_time"]:
        result["start_iso"] = f"{result['date']}T{result['start_time']}:00"
    else:
        result["start_iso"] = datetime.now().isoformat(timespec="seconds")

    return result


def parse_strava(text: str) -> dict:
    """解析 Strava 截图（备用）"""
    # TODO: 等有 Strava 截图再加
    return parse_apple_fitness(text)


def format_summary(parsed: dict) -> str:
    """生成简短摘要"""
    parts = []
    if parsed["location"]:
        parts.append(f"📍 {parsed['location']}")
    if parsed["avg_speed_kmh"]:
        parts.append(f"{parsed['avg_speed_kmh']} km/h")
    if parsed["avg_hr"]:
        parts.append(f"{parsed['avg_hr']} bpm")
    if parsed["calories"]:
        parts.append(f"{parsed['calories']} kcal")
    if parsed["elevation_m"]:
        parts.append(f"⛰{parsed['elevation_m']}m")
    return " · ".join(parts)


def main():
    import argparse
    p = argparse.ArgumentParser(description="截图识别 + 写入 Notion")
    p.add_argument("image", help="截图路径")
    p.add_argument("--dry-run", action="store_true", help="只解析不写")
    p.add_argument("--json", action="store_true", help="JSON 输出")
    p.add_argument("--correct", help="手动修正某字段，格式 'key=value'，可多次")
    args = p.parse_args()

    image_path = Path(args.image)
    if not image_path.exists():
        print(f"ERROR: 不存在 {image_path}")
        sys.exit(1)

    print(f"OCR 识别: {image_path}")
    text = ocr_image(image_path)
    if not args.json:
        print(f"\n--- OCR 原文 ---\n{text}\n---")

    # 解析
    parsed = parse_apple_fitness(text)
    if args.correct:
        for kv in args.correct:
            if "=" in kv:
                k, v = kv.split("=", 1)
                # 智能转换类型
                if k in ("distance_km", "avg_speed_kmh"):
                    parsed[k] = float(v)
                elif k in ("avg_hr", "calories", "elevation_m", "duration_sec"):
                    parsed[k] = int(v)
                elif k in ("start_time", "end_time", "activity", "location", "date"):
                    parsed[k] = v
                print(f"  修正: {k} = {v}")

    if args.json:
        print(json.dumps(parsed, indent=2, ensure_ascii=False))
        return

    print(f"\n--- 解析结果 ---")
    for k, v in parsed.items():
        if k == "raw_text":
            continue
        print(f"  {k}: {v}")

    if args.dry_run:
        print("\n[DRY RUN] 未写入 Notion")
        return

    # 写 Notion
    print("\n写入 Notion...")
    result = log_to_notion(
        activity=parsed["activity"],
        distance_km=parsed["distance_km"],
        duration=str(parsed["duration_sec"]),
        avg_speed=parsed["avg_speed_kmh"],
        avg_hr=parsed["avg_hr"],
        calories=parsed["calories"],
        elevation=parsed["elevation_m"],
        location=parsed["location"],
        start_time=parsed["start_iso"],
        note=f"OCR 识别: {parsed['activity']} {parsed['distance_km']}km"
    )
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
