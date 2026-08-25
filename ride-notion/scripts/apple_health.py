"""Apple Health XML 解析器
解析 iPhone Health App 导出的 export.xml，自动提取骑行/跑步/游泳等运动记录。
"""
import json
import re
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Optional


# HKWorkoutActivityType 映射
HK_WORKOUT_TYPES = {
    "HKWorkoutActivityTypeCycling": ("骑行", 1.0),
    "HKWorkoutActivityTypeRunning": ("跑步", 1.0),
    "HKWorkoutActivityTypeWalking": ("徒步", 1.0),
    "HKWorkoutActivityTypeHiking": ("徒步", 1.0),
    "HKWorkoutActivityTypeSwimming": ("游泳", 1.0),
    "HKWorkoutActivityTypeTraditionalStrengthTraining": ("健身", 1.0),
    "HKWorkoutActivityTypeFunctionalStrengthTraining": ("健身", 1.0),
    "HKWorkoutActivityTypeYoga": ("瑜伽", 1.0),
    "HKWorkoutActivityTypeRopeSkipping": ("跳绳", 1.0),
    "HKWorkoutActivityTypeRowing": ("划船", 1.0),
    "HKWorkoutActivityTypeElliptical": ("椭圆机", 1.0),
    "HKWorkoutActivityTypeStairClimbing": ("爬楼", 1.0),
}

# HKQuantityType 标识符
HK_TYPES = {
    "DistanceCycling": "distance_m",      # 骑行距离 (米)
    "DistanceWalkingRunning": "distance_m",  # 跑步/徒步距离
    "DistanceSwimming": "distance_m",     # 游泳距离
    "ActiveEnergyBurned": "calories",     # 消耗千卡
    "HeartRate": "heart_rate",            # 心率 (瞬时)
    "TimeInZone": "time_in_zone",         # 心率区间时间
    "AverageSpeed": "avg_speed_ms",       # 平均速度 (m/s)
    "MaxSpeed": "max_speed_ms",          # 最大速度
    "ActiveEnergy": "calories",
    "TotalEnergy": "calories",
    "BasalEnergyBurned": "basal_calories",
    "StepCount": "steps",
    "DistanceDownhillSnowSports": "distance_m",
    "WalkingSpeed": "speed_ms",
    "RunningSpeed": "speed_ms",
    "CyclingSpeed": "speed_ms",
    "CyclingPower": "power_w",
    "CyclingCadence": "cadence_rpm",
    "CyclingFunctionalThresholdPower": "ftp_w",
    "ElevationAscended": "ascent_m",     # 爬升
    "ElevationDescended": "descent_m",
    "StepCount": "steps",
    "HeartRateRecoveryOneMinute": "hr_recovery_1min",
    "VO2Max": "vo2max",
    "RestingHeartRate": "resting_hr",
}

# 心率区间（按最大心率百分比）
HEART_RATE_ZONES = {
    "warmup": (0, 0.6),
    "fat_burn": (0.6, 0.7),
    "cardio": (0.7, 0.8),
    "anaerobic": (0.8, 0.9),
    "max": (0.9, 1.1),
}


def parse_iso_duration(s: str) -> Optional[timedelta]:
    """解析 ISO 8601 duration: PT1H13M44S"""
    if not s:
        return None
    m = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", s)
    if not m:
        return None
    h, mi, se = m.groups()
    return timedelta(hours=int(h or 0), minutes=int(mi or 0), seconds=int(se or 0))


def parse_meta_data(xml_path: Path) -> Dict:
    """解析 export.xml 头部的元数据"""
    with open(xml_path, encoding="utf-8") as f:
        content = f.read(5000)
    m = re.search(r'<Me.*?localDate="([^"]*)"', content)
    m2 = re.search(r'<Me.*?localTime="([^"]*)"', content)
    return {
        "export_time": f"{m.group(1) if m else '?'} {m2.group(2) if m2 else '?'}",
        "source": "iPhone Health"
    }


