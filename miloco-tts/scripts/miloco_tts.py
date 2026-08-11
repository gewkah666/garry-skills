#!/usr/bin/env python3
"""
智能 TTS 路由(Home Assistant 版)
- 解析消息中的"哪个设备"(总管 Play/mini、电视等)
- 解析消息中的"播放/朗读"文本和音量
- 通过 Home Assistant REST API 让设备朗读

后端:Home Assistant(不再依赖 miloco-cli,Windows/macOS 通用)
- 配置:环境变量 HASS_URL(默认 http://192.168.31.149:8123)+ HASS_TOKEN(必填,
  HA 长期访问令牌;也接受 HA_URL / HA_TOKEN)
- 设备 entity 自动发现:按好友名/entity_id 关键词从 /api/states 匹配,无需写死 entity_id
- TTS 通道(按顺序尝试):
  1. 官方小米米家集成(xiaomi_home)的"播放文本"text 实体 → text.set_value
  2. xiaomi_miot(al-one)集成 → xiaomi_miot.intelligent_speaker 服务
- 音量:media_player.volume_set,退回含"音量/volume"的 number 实体

用法:
  python miloco_tts.py "对书房说 该休息了"
  python miloco_tts.py "电视播报 快递到了"
  python miloco_tts.py "对卧室说 晚安 音量30"
  python miloco_tts.py --list          # 列出发现的候选实体(调试用)
"""

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from typing import Dict, List, Optional, Tuple

def _load_token() -> Optional[str]:
    """token 读取顺序:环境变量 → Windows 用户级注册表 → ~/.hass_token 文件。

    注册表兜底是因为 Windows 用户级环境变量只对设置之后新启动的进程生效,
    长驻会话(编辑器/agent)里的子进程继承的是旧环境。
    """
    token = os.environ.get("HASS_TOKEN") or os.environ.get("HA_TOKEN")
    if token:
        return token
    if sys.platform == "win32":
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as k:
                for name in ("HASS_TOKEN", "HA_TOKEN"):
                    try:
                        return winreg.QueryValueEx(k, name)[0]
                    except FileNotFoundError:
                        pass
        except OSError:
            pass
    token_file = os.path.expanduser("~/.hass_token")
    if os.path.isfile(token_file):
        with open(token_file, encoding="utf-8") as f:
            return f.read().strip() or None
    return None


HASS_URL = (os.environ.get("HASS_URL") or os.environ.get("HA_URL")
            or "http://192.168.31.149:8123").rstrip("/")
HASS_TOKEN = _load_token()

# 逻辑设备表:match 里的关键词用于在 HA 实体的 entity_id / friendly_name 中匹配
DEVICES = {
    "mini": {"name": "总管mini", "room": "书房",
             "match": ["总管mini", "zong_guan_mini", "zongguan_mini"]},
    "play": {"name": "总管Play", "room": "卧室",
             "match": ["总管play", "zong_guan_play", "zongguan_play"]},
    "tv":   {"name": "泰乐福(电视)", "room": "客厅",
             "match": ["泰乐福", "tai_le_fu", "tailefu", "mitv", "mih1"]},
}

# 文本别名 → 逻辑设备(长别名优先匹配)
DEVICE_ALIASES = {
    "总管mini": "mini",
    "mini": "mini",
    "书房音箱": "mini",
    "书房喇叭": "mini",
    "书房": "mini",

    "总管play": "play",
    "总管": "play",  # 单独说"总管"默认是 Play
    "卧室音箱": "play",
    "卧室喇叭": "play",
    "卧室": "play",

    "电视": "tv",
    "泰乐福": "tv",
    "客厅电视": "tv",
    "客厅屏": "tv",
    "客厅": "tv",

    "手表": "watch",
    "腕表": "watch",
    "手机": "phone",
    "耳机": "phone",
    "蓝牙耳机": "phone",
}

