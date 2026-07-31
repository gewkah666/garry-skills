---
name: miloco-tts
description: 智能 TTS 路由 — 通过 miloco 让小爱音箱/电视/管家朗读。自动识别"总管 mini / 总管 Play / 电视"等设备名，从自然语言指令中提取文本、音量、播放设备。覆盖场景：让 X 朗读 / 对 X 说 / X 播报 / X 音量 N + 文本。底层走 miloco CLI（device action play-text 或 post）。
version: 1.1.0
author: Hermes Agent
license: MIT
platforms: [macos, linux]
metadata:
  hermes:
    tags: [miloco, tts, 智能音箱, 小爱, 电视, 朗读, 播报]
---

# Miloco 智能 TTS 路由

## 概述

**问题：** 直接用 miloco 调 TTS 需要：
- 知道设备 DID
- 知道 action 名（音箱用 `play-text`、电视用 `post`）
- 自己拆解自然语言里的"哪个设备 / 朗读什么 / 音量多少"

**本 skill 提供一个智能入口**——输入自然语言，自动识别设备和提取内容。

## 用法

### 脚本入口

```bash
python3 scripts/miloco_tts.py "让总管 mini 朗读 测试文本"
python3 scripts/miloco_tts.py "对卧室说 晚安"
python3 scripts/miloco_tts.py "电视播报 快递到了"
python3 scripts/miloco_tts.py "对书房说 你好 音量80"
python3 scripts/miloco_tts.py "list" --list
```

### 设备别名（自动识别）

| 文本关键词 | 设备 | DID | 房间 |
|-----------|------|-----|------|
| 总管 mini / mini / 书房音箱 | 总管mini（xiaomi.wifispeaker.x4b）| 865912910 | 书房 |
| 总管 / 总管 play / 卧室音箱 | 总管Play（xiaomi.wifispeaker.lx05）| 423919135 | 卧室 |
| 电视 / 泰乐福 / 客厅电视 | 泰乐福（xiaomi.tv.mih1）| 802414229 | 客厅 |

> 匹配时**长别名优先**（"总管 mini" > "mini"，"总管 play" > "play"），单说"总管"默认指 Play。

### 文本清理规则

按以下顺序清理（长别名优先）：

1. 去掉所有设备别名
2. 去掉"让 X 说/读/播放/播报/朗读"
3. 去掉"对 X 说"
4. 去掉开头的"朗读/读/说/播放/播报/说一声"
5. 去掉中间的"朗读/播放/播报/TTS"
6. 去掉开头的"让/对/给/到/往"
7. 去掉"音量 N" 或 "N%"
8. 整理空白 + 去标点

### 音量解析

- 文本含 "音量 N" → N
- 文本含 "N%" → N
- 否则 → 默认 50%

### 设备 action 自动选择

| 设备 | 用的 action | 说明 |
|------|------------|------|
| 总管 mini / 总管 Play | `play-text` | 智能音箱 TTS |
| 电视 | `post` | message-router |

## 常见场景

### 智能家居通知
```bash
# miloco 检测到人，触发"播报到总管"
python3 scripts/miloco_tts.py "对卧室说 检测到陌生人，请查看"
```

### 闹钟/提醒
```bash
# 5 分钟后提醒
python3 scripts/miloco_tts.py "对书房说 该休息了"
```

### 配合 dev-tasks skill
每次完成 dev-tasks 任务时，TTS 播报"任务 X 已完成"。

### 配合 miloco 规则
miloco 规则触发后，可以调用本 skill 而不是直接 webhook 通知。

## Pitfalls（实测踩坑）

### TV 的 `post` 可能"假装成功但不朗读" — 2026-07-31 验证

调用 `xiaomi.tv.mih1`（泰乐福）的 `action.5.1 post`，返回 `code: 0`（成功），但电视**没有朗读声音**。它实际是 OSD 弹通知，不是 TTS。

**对策**：脚本调用 TV 之前**显式提示用户** — TV 适合"显示通知"，不是"朗读"。TV 的 `post` 只作 fallback，不要把 TV 用作主朗读通道。如果用户必须用 TV 朗读，**实测脚本输出**（不是 API 返回）才能验证：

```bash
# Bad — 检查 API 响应，根本不可靠
~/.local/bin/miloco-cli device action 802414229 post "消息" | jq .code  # = 0 但是没出声

# Good — 看电视屏幕是否真的 OSD 出弹窗
```

**首选走音箱**（总管 mini / 总管 Play），它们真的出声。

### `device control` vs `device action`（路径名）

智能音箱的 `play-text`、电视的 `post` **都是 action 不是 property**！

- ❌ `miloco-cli device control <did> play-text "..."` — 报 `'play-text' is an action, not a controllable property`
- ✅ `miloco-cli device action <did> play-text "..."` — 工作

CLI 自动推断类型 — 任何 `action.{siid}.{aiid}` 形式的 spec_name 都要用 `device action`。

### 别名解析的歧义陷阱

脚本用"长别名优先"匹配（`总管 mini` > `mini`），但用户的口语常常说 `"总管mini"`（无空格）。两边都测过：

| 输入 | 解析出的设备 | 原因 |
|------|------------|------|
| `总管 mini 朗读 测试` | 总管mini（书房） | 长别名 "总管mini" 优先匹配 |
| `总管 play 朗读 测试` | 总管Play（卧室） | 长别名 "总管play" 优先 |
| `总管 朗读 测试` | 总管Play（卧室） | 单说 "总管" 默认 Play |
| `mini 朗读 测试` | 总管mini | "mini" 唯一匹配 |
| `play 朗读 测试` | 总管Play | "play" 唯一匹配 |

如果未来加新别名（"老王音箱" / "小豆浆"），按"长别名优先"加入 `DEVICE_ALIASES` dict — **永远先匹配长串**，不要相信 `dict` 的迭代顺序。

### `parse_message` 返回元组的顺序坑（debug 时长 5 分钟）

```python
# ❌ 错：把 tts_text 当 real_name
did, real_name, tts_text = parse_message(text)
# 输出会变成 "目标设备: 这是一个测试" + "朗读内容: 50"（默认值）

# ✅ 对：第二个位置是 tts_text，第三个是 volume
did, tts_text, volume = parse_message(text)
real_name = get_device_info(did).get("name", did)  # 自己再查设备名
```

这是 Python 解构元组的经典坑，调试的特征是"朗读内容看起来像默认值"。

### iLink 微信限流伪装（详见 miloco skill pitfall 31a）

脚本默认只发飞书（feishu）；如果用户切到微信（weixin），**30 秒 cooldown 不一定能恢复**（实测 5-10 分钟）。脚本里 `send_to_hermes(message)` 返回 False 时**不要重试**，记录日志后让 watcher 去重 + 30s cooldown 兜底。详见 miloco skill `references/wechat-ilink-rate-limit.md`。

## 扩展

要支持更多设备，在 `scripts/miloco_tts.py` 的 `DEVICE_ALIASES` dict 添加：
```python
DEVICE_ALIASES = {
    "你的设备名": "did",
    ...
}
```

要支持更多设备类型，在 `play_tts()` 函数添加新的 action 映射：
```python
action = "post" if did == "电视DID" else "play-text"
```

## 依赖

- `miloco-cli` (`/Users/garry/.local/bin/miloco-cli`)
- `miloco` 后端运行中（端口 1810）
- 设备已绑定米家账号并 in_use
- 单一来源：`~/Projects/garry-skills/miloco-tts/`（双平台 symlink 到 `~/.claude/skills/` 和 `~/.hermes/skills/smart-home/`）