def parse_health_xml(xml_path: Path) -> List[Dict]:
    """主解析函数：返回所有运动记录列表"""
    print(f"正在解析: {xml_path}")
    if not xml_path.exists():
        raise FileNotFoundError(f"文件不存在: {xml_path}")

    file_size_mb = xml_path.stat().st_size / 1024 / 1024
    print(f"文件大小: {file_size_mb:.1f} MB")

    # 解析
    tree = ET.parse(xml_path)
    root = tree.getroot()

    # Step 1: 找所有 Workout
    workouts = []
    for workout in root.findall("Workout"):
        act_type = workout.get("workoutActivityType", "")
        if act_type not in HK_WORKOUT_TYPES:
            continue

        act_name, _ = HK_WORKOUT_TYPES[act_type]
        duration_str = workout.get("duration", "")
        duration = parse_iso_duration(duration_str) or timedelta()
        duration_sec = duration.total_seconds()

        start_iso = workout.get("startDate", "")
        end_iso = workout.get("endDate", "")
        start_dt = parse_iso_datetime(start_iso)
        end_dt = parse_iso_datetime(end_iso)

        # Step 2: 找 Workout 内的 Statistics
        stats = {
            "distance_m": 0.0,
            "calories": 0,
            "ascent_m": 0,
            "avg_speed_ms": 0,
            "max_speed_ms": 0,
            "power_w": 0,
            "cadence": 0,
            "vo2max": 0,
            "resting_hr": 0,
            "energy_active": 0,
            "energy_total": 0,
        }
        for stat in workout.findall("WorkoutStatistics"):
            stype = stat.get("type", "")
            sunit = stat.get("unit", "")
            ssum = stat.get("sum", "0")
            savg = stat.get("average", "0")
            smin = stat.get("minimum", "0")
            smax = stat.get("maximum", "0")
            try:
                if "Distance" in stype and sunit == "m":
                    stats["distance_m"] = float(ssum or 0)
                elif "ActiveEnergyBurned" in stype and sunit == "kcal":
                    stats["calories"] = float(ssum or 0)
                elif "ActiveEnergy" in stype and sunit == "kcal":
                    stats["energy_active"] = float(ssum or 0)
                elif "TotalEnergy" in stype and sunit == "kcal":
                    stats["energy_total"] = float(ssum or 0)
                elif "AverageSpeed" in stype and sunit == "m/s":
                    stats["avg_speed_ms"] = float(savg or 0)
                elif "MaxSpeed" in stype and sunit == "m/s":
                    stats["max_speed_ms"] = float(smax or 0)
                elif "ElevationAscended" in stype and sunit == "m":
                    stats["ascent_m"] = float(ssum or 0)
                elif "VO2Max" in stype:
                    stats["vo2max"] = float(savg or 0)
                elif "RestingHeartRate" in stype:
                    stats["resting_hr"] = float(savg or 0)
                elif "CyclingPower" in stype and sunit == "W":
                    stats["power_w"] = float(savg or 0)
                elif "CyclingCadence" in stype and sunit == "rpm":
                    stats["cadence"] = float(savg or 0)
            except (ValueError, TypeError):
                pass

        # Step 3: 找 WorkoutRoute → 找 GPS 轨迹点
        route_points = []
        for route in workout.findall("WorkoutRoute"):
            for pt in route.findall("LocationMetadata/Location"):
                lat = float(pt.get("latitude", "0") or 0)
                lon = float(pt.get("longitude", "0") or 0)
                if lat and lon:
                    route_points.append({"lat": lat, "lon": lon})
            # 直接子节点的 FilePath
            for pt in route:
                if pt.tag.endswith("FilePath"):
                    pass  # GPX track

        # Step 4: 用 Route 时间戳确定活动配速（可选）
        # ...

        # 组装记录
        record = {
            "activity": act_name,
            "start_time": start_iso,
            "end_time": end_iso,
            "duration_sec": duration_sec,
            "start_dt": start_dt.isoformat() if start_dt else None,
            "end_dt": end_dt.isoformat() if end_dt else None,
            "distance_km": stats["distance_m"] / 1000 if stats["distance_m"] else 0,
            "calories": stats["calories"],
            "ascent_m": stats["ascent_m"],
            "avg_speed_kmh": stats["avg_speed_ms"] * 3.6 if stats["avg_speed_ms"] else 0,
            "max_speed_kmh": stats["max_speed_ms"] * 3.6 if stats["max_speed_ms"] else 0,
            "power_w": stats["power_w"],
            "cadence_rpm": stats["cadence"],
            "vo2max": stats["vo2max"],
            "resting_hr": stats["resting_hr"],
            "route_points": len(route_points),
            "source": "apple_health",
        }
        workouts.append(record)

    print(f"找到 {len(workouts)} 条运动记录")
    return workouts