# 走 notify.mobile_app_* 服务的随身设备(需手机安装 HA Companion 并登录本 HA)。
# watch: 普通通知 → 手机 → 小米运动健康镜像到手表(文字+震动,Color 2 无语音通路)
# phone: message="TTS" 让手机本地合成并播放语音(连着蓝牙耳机/眼镜时自动走蓝牙)
MOBILE_MODES = {
    "watch": {"name": "手表 Color 2", "room": "随身", "tts": False},
    "phone": {"name": "手机(TTS 播报)", "room": "随身", "tts": True},
}

DEFAULT_DEVICE = "mini"
DEFAULT_VOLUME = 50

# ---------------------------------------------------------------- HA REST API


def api(path: str, payload: Optional[dict] = None) -> object:
    """GET(payload=None)或 POST 到 HA REST API"""
    if not HASS_TOKEN:
        sys.exit("错误: 找不到 HA 令牌。设置 HASS_TOKEN 环境变量,或把令牌写入 ~/.hass_token 文件"
                 "(HA 网页 个人资料 → 安全 → 长期访问令牌 创建)")
    req = urllib.request.Request(
        f"{HASS_URL}/api/{path}",
        data=json.dumps(payload).encode() if payload is not None else None,
        headers={"Authorization": f"Bearer {HASS_TOKEN}",
                 "Content-Type": "application/json"},
        method="POST" if payload is not None else "GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")[:200]
        raise RuntimeError(f"HA API {path} 失败: HTTP {e.code} {detail}") from e
    except urllib.error.URLError as e:
        raise RuntimeError(f"无法连接 HA ({HASS_URL}): {e.reason}") from e


def get_states() -> List[dict]:
    return api("states")


# ------------------------------------------------------------- entity 发现


def _matches(state: dict, keywords: List[str]) -> bool:
    eid = state["entity_id"].lower()
    name = (state.get("attributes", {}).get("friendly_name") or "").lower()
    return any(k.lower() in eid or k.lower() in name for k in keywords)


def find_entities(states: List[dict], dev_key: str) -> Dict[str, Optional[str]]:
    """为一个逻辑设备找出 TTS text 实体 / media_player / 音量 number 实体"""
    dev = DEVICES[dev_key]
    mine = [s for s in states if _matches(s, dev["match"])]

    def pick(domain: str, extra: List[str]) -> Optional[str]:
        cands = [s for s in mine if s["entity_id"].startswith(domain + ".")]
        if extra:
            pref = [s for s in cands if _matches(s, extra)]
            cands = pref or []
        return cands[0]["entity_id"] if cands else None

    return {
        # 官方 xiaomi_home:音箱的"播放文本"和电视的"消息传递(post)"都是 notify 实体
        "tts_notify": (pick("notify", ["play_text", "播放文本"])
                       or pick("notify", ["post", "消息"])
                       or pick("notify", ["execute_text_directive", "执行文本指令"])),
        # 其他集成可能用 text 实体
        "tts_text": pick("text", ["play_text", "播放文本"]),
        "media_player": pick("media_player", []),
        "volume_number": pick("number", ["volume", "音量"]),
    }


# ------------------------------------------------------------- 随身设备(HA Companion)


def find_mobile_services() -> List[str]:
    """在 notify 域找全部 mobile_app_* 服务(HA Companion 注册后出现)"""
    domains = api("services")
    notify = next((d for d in domains if d["domain"] == "notify"), None)
    if not notify:
        return []
    return sorted(s for s in notify["services"] if s.startswith("mobile_app"))


def send_mobile(key: str, text: str) -> bool:
    svcs = find_mobile_services()
    if not svcs:
        print("✗ HA 里没有 notify.mobile_app_* 服务。"
              "手机需安装 HA Companion(小米手机装 minimal 版,走 WebSocket 收通知)"
              "并登录本 HA 后重试。")
        return False
    if MOBILE_MODES[key]["tts"]:
        svcs = svcs[:1]  # TTS 命令仅 Android 支持,只发第一个,避免 iOS 收到字面"TTS"
        payload = {"message": "TTS", "data": {"tts_text": text}}
    else:
        # watch: 广播到所有已注册手机,各自镜像到自己的手表
        payload = {"message": text, "title": "Phantom",
                   "data": {"importance": "high", "priority": "high"}}
    ok = False
    for svc in svcs:
        try:
            api(f"services/notify/{svc}", payload)
            print(f"✓ 已发送 (notify.{svc} → {MOBILE_MODES[key]['name']}): {text[:50]}")
            ok = True
        except RuntimeError as e:
            print(f"⚠ notify.{svc} 发送失败: {e}")
    if ok and not MOBILE_MODES[key]["tts"]:
        # 文字通知之外再让手机朗读一遍(仅第一台 Android),连耳机时自动走耳机
        try:
            api(f"services/notify/{svcs[0]}",
                {"message": "TTS", "data": {"tts_text": text}})
            print(f"✓ 已朗读 (notify.{svcs[0]})")
        except RuntimeError as e:
            print(f"⚠ 朗读失败: {e}")
    return ok


