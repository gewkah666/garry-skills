#!/usr/bin/env python3
"""
estimate_torrent_size.py - 从种子文件预估体积

用法:
  python estimate_torrent_size.py <torrent_file> [<torrent_file>...]
"""
import sys
sys.path.insert(0, '/Users/garry/.hermes/skills/anime-tracker')


def bdecode(data, idx=0):
    if data[idx:idx+1] == b'i':
        end = data.index(b'e', idx)
        return int(data[idx+1:end]), end + 1
    if data[idx:idx+1] == b'l':
        idx += 1
        result = []
        while data[idx:idx+1] != b'e':
            v, idx = bdecode(data, idx)
            result.append(v)
        return result, idx + 1
    if data[idx:idx+1].isdigit():
        colon = data.index(b':', idx)
        length = int(data[idx:colon])
        return data[colon+1:colon+1+length], colon + 1 + length
    if data[idx:idx+1] == b'd':
        idx += 1
        result = {}
        while data[idx:idx+1] != b'e':
            k, idx = bdecode(data, idx)
            v, idx = bdecode(data, idx)
            result[k] = v
        return result, idx + 1


def analyze_torrent(torrent_path: str) -> dict:
    """分析种子文件，返回关键信息（含体积预估）。"""
    try:
        with open(torrent_path, 'rb') as f:
            data = f.read()
    except Exception as e:
        return {"error": f"读取失败: {e}"}

    try:
        info, _ = bdecode(data)
    except Exception as e:
        return {"error": f"bdecode 失败: {e}"}

    # 兼容两种结构: 顶层是 info 或顶层 dict 含 info
    if isinstance(info, dict) and b'info' in info:
        info_dict = info[b'info']
    else:
        info_dict = info

    # 提取名字
    name_bytes = info_dict.get(b'name', b'?')
    name = name_bytes.decode('utf-8', errors='replace') if isinstance(name_bytes, bytes) else str(name_bytes)

    # 单文件模式
    if b'length' in info_dict:
        total_size = info_dict[b'length']
        file_count = 1
        is_dir = False
    # 多文件模式
    elif b'files' in info_dict:
        files = info_dict[b'files']
        total_size = sum(f[b'length'] for f in files)
        file_count = len(files)
        is_dir = True
    else:
        return {"error": "无法识别种子结构"}

    # 启发式: 分辨率/编码/来源
    name_lower = name.lower()
    resolution = "?"
    if "2160p" in name_lower or "4k" in name_lower or "uhd" in name_lower:
        resolution = "2160p"
    elif "1440p" in name_lower:
        resolution = "1440p"
    elif "1080p" in name_lower or "1920x1080" in name_lower or "1920×1080" in name_lower:
        resolution = "1080p"
    elif "720p" in name_lower or "1280x720" in name_lower:
        resolution = "720p"
    elif "480p" in name_lower:
        resolution = "480p"

    codec = "?"
    if "hevc" in name_lower or "h265" in name_lower or "x265" in name_lower:
        codec = "HEVC"
    elif "x264" in name_lower or "h264" in name_lower:
        codec = "x264"
    elif "av1" in name_lower:
        codec = "AV1"

    source = "?"
    if "webrip" in name_lower or "web-dl" in name_lower:
        source = "WEB"
    elif "bdrip" in name_lower or "bluray" in name_lower:
        source = "BD"
    elif "dvdrip" in name_lower:
        source = "DVD"
    elif "raw" in name_lower and "bd" in name_lower:
        source = "BD-raw"

    # 季度标记 (用于识别是合集还是单季)
    season_marker = "?"
    if re.search(r"S\d{1,2}E\d{1,3}", name, re.IGNORECASE):
        season_marker = "ongoing(单集)"
    elif re.search(r"S\d{1,2}-S\d{1,2}", name, re.IGNORECASE):
        season_marker = "multi-season合集"
    elif re.search(r"S\d{1,2}", name, re.IGNORECASE):
        season_marker = "seasonal"
    elif "complete" in name_lower or "fin" in name_lower:
        season_marker = "complete"
    elif re.search(r"全\s*\d+集", name):
        season_marker = "complete"
    elif re.search(r"\d{1,3}-\d{1,3}", name):
        season_marker = "batch"

    return {
        "name": name,
        "size_gb": round(total_size / 1024 / 1024 / 1024, 2),
        "size_bytes": total_size,
        "file_count": file_count,
        "is_dir": is_dir,
        "resolution": resolution,
        "codec": codec,
        "source": source,
        "season": season_marker,
    }


import re


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法: python estimate_torrent_size.py <torrent_file>...")
        sys.exit(1)

    for path in sys.argv[1:]:
        result = analyze_torrent(path)
        print(f"\n=== {path.split('/')[-1]} ===")
        if "error" in result:
            print(f"  ERROR: {result['error']}")
            continue
        for k, v in result.items():
            if k == "name":
                print(f"  name: {v[:80]}")
            elif k == "size_bytes":
                continue
            else:
                print(f"  {k}: {v}")