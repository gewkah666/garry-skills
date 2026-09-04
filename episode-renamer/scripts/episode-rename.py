#!/usr/bin/env python3
"""
episode-rename.py - 为视频文件名注入 S##E## 标记（保留原文件名）

用法:
  episode-rename.py /path/to/anime --dry-run
  episode-rename.py /path/to/anime
  episode-rename.py /path/to/anime --undo
  episode-rename.py /path/to/anime --mode prefix
"""
import argparse
import json
import re
import shutil
import sys
from pathlib import Path

VIDEO_EXT = {".mp4", ".mkv", ".avi", ".ts", ".mov", ".wmv", ".flv", ".webm"}

# 多种季/集识别模式
PATTERNS = [
    # 双重编号 [01_73] → 第4季01 (73-72)
    (re.compile(r"\[(\d{1,3})_(\d{1,3})\]"), "double"),
    # [S02][05] 或 [S02E05]
    (re.compile(r"\[S(\d{1,2})(?:E(\d{1,3}))?\]", re.IGNORECASE), "sn"),
    # S02E05 不带括号
    (re.compile(r"\bS(\d{1,2})E(\d{1,3})\b", re.IGNORECASE), "sn_inline"),
    # 第N话 / EP N / EP0N
    (re.compile(r"\[(?:EP|第|E)?\s*0?(\d{1,3})\s*(?:END|話|话)?\]", re.IGNORECASE), "ep_only"),
    # [01v2] / [01_02] 简版
    (re.compile(r"\[(\d{1,3})\]"), "simple"),
]