# ------------------------------------------------------------- 消息解析(与 miloco 版一致)


def resolve_device(text: str) -> str:
    text_lower = text.lower()
    for alias, key in sorted(DEVICE_ALIASES.items(), key=lambda x: -len(x[0])):
        if alias.lower() in text_lower:
            return key
    return DEFAULT_DEVICE


def parse_volume(text: str) -> int:
    m = re.search(r"音量\s*(\d+)", text) or re.search(r"(\d+)\s*%", text)
    return max(0, min(100, int(m.group(1)))) if m else DEFAULT_VOLUME


def clean_text(text: str, key: Optional[str] = None,
               extra_aliases: Optional[List[str]] = None) -> Tuple[str, int]:
    volume = parse_volume(text)
    tts_text = text
    # 只剥除目标设备自己的别名——"手机/手表/客厅"等词出现在正文里时必须保留
    aliases = [a for a, k in DEVICE_ALIASES.items() if key is None or k == key]
    if extra_aliases:
        aliases.extend(extra_aliases)
    pre_alias = tts_text
    for alias in sorted(set(aliases), key=lambda x: -len(x)):
        a = r"\s*".join(re.escape(c) for c in alias)  # 容忍设备名内部空格("总管 mini")
        # 只在指令位置剥除设备名("对X说/让X播报/X播报 开头"),正文中的设备词保留
        tts_text = re.sub(rf"(让|对|给|到|往)\s*{a}\s*(说|读|播放|播报|朗读)?", "",
                          tts_text, flags=re.IGNORECASE)
        tts_text = re.sub(rf"^\s*{a}\s*(说|读|播放|播报|朗读)", "",
                          tts_text, flags=re.IGNORECASE)
    if tts_text == pre_alias:
        # 设备名指令没命中时才用通用句式兜底(锚定句首),避免误伤正文里的"对…说"
        tts_text = re.sub(r"^\s*让\s*[^说读播放播报朗读]{0,8}\s*(说|读|播放|播报|朗读)", "", tts_text)
        tts_text = re.sub(r"^\s*对\s*[^说]{0,8}\s*说", "", tts_text)
    tts_text = re.sub(r"^(朗读|说一声|读|说|播放|播报)", "", tts_text, flags=re.IGNORECASE)
    tts_text = re.sub(r"^(朗读|说一声|读|说|播放|播报)", "", tts_text, flags=re.IGNORECASE)
    tts_text = re.sub(r"(朗读|播放|播报|TTS)", "", tts_text, flags=re.IGNORECASE)
    tts_text = re.sub(r"^(让|对|给|到|往)\s*", "", tts_text)
    tts_text = re.sub(r"音量\s*\d+", "", tts_text)
    tts_text = re.sub(r"\d+\s*%", "", tts_text)
    tts_text = re.sub(r"\s+", " ", tts_text).strip(" ，,。.?？!！:：")
    return tts_text or "请提供要朗读的内容", volume


# ------------------------------------------------------------- 执行


def set_volume(entities: Dict[str, Optional[str]], volume: int) -> None:
    try:
        if entities["media_player"]:
            api("services/media_player/volume_set",
                {"entity_id": entities["media_player"], "volume_level": volume / 100})
        elif entities["volume_number"]:
            api("services/number/set_value",
                {"entity_id": entities["volume_number"], "value": volume})
        else:
            print("⚠ 未找到音量实体,跳过音量设置")
            return
        print(f"✓ 音量设为 {volume}%")
    except RuntimeError as e:
        print(f"⚠ 音量设置失败(继续播放): {e}")