def parse_iso_datetime(s: str) -> Optional[datetime]:
    """解析 ISO 8601 时间戳"""
    if not s:
        return None
    try:
        # 处理 '2026-08-04 22:02:00 +0800' 格式
        s = s.replace(" +", "+").replace(" -", "-")
        return datetime.fromisoformat(s)
    except Exception:
        # 去掉时区再试
        try:
            return datetime.fromisoformat(s.split(" +")[0].split(" -")[0])
        except Exception:
            return None


def filter_activities(workouts: List[Dict], activity: Optional[str] = None,
                       since: Optional[str] = None, until: Optional[str] = None) -> List[Dict]:
    """过滤记录"""
    result = []
    for w in workouts:
        if activity and w["activity"] != activity:
            continue
        if since:
            since_dt = parse_iso_datetime(since)
            if since_dt and w.get("start_dt") and w["start_dt"] < since_dt.isoformat():
                continue
        if until:
            until_dt = parse_iso_datetime(until)
            if until_dt and w.get("start_dt") and w["start_dt"] > until_dt.isoformat():
                continue
        result.append(w)
    return result


def main():
    import argparse
    p = argparse.ArgumentParser(description="Apple Health XML 解析器")
    p.add_argument("--file", required=True, help="export.xml 路径")
    p.add_argument("--activity", help="只显示某种运动 (骑行/跑步/...)")
    p.add_argument("--since", help="起始日期 (YYYY-MM-DD)")
    p.add_argument("--until", help="结束日期 (YYYY-MM-DD)")
    p.add_argument("--limit", type=int, default=10, help="最多显示 N 条")
    p.add_argument("--json", action="store_true", help="输出 JSON")
    p.add_argument("--stats", action="store_true", help="汇总统计")
    args = p.parse_args()

    meta = parse_meta_data(Path(args.file))
    workouts = parse_health_xml(Path(args.file))
    workouts = filter_activities(workouts, activity=args.activity,
                                 since=args.since, until=args.until)
    workouts.sort(key=lambda w: w.get("start_dt") or "", reverse=True)
    workouts = workouts[:args.limit]

    if args.stats:
        # 汇总
        total_dist = sum(w["distance_km"] for w in workouts)
        total_cal = sum(w["calories"] for w in workouts)
        total_time = sum(w["duration_sec"] for w in workouts)
        print(f"\n=== 汇总 ===")
        print(f"记录数: {len(workouts)}")
        print(f"总距离: {total_dist:.2f} km")
        print(f"总时间: {total_time / 3600:.1f} 小时")
        print(f"总消耗: {total_cal:.0f} kcal")
        print(f"导出时间: {meta['export_time']}")
    elif args.json:
        print(json.dumps({
            "meta": meta,
            "count": len(workouts),
            "workouts": workouts
        }, indent=2, ensure_ascii=False))
    else:
        print(f"\n=== {meta['export_time']} 导出 ===")
        for w in workouts:
            src = w["start_dt"]
            dur = f"{int(w['duration_sec'] // 3600)}h{int((w['duration_sec'] % 3600) // 60)}m"
            dist = f"{w['distance_km']:.2f} km" if w["distance_km"] else "-"
            avg = f"{w['avg_speed_kmh']:.1f} km/h" if w["avg_speed_kmh"] else "-"
            asc = f" ⛰{w['ascent_m']:.0f}m" if w["ascent_m"] else ""
            cal = f" {w['calories']:.0f}kcal" if w["calories"] else ""
            print(f"  {src} | {w['activity']:<5} | {dur:>5} | {dist:>8} | {avg:>10}{asc}{cal}")


if __name__ == "__main__":
    main()
