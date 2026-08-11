---
name: miloco-tts
description: 智能 TTS 路由 — 通过 Home Assistant 让小爱音箱/电视朗读。自动识别"总管 mini / 总管 Play / 电视"等设备名，从自然语言指令中提取文本、音量、播放设备。覆盖场景：让 X 朗读 / 对 X 说 / X 播报 / X 音量 N + 文本。底层走 HA REST API（text.set_value 播放文本，退回 xiaomi_miot.intelligent_speaker），Windows/macOS 通用。
---

# 智能 TTS 路由（Home Assistant 版）

## 概述

**问题：** 直接让小爱音箱/电视朗读需要：
- 知道 HA 里对应的 entity_id
- 知道走哪个服务（官方集成的"播放文本" text 实体、xiaomi_miot 的 intelligent_speaker）
- 自己拆解自然语言里的"哪个设备 / 朗读什么 / 音量多少"

**本 skill 提供一个智能入口**——输入自然语言，自动识别设备、提取内容、自动发现 entity。

> 历史：本 skill 原走 miloco-cli（仅 macOS）。现已改为 Home Assistant REST API，
> 局域网内任何机器都能调用；脚本路径和调用方式保持不变。

## 配置（环境变量）

| 变量 | 说明 | 默认 |
|------|------|------|
| `HASS_URL`（或 `HA_URL`） | HA 地址 | `http://192.168.31.149:8123` |
| `HASS_TOKEN`（或 `HA_TOKEN`） | HA 长期访问令牌（**必填**） | 无 |

Token 在 HA 网页 **个人资料 → 安全 → 长期访问令牌** 创建。读取顺序：
环境变量 → Windows 用户级注册表（`HKCU\Environment`，兜底长驻会话继承不到新环境变量的情况）
→ `~/.hass_token` 文件（macOS/Linux 推荐把令牌放这个文件）。

## 用法

### 脚本入口

```bash
# Windows: python  /  macOS: python3
python scripts/miloco_tts.py "让总管 mini 朗读 测试文本"
python scripts/miloco_tts.py "对卧室说 晚安"
python scripts/miloco_tts.py "电视播报 快递到了"
python scripts/miloco_tts.py "对书房说 你好 音量80"
python scripts/miloco_tts.py --list        # 列出发现的设备实体（调试）
python scripts/miloco_tts.py --device tv --volume 30 "快递到了"
```

### 设备别名（自动识别）

| 文本关键词 | 逻辑设备 | 房间 |
|-----------|---------|------|
| 总管 mini / mini / 书房音箱 / 书房 | `mini` 总管mini（xiaomi.wifispeaker.x4b） | 书房 |
| 总管 / 总管 play / 卧室音箱 / 卧室 | `play` 总管Play（xiaomi.wifispeaker.lx05） | 卧室 |
| 电视 / 泰乐福 / 客厅电视 / 客厅 | `tv` 泰乐福（xiaomi.tv.mih1） | 客厅 |
| 手表 / 腕表 | `watch` 手表 Color 2（通知镜像，文字+震动） | 随身 |
| 手机 / 耳机 / 蓝牙耳机 | `phone` 手机 TTS 播报（蓝牙时自动走耳机/眼镜） | 随身 |

> 匹配时**长别名优先**（"总管 mini" > "mini"，"总管 play" > "play"），单说"总管"默认指 Play。
> 都没匹配到时默认 `mini`（书房）。

### 随身设备（watch / phone，走 HA Companion）

`watch` 和 `phone` 不走米家实体，而是 `notify.mobile_app_*` 服务（自动发现，取第一个）：

- `watch`：发普通通知 → 手机 → **小米运动健康通知镜像** → 手表显示文字+震动。
  Color 2 无语音通路（封闭 RTOS，不支持快应用/侧载），文显是它的上限。
- `phone`：发 `message: "TTS"` + `tts_text` → 手机本地合成并**播放语音**；手机连着蓝牙耳机/
  眼镜时音频自动路由过去。音量参数对该通道无效（走手机媒体音量）。

前置条件（一次性）：手机安装 **HA Companion minimal 版**（无谷歌服务的国产手机用
minimal，通知走与 HA 的持久 WebSocket；GitHub home-assistant/android Releases 下载
`app-minimal-release.apk`）并登录本 HA → HA 出现 `notify.mobile_app_*`；关闭该 App 的
电池优化并允许自启动；小米运动健康里为 Home Assistant 开启应用通知同步。
手机在外网时需能连通 HA（VPN/内网穿透），否则通知积压到重连后送达。

```bash
python scripts/miloco_tts.py "对手表说 构建完成"
python scripts/miloco_tts.py "让耳机播报 该站起来活动了"
```

### Entity 自动发现

脚本每次运行从 `/api/states` 按关键词（设备名拼音/中文）匹配实体，无需写死 entity_id：

| 用途 | 匹配规则（按序） |
|------|----------------|
| TTS | `notify.*` 含 `play_text`/播放文本 → 含 `post`/消息 → 含 执行文本指令（官方 xiaomi_home，走 `notify.send_message`） |
| TTS 备选 | `text.*` 含 `play_text`/播放文本（其他集成，走 `text.set_value`） |
| TTS 兜底 | `media_player.*` + `xiaomi_miot.intelligent_speaker` 服务（execute=false） |
| 音量 | `media_player.volume_set` → 含 volume/音量 的 `number.*` 实体 |

本地实测（官方 xiaomi_home 集成）发现的实体：音箱 `notify.xiaomi_cn_<did>_x4b/lx05_play_text_a_*`，
电视 `notify.xiaomi_cn_<did>_mih1_post_a_*`，音量走 `media_player.xiaomi_cn_<did>_*`。

设备改名/换集成后跑 `--list` 检查发现结果。

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

## 常见场景

### 智能家居通知
```bash
python scripts/miloco_tts.py "对卧室说 检测到陌生人，请查看"
```

### 闹钟/提醒
```bash
python scripts/miloco_tts.py "对书房说 该休息了"
```

### 配合 dev-tasks skill
每次完成 dev-tasks 任务时，TTS 播报"任务 X 已完成"。

## 扩展

要支持更多设备，在 `scripts/miloco_tts.py` 改两个 dict：

```python
DEVICES = {
    "新设备key": {"name": "显示名", "room": "房间",
                 "match": ["HA里的friendly_name关键词", "拼音entity_id关键词"]},
}
DEVICE_ALIASES = {
    "口语别名": "新设备key",
}
```

## 依赖

- Home Assistant 可达（默认 `http://192.168.31.149:8123`，跑在 Z2Ultra NAS 的 Docker 里）
- `HASS_TOKEN` 环境变量（HA 长期访问令牌）
- 小米设备已通过 **米家集成**（官方 xiaomi_home 或 al-one xiaomi_miot）接入 HA
- Python 3（仅标准库，无第三方依赖）
