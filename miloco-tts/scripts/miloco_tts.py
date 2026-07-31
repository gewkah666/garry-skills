#!/usr/bin/env python3
"""
miloco TTS 智能路由
- 解析消息中的"哪个设备"（总管 Play/mini、bookmini、电视等）
- 解析消息中的"播放/朗读"
- 自动选择设备和音量
- 调用 miloco TTS action

支持的设备名关键词：
- 总管 / mini / 书房音箱 / 卧室音箱 → 总管 mini / Play
- 客厅 / 电视 / 泰乐福 → 电视
- 米家 → 失败（无 TTS）
- 喇叭 / 音箱 → 总管 mini（默认）

支持的指令：
- 朗读/读/说/播报/播放/TTS → 播放文本
- 播放音乐/电台/列表 → 走 play-music（如果支持）
"""

import argparse
import json
import re
import subprocess
import sys
from typing import Optional, Dict, List, Tuple

MILOCO_CLI = "/Users/garry/.local/bin/miloco-cli"
TOKEN = "10ef1a3b-85e1-4645-ae28-95d2f96e92ca"
MILOCO_BASE = "http://127.0.0.1:1810/api"

# 设备别名映射
DEVICE_ALIASES = {
    # 总管 mini（书房）
    "总管mini": "865912910",
    "mini": "865912910",
    "书房音箱": "865912910",
    "书房喇叭": "865912910",

    # 总管 Play（卧室）
    "总管play": "423919135",
    "总管": "423919135",  # 单独说"总管"默认是 Play
    "卧室音箱": "423919135",
    "卧室喇叭": "423919135",

    # 电视（客厅）
    "电视": "802414229",
    "泰乐福": "802414229",
    "客厅电视": "802414229",
    "客厅屏": "802414229",
}

# 默认音量
DEFAULT_VOLUME = 50


def get_device_info(did: str) -> Optional[Dict]:
    """获取设备信息"""
    import urllib.request
    url = f"{MILOCO_BASE}/miot/devices/{did}/spec"
    req = urllib.request.Request(url)
    req.add_header("Authorization", f"Bearer {TOKEN}")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
            return data.get("data", {})
    except Exception as e:
        print(f"获取设备信息失败: {e}")
        return None


def list_all_audio_devices() -> Dict[str, Dict]:
    """列出所有可播放音频的设备（含音箱、电视）"""
    import urllib.request
    url = f"{MILOCO_BASE}/miot/home"
    req = urllib.request.Request(url)
    req.add_header("Authorization", f"Bearer {TOKEN}")
    devices = {}
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read()).get("data", {})
            for dev in data.get("devices", []):
                name = dev.get("name", "")
                model = dev.get("model", "")
                did = dev.get("did", "")
                if (
                    "speaker" in model.lower()
                    or "tv" in model.lower()
                    or "mitv" in model.lower()
                    or "音箱" in name
                    or "总管" in name
                    or "电视" in name
                ):
                    devices[name] = {"did": did, "model": model, "name": name, "room": dev.get("room", "")}
    except Exception as e:
        print(f"列出设备失败: {e}")
    return devices


def resolve_device(text: str) -> Optional[Tuple[str, str]]:
    """
    从文本中识别设备
    返回 (did, name) 或 None
    """
    text_lower = text.lower()

    # 1. 先匹配别名（长别名优先）
    sorted_aliases = sorted(DEVICE_ALIASES.items(), key=lambda x: -len(x[0]))
    for alias, did in sorted_aliases:
        if alias.lower() in text_lower:
            # 找到设备真实名
            spec = get_device_info(did)
            real_name = spec.get("name", alias)
            return (did, real_name)

    # 2. 没匹配到，列出所有音箱让用户选
    devices = list_all_audio_devices()
    if devices:
        # 返回书房 mini（如果存在）
        for name, dev in devices.items():
            if "mini" in name.lower():
                return (dev["did"], name)
        # 否则返回第一个
        first = list(devices.values())[0]
        return (first["did"], first["name"])

    return None


def parse_volume(text: str) -> int:
    """从文本中解析音量"""
    m = re.search(r"音量\s*(\d+)", text)
    if m:
        return max(0, min(100, int(m.group(1))))
    m = re.search(r"(\d+)\s*%", text)
    if m:
        return max(0, min(100, int(m.group(1))))
    return DEFAULT_VOLUME


