"""Apple Health XML 自动同步工具
检测 ~/Downloads 中的 apple_health_export.zip，解压并写入 Notion。
逐条记录跟踪，支持增量同步（不重复导入）。
"""
import json
import os
import re
import sys
import shutil
import urllib.request
import zipfile
import time
import subprocess
import tempfile
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional

sys.path.insert(0, str(Path(__file__).parent))
from config import Config
from apple_health import parse_health_xml, parse_meta_data, filter_activities
from ride_log import log_to_notion


# === 路径 ===
DOWNLOADS_DIR = Path.home() / "Downloads"
EXTRACT_DIR = Path.home() / ".health_export_cache"
STATE_FILE = Path.home() / ".hermes/ride-notion/state.json"
HERMES_BIN = Path.home() / "Library/Application Support/cn.org.hermesagent.desktop/runtime/desktop-bin/hermes"

# === 状态 ===
def load_state() -> dict:
    """加载同步状态：跟踪已写入的工作 ID"""
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    if not STATE_FILE.exists():
        return {"processed": {}, "last_sync": None}
    try:
        return json.loads(STATE_FILE.read_text())
    except Exception:
        return {"processed": {}, "last_sync": None}


def save_state(state: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False))


def gen_workout_id(workout: Dict) -> str:
    """生成唯一的运动记录 ID（用于去重）"""
    return f"{workout['activity']}|{workout['start_dt']}|{workout['duration_sec']}"


# === 工具 ===
def find_zip_export() -> Optional[Path]:
    """在 Downloads 找最近的 apple_health_export*.zip"""
    if not DOWNLOADS_DIR.exists():
        return None
    candidates = list(DOWNLOADS_DIR.glob("apple_health_export*.zip"))
    if not candidates:
        return None
    # 最新一份
    candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return candidates[0]


def extract_zip(zip_path: Path) -> Path:
    """解压到 cache 目录，返回 export.xml 路径"""
    EXTRACT_DIR.mkdir(parents=True, exist_ok=True)

    # 用 zip 文件 mtime + size 作为 cache key
    cache_key = f"{zip_path.stat().st_size}_{int(zip_path.stat().st_mtime)}"
    cache_subdir = EXTRACT_DIR / cache_key
    xml_path = cache_subdir / "apple_health_export" / "export.xml"

    if xml_path.exists():
        print(f"使用缓存: {xml_path}")
        return xml_path

    print(f"解压: {zip_path} → {cache_subdir}")
    cache_subdir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(cache_subdir)
    return xml_path


def send_feishu_notify(message: str) -> bool:
    """友好通知"""
    try:
        result = subprocess.run(
            [str(HERMES_BIN), "send", "-t", "feishu", message],
            capture_output=True, text=True, timeout=15
        )
        return result.returncode == 0
    except Exception as e:
        print(f"飞书通知失败: {e}")
        return False


# === 同步核心 ===
def sync_to_notion(workouts: List[Dict], activity_filter: Optional[str] = None,
                  since: Optional[str] = None, dry_run: bool = False,
                  min_duration_min: int = 5) -> Dict:
    """同步运动数据到 Notion

    - 增量同步：跳过已写入的（同 start_time + duration）
    - 最小时长过滤：太短的活动忽略（< 5 min）
    - 活动过滤：可只导入骑行/跑步
    """
    state = load_state()
    processed = state.get("processed", {})

    # 过滤
    workouts = filter_activities(workouts, activity=activity_filter, since=since)
    workouts = [w for w in workouts if w["duration_sec"] >= min_duration_min * 60]

    new_count = 0
    skip_count = 0
    error_count = 0
    new_records = []

    for w in workouts:
        wid = gen_workout_id(w)
        if wid in processed:
            skip_count += 1
            continue

        if dry_run:
            new_count += 1
            print(f"  [DRY] {w['activity']} {w['start_dt']} {w['distance_km']:.2f}km")
            continue

        # 写入 Notion
        result = log_to_notion(
            activity=w["activity"],
            distance_km=w["distance_km"],
            duration=str(int(w["duration_sec"])),
            avg_speed=w["avg_speed_kmh"],
            avg_hr=0,  # Apple Health stats 没单独算 average
            calories=w["calories"],
            elevation=int(w["ascent_m"]),
            location="",
            start_time=w["start_dt"],
            end_time=w["end_time"],
            segments=[],
            note=f"from Apple Health | {w['distance_km']:.2f}km in {int(w['duration_sec']//60)}min"
        )

        if result.get("status") == "ok":
            processed[wid] = {
                "page_id": result["page_id"],
                "written_at": datetime.now().isoformat(),
                "title": result["title"]
            }
            new_count += 1
            new_records.append(w)
            print(f"  ✓ {w['activity']} {w['start_dt']} {w['distance_km']:.2f}km")
        else:
            error_count += 1
            print(f"  ✗ {w['activity']} {w['start_dt']}: {result.get('error', '?')}")

    # 保存状态
    if not dry_run and new_count > 0:
        state["processed"] = processed
        state["last_sync"] = datetime.now().isoformat()
        save_state(state)

    return {
        "new_written": new_count,
        "skipped_duplicate": skip_count,
        "errors": error_count,
        "total_scanned": len(workouts),
        "new_records": new_records
    }