def play_tts(entities: Dict[str, Optional[str]], text: str) -> bool:
    if entities["tts_notify"]:
        api("services/notify/send_message",
            {"entity_id": entities["tts_notify"], "message": text})
        print(f"✓ 播放成功 ({entities['tts_notify']}): {text[:50]}")
        return True
    if entities["tts_text"]:
        api("services/text/set_value",
            {"entity_id": entities["tts_text"], "value": text})
        print(f"✓ 播放成功 ({entities['tts_text']}): {text[:50]}")
        return True
    if entities["media_player"]:
        # al-one xiaomi_miot 集成的 TTS 服务(execute=False 表示朗读而非执行指令)
        api("services/xiaomi_miot/intelligent_speaker",
            {"entity_id": entities["media_player"], "text": text, "execute": False})
        print(f"✓ 播放成功 (xiaomi_miot / {entities['media_player']}): {text[:50]}")
        return True
    print("✗ 未找到可用的 TTS 实体(notify/text 播放文本 / media_player)。"
          "先跑 --list 看 HA 里发现了什么。")
    return False


def list_devices() -> None:
    states = get_states()
    print(f"HA: {HASS_URL}\n")
    for key, dev in DEVICES.items():
        ents = find_entities(states, key)
        print(f"[{key}] {dev['name']}({dev['room']})")
        for slot, eid in ents.items():
            print(f"    {slot:14} {eid or '—'}")
    # 其他疑似小米音频设备,便于扩展 DEVICES
    xiaomi_ish = [s for s in states
                  if s["entity_id"].split(".")[0] in ("media_player", "text", "notify")
                  and _matches(s, ["xiaomi", "speaker", "音箱", "电视", "wifispeaker"])]
    if xiaomi_ish:
        print("\n其他候选实体:")
        for s in xiaomi_ish:
            name = s.get("attributes", {}).get("friendly_name", "")
            print(f"    {s['entity_id']}  ({name})")
    svc = find_mobile_service()
    print(f"\n[watch/phone] notify 服务: "
          f"{'notify.' + svc if svc else '—(手机未接入 HA Companion)'}")


def main() -> None:
    parser = argparse.ArgumentParser(description="智能 TTS 播放(Home Assistant)")
    parser.add_argument("text", nargs="*", help="要朗读的内容(可包含设备名)")
    parser.add_argument("--list", action="store_true", help="列出发现的设备实体")
    parser.add_argument("--device", help="指定逻辑设备 key(mini/play/tv)或别名")
    parser.add_argument("--volume", type=int, help="音量 0-100")
    args = parser.parse_args()

    if args.list:
        list_devices()
        return
    if not args.text:
        parser.error("需要提供要朗读的内容")

    text = " ".join(args.text)
    if args.device:
        key = DEVICE_ALIASES.get(args.device, args.device)
        if key not in DEVICES and key not in MOBILE_MODES:
            sys.exit(f"未知设备: {args.device}"
                     f"(可用: {', '.join(list(DEVICES) + list(MOBILE_MODES))})")
        tts_text, volume = clean_text(text, key, [args.device])
    else:
        key = resolve_device(text)
        tts_text, volume = clean_text(text, key)
    volume = args.volume if args.volume is not None else volume

    if key in MOBILE_MODES:
        dev = MOBILE_MODES[key]
        print(f"目标设备: {dev['name']}({dev['room']})")
        print(f"发送内容: {tts_text}\n")
        if not send_mobile(key, tts_text):
            sys.exit(1)
        return

    dev = DEVICES[key]
    entities = find_entities(get_states(), key)
    print(f"目标设备: {dev['name']}({dev['room']})")
    print(f"朗读内容: {tts_text}")
    print(f"音量: {volume}%\n")

    set_volume(entities, volume)
    if not play_tts(entities, tts_text):
        sys.exit(1)


if __name__ == "__main__":
    main()