def parse_episode(filename: str, parent_dir: Path) -> dict:
    """从文件名+父目录推断 (season, episode)。返回 None 表示无法识别。"""
    # 1. [NN_MM] 双编号模式 (最准确)
    for pat, ptype in PATTERNS:
        m = pat.search(filename)
        if m and ptype == "double":
            season_local = int(m.group(1))  # 第几季 (1-based)
            ep_total = int(m.group(2))  # 全剧累计集数
            # 季数 = ep_total // (每季约 24 集) 或更精确的: 季数 = season_local
            # 这里取 season_local 作为季内编号 + (ep_total // 24) 作为季数偏移
            season_offset = max(1, (ep_total - season_local) // 24 + 1)
            # 但若文件名有 S4 标识,以 S4 为准
            return {"season": season_offset, "episode": season_local,
                    "total_ep": ep_total, "source": "double"}

    # 2. [S02E05] 或 [S02]
    for pat, ptype in PATTERNS:
        m = pat.search(filename)
        if m and ptype == "sn":
            season = int(m.group(1))
            episode = int(m.group(2)) if m.group(2) else None
            return {"season": season, "episode": episode,
                    "total_ep": None, "source": "sn_bracket"}

    # 3. S##E## inline
    for pat, ptype in PATTERNS:
        m = pat.search(filename)
        if m and ptype == "sn_inline":
            return {"season": int(m.group(1)), "episode": int(m.group(2)),
                    "total_ep": None, "source": "sn_inline"}

    # 4. [EP01] / [第12话] 等单集编号
    for pat, ptype in PATTERNS:
        m = pat.search(filename)
        if m and ptype == "ep_only":
            ep = int(m.group(1))
            # 从父目录名推断季数
            season = infer_season_from_dir(parent_dir)
            return {"season": season, "episode": ep,
                    "total_ep": None, "source": "ep_only"}

    # 5. [NN] 简单编号
    for pat, ptype in PATTERNS:
        m = pat.search(filename)
        if m and ptype == "simple":
            # 可能是季数或集数
            n = int(m.group(1))
            if n <= 30:  # 假设是集数
                season = infer_season_from_dir(parent_dir)
                return {"season": season, "episode": n,
                        "total_ep": None, "source": "simple"}
            else:  # 假设是累计集数
                season_offset = max(1, (n - 1) // 24 + 1)
                return {"season": season_offset, "episode": 1,
                        "total_ep": n, "source": "simple_total"}

    return None


def infer_season_from_dir(parent_dir: Path) -> int:
    """从父目录名推断季数,如 S4/ S04/ Season4/"""
    name = parent_dir.name
    m = re.search(r"[Ss](\d{1,2})", name)
    if m:
        return int(m.group(1))
    return 1


def already_has_marker(filename: str) -> bool:
    """检查是否已含完整的 S##E## 标记 (而非仅 S##)"""
    return bool(re.search(r"\bS\d{1,2}E\d{1,3}\b", filename, re.IGNORECASE))


def inject_marker(filename: str, season: int, episode: int, mode: str = "after-S") -> str:
    """在文件名中插入 [S##E##] 标记"""
    if episode is None:
        marker = f"S{season:02d}"
    else:
        marker = f"S{season:02d}E{episode:02d}"

    if mode == "prefix":
        # 在文件名最开头插入
        bracket_marker = f"[{marker}]"
        # 保留原扩展名
        m = re.match(r"^(.*?)(\[.*?\])", filename)
        if m:
            # 找到第一个 [ 后插入
            return f"[{marker}]{filename}"
        return f"[{marker}] {filename}"

    # 默认: 在 S## 标识后插入
    bracket_marker = f"[{marker}]"
    # 匹配 [Title S4] 模式
    m = re.search(r"(\[.*?\bS\d{1,2}\b.*?\])", filename, re.IGNORECASE)
    if m:
        return filename.replace(m.group(1), m.group(1) + bracket_marker, 1)
    # 否则插在第一个 ] 后
    return f"{bracket_marker}{filename}"


def process_dir(dir_path: Path, mode: str = "after-S", force: bool = False) -> list:
    """扫描目录,返回 (old_path, new_path) 列表

    注: SMB 挂载的 NAS 文件可能 is_file() 返回 False,此处仅依赖扩展名判断。
    """
    results = []
    for f in sorted(dir_path.iterdir()):
        # SMB 挂载的 NAS 文件可能 is_file() 异常,改用扩展名判断
        if f.suffix.lower() not in VIDEO_EXT:
            continue
        name = f.name
        has = already_has_marker(name)
        if not force and has:
            continue
        info = parse_episode(name, dir_path)
        if not info:
            continue
        new_name = inject_marker(name, info["season"], info["episode"], mode)
        if new_name == name:
            continue
        new_path = f.with_name(new_name)
        results.append((f, new_path, info))
    return results


def save_mapping(dir_path: Path, mappings: list):
    """保存改名映射用于 undo"""
    map_file = dir_path / ".episode-rename-map.json"
    data = []
    for old, new, info in mappings:
        data.append({
            "old": old.name,
            "new": new.name,
            "info": info,
        })
    map_file.write_text(json.dumps(data, ensure_ascii=False, indent=2))
    return map_file


def undo(dir_path: Path) -> int:
    """根据映射还原"""
    map_file = dir_path / ".episode-rename-map.json"
    if not map_file.exists():
        print(f"未找到映射文件: {map_file}")
        return 0
    data = json.loads(map_file.read_text())
    count = 0
    for entry in data:
        new_path = dir_path / entry["new"]
        old_path = dir_path / entry["old"]
        if new_path.exists():
            shutil.move(str(new_path), str(old_path))
            print(f"  {entry['new'][:60]}...")
            print(f"  → {entry['old'][:60]}...")
            count += 1
        else:
            print(f"  ⚠️  找不到: {entry['new']}")
    map_file.unlink()
    return count


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dir", help="目标目录")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--mode", choices=["after-S", "prefix"], default="after-S",
                    help="插入位置: after-S (在 S## 标识后) / prefix (开头)")
    ap.add_argument("--force", action="store_true", help="对已含标记的文件也强制改名")
    ap.add_argument("--undo", action="store_true", help="还原上次改名")
    ap.add_argument("--yes", "-y", action="store_true", help="跳过确认直接执行")
    args = ap.parse_args()

    target = Path(args.dir).expanduser().resolve()
    if not target.is_dir():
        sys.exit(f"目录不存在: {target}")

    if args.undo:
        n = undo(target)
        print(f"✓ 还原 {n} 个文件")
        return

    mappings = process_dir(target, mode=args.mode, force=args.force)
    if not mappings:
        print("无可改名的文件 (全部已含 S##E## 标记或无法识别)")
        return

    # 打印预览
    print(f"将改名 {len(mappings)} 个文件:\n")
    for old, new, info in mappings:
        ep = info.get('episode')
        ep_str = f"{ep:02d}" if ep else "??"
        print(f"  {old.name[:70]}")
        print(f"    → {new.name[:70]}")
        print(f"    (S{info['season']:02d}E{ep_str}, 来源: {info['source']})")
        print()

    if args.dry_run:
        print("=== Dry-run 模式,未实际改名 ===")
        print(f"加 --force 跳过已含标记文件(无此项无需)")
        return

    # 确认执行（非 dry-run 且有 --yes 时跳过）
    if not args.dry_run:
        if args.yes:
            print("\n[自动执行 - --yes]")
        else:
            resp = input("\n确认执行? (y/N) ").strip().lower()
            if resp != "y":
                print("取消")
                return

    count = 0
    for old, new, _info in mappings:
        if new.exists():
            print(f"  ⚠️  目标已存在,跳过: {new.name}")
            continue
        shutil.move(str(old), str(new))
        count += 1
    save_mapping(target, mappings)
    print(f"\n✓ 改名 {count} 个文件")
    print(f"映射已保存: {target}/.episode-rename-map.json (可用 --undo 还原)")


if __name__ == "__main__":
    main()