def process_export(xml_path: Path, dry_run: bool = False,
                   activity_filter: Optional[str] = None,
                   since: Optional[str] = None,
                   notify: bool = True) -> Dict:
    """处理一份 export.xml"""
    if not xml_path.exists():
        return {"status": "error", "message": f"找不到 {xml_path}"}

    # 解析
    meta = parse_meta_data(xml_path)
    workouts = parse_health_xml(xml_path)

    # 同步
    result = sync_to_notion(workouts, activity_filter=activity_filter,
                             since=since, dry_run=dry_run)

    # 通知
    if notify and not dry_run and result["new_written"] > 0:
        msg = (
            f"🏃 运动记录已同步到 Notion\n"
            f"• 新增: {result['new_written']} 条\n"
            f"• 跳过重复: {result['skipped_duplicate']} 条\n"
            f"• 扫描: {result['total_scanned']} 条\n"
            f"• 来源: Apple Health {meta['export_time']}"
        )
        send_feishu_notify(msg)

    return {
        "status": "ok",
        "meta": meta,
        **result
    }


def watch_mode(check_interval_sec: int = 60):
    """watch 模式：定期检查 Downloads 找新导出"""
    print(f"开始监控 {DOWNLOADS_DIR}，每 {check_interval_sec} 秒检查")
    seen_zips = set()
    while True:
        try:
            zip_path = find_zip_export()
            if zip_path and zip_path not in seen_zips:
                seen_zips.add(zip_path)
                print(f"发现新导出: {zip_path}")
                xml_path = extract_zip(zip_path)
                process_export(xml_path, dry_run=False, notify=True)
                print(f"等待下次导出...")
        except KeyboardInterrupt:
            break
        except Exception as e:
            print(f"错误: {e}")
        time.sleep(check_interval_sec)


def main():
    import argparse
    p = argparse.ArgumentParser(description="Apple Health 自动同步到 Notion")
    p.add_argument("--file", help="解压后的 export.xml 路径")
    p.add_argument("--zip", help="Apple Health 导出 zip 路径")
    p.add_argument("--activity", help="只导入指定运动 (骑行/跑步/...)")
    p.add_argument("--since", help="起始日期 YYYY-MM-DD")
    p.add_argument("--min-duration", type=int, default=5, help="最短时长（分钟）")
    p.add_argument("--dry-run", action="store_true", help="只看不写")
    p.add_argument("--watch", action="store_true", help="持续监控模式")
    p.add_argument("--interval", type=int, default=60, help="watch 检查间隔（秒）")
    p.add_argument("--no-notify", action="store_true", help="不发飞书通知")
    p.add_argument("--json", action="store_true", help="JSON 输出")
    args = p.parse_args()

    if args.watch:
        watch_mode(args.interval)
        return

    # 找 zip
    xml_path = None
    if args.file:
        xml_path = Path(args.file)
    elif args.zip:
        xml_path = extract_zip(Path(args.zip))
    else:
        # 自动找 Downloads 最新的
        zip_path = find_zip_export()
        if zip_path:
            print(f"自动找到最新导出: {zip_path}")
            xml_path = extract_zip(zip_path)
        else:
            print(f"ERROR: Downloads 目录没有 apple_health_export*.zip")
            print("请先 iPhone → 健康 App → 头像 → 导出所有健康数据")
            sys.exit(1)

    # 处理
    result = process_export(
        xml_path,
        dry_run=args.dry_run,
        activity_filter=args.activity,
        since=args.since,
        notify=not args.no_notify
    )

    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False, default=str))
    else:
        if result.get("status") == "ok":
            print(f"\n✓ 同步完成")
            print(f"  新增: {result['new_written']} 条")
            print(f"  跳过重复: {result['skipped_duplicate']} 条")
            print(f"  错误: {result['errors']} 条")
            print(f"  扫描: {result['total_scanned']} 条")
        else:
            print(f"✗ 失败: {result.get('message', '?')}")


if __name__ == "__main__":
    main()