def clean_text(text: str, extra_aliases: List[str] = None) -> Tuple[str, int]:
    """
    清理文本，提取要朗读的内容和音量
    """
    # 1. 找音量
    volume = parse_volume(text)

    # 2. 提取要朗读的文本（去掉所有设备名 + 动作词 + 音量指令）
    tts_text = text
    # 先去掉所有设备别名（长别名优先）
    aliases = list(DEVICE_ALIASES.keys())
    if extra_aliases:
        aliases.extend(extra_aliases)
    for alias in sorted(set(aliases), key=lambda x: -len(x)):
        tts_text = re.sub(re.escape(alias), "", tts_text, flags=re.IGNORECASE)
    # 去掉"让 X 说/读/播放"格式
    tts_text = re.sub(r"让\s*[^说读播放播报朗读]{0,5}\s*(说|读|播放|播报|朗读)", "", tts_text)
    # 去掉"对 X 说"格式
    tts_text = re.sub(r"对\s*[^说]{0,3}\s*说", "", tts_text)
    # 去掉动作词
    tts_text = re.sub(r"^(朗读|读|说|播放|播报|说一声)", "", tts_text, flags=re.IGNORECASE)
    tts_text = re.sub(r"^(朗读|读|说|播放|播报|说一声)", "", tts_text, flags=re.IGNORECASE)
    tts_text = re.sub(r"(朗读|播放|播报|TTS)", "", tts_text, flags=re.IGNORECASE)
    # 去掉"让"和"对"残留
    tts_text = re.sub(r"^(让|对|给|到|往)\s*", "", tts_text)
    # 去掉音量指令
    tts_text = re.sub(r"音量\s*\d+", "", tts_text)
    tts_text = re.sub(r"\d+\s*%", "", tts_text)
    # 整理空白
    tts_text = re.sub(r"\s+", " ", tts_text).strip(" ，,。.?？!！:：")

    if not tts_text:
        tts_text = "请提供要朗读的内容"

    return tts_text, volume


def parse_message(text: str) -> Tuple[str, str, int]:
    """
    解析消息
    返回 (device_did, tts_text, volume)
    """
    # 1. 找设备（先匹配长别名）
    device = resolve_device(text)
    if not device:
        raise RuntimeError("找不到可播放的设备（书房总管 mini / 卧室总管 Play / 电视）")

    # 2-3. 清理文本
    tts_text, volume = clean_text(text)

    return (device[0], tts_text, volume)


def control_volume(did: str, volume: int) -> bool:
    """设置音量"""
    try:
        result = subprocess.run(
            [MILOCO_CLI, "device", "control", did, "volume", str(volume)],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0:
            print(f"✓ 音量设为 {volume}%")
            return True
        else:
            print(f"音量设置失败: {result.stderr}")
            return False
    except Exception as e:
        print(f"音量异常: {e}")
        return False


def play_tts(did: str, text: str) -> bool:
    """播放 TTS"""
    try:
        # 电视用 post（message-router），其他音箱用 play-text
        action = "post" if did == "802414229" else "play-text"
        result = subprocess.run(
            [MILOCO_CLI, "device", "action", did, action, text],
            capture_output=True, text=True, timeout=15
        )
        if result.returncode == 0:
            data = json.loads(result.stdout)
            if data.get("code") == 0:
                print(f"✓ 播放成功 ({action}): {text[:50]}")
                return True
        print(f"播放失败: {result.stderr or result.stdout}")
        return False
    except Exception as e:
        print(f"播放异常: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(description="miloco 智能 TTS 播放")
    parser.add_argument("text", nargs="+", help="要朗读的内容（可包含设备名）")
    parser.add_argument("--list", action="store_true", help="列出可播放的设备")
    parser.add_argument("--device", help="指定设备名或 DID")
    parser.add_argument("--volume", type=int, help="音量 0-100")
    args = parser.parse_args()

    if args.list:
        print("可播放的设备：")
        for name, dev in list_all_audio_devices().items():
            print(f"  - {name} (DID: {dev['did']}, 房间: {dev.get('room', '?')})")
        sys.exit(0)

    if args.device:
        text = " ".join(args.text)
        if args.device.startswith("did:") or len(args.device) > 8 and args.device.isdigit():
            did = args.device
            real_name = get_device_info(did).get("name", did)
        else:
            # 当别名查
            found = DEVICE_ALIASES.get(args.device)
            if found:
                did = found
                real_name = args.device
            else:
                print(f"未知设备: {args.device}")
                return
        # 走相同的清理流程
        tts_text, volume = clean_text(text, [args.device])
        volume = args.volume or volume
    else:
        text = " ".join(args.text)
        did, tts_text, volume = parse_message(text)
        # 设备真实名（用于显示）
        try:
            real_name = get_device_info(did).get("name", did)
        except:
            real_name = did
        volume = args.volume or volume

    if not tts_text:
        tts_text = "请提供要朗读的内容"

    print(f"目标设备: {real_name} (DID: {did})")
    print(f"朗读内容: {tts_text}")
    print(f"音量: {volume}%")
    print()

    control_volume(did, volume)
    play_tts(did, tts_text)


if __name__ == "__main__":
    main()
