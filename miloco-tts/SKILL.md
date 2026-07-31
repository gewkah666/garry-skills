---
name: miloco-tts
description: 智能 TTS 路由 — 通过 miloco 让小爱音箱/电视/管家朗读。自动识别"总管 mini / 总管 Play / 电视"等设备名，从自然语言指令中提取文本、音量、播放设备。覆盖场景：让 X 朗读 / 对 X 说 / X 播报 / X 音量 N + 文本。底层走 miloco CLI（device action play-text 或 post）。
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
