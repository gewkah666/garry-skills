---
name: ha-fallback
description: Home Assistant 智能家居备用控制链路。当 miloco-cli 无法工作（后端未运行且拉起失败、cannot connect to Miloco backend、小米账号未绑定 is_bound=false、米家云超时）时，作为 fallback 通过 ~/Projects/ha_api.py 查询与控制设备（灯开关/亮度、实体状态）。主链路仍是 miloco-devices，仅在降级场景使用本技能。
metadata:
  author: garry
  version: "1.0"
  date: "2026-09-01"
---

# ha-fallback

米家设备的 Home Assistant 备用通道。HA（`http://192.168.31.149:8123`）经 yeelink/gtop 等局域网集成镜像同一批设备，米家云链路故障时用它兜底。

## 何时激活（触发条件）

**只在 miloco 主链路失败时降级使用**，判定信号（任一命中即切换）：

| miloco-cli 症状 | 处理 |
| --- | --- |
| `cannot connect to Miloco backend` 且 `miloco-cli service start` 拉起失败 | → 本技能 |
| `account status` 返回 `is_bound: false` 且御主暂不便重新授权 | → 本技能 |
| CLI 超时重试一次仍失败、`device list` 返回 0 台但御主确认家中有设备 | → 本技能 |
| 正常场景 | ❌ 不用本技能，走 miloco-devices（spec 语义全、支持场景/action/非灯设备） |

> 两链路控制的是**同一批物理设备**，状态互通：HA 侧开的灯，miloco `props` 查到的也是开。

## 工具

`python3 ~/Projects/ha_api.py <command> [args]`（token 已内置于脚本，勿在对话中回显）

| 命令 | 用途 |
| --- | --- |
| `lights` | 列出已映射的灯（中文名 → entity_id + 当前状态） |
| `light-on <中文名> [brightness]` | 开灯，可选亮度 1-100 |
| `light-off <中文名>` | 关灯 |
| `state <entity_id>` | 查单实体完整状态（含 attributes：亮度/色温） |
| `on / off / toggle <entity_id>` | 按 entity_id 开关（未映射设备用这个） |
| `states` | 全实体按 domain 分组概览（找未知 entity_id 时用） |

## 工作流

1. **灯类设备**：`lights` 查中文名映射 → `light-on/light-off` 直接控制。
2. **非灯设备**（未在映射表）：`states` 或 `get_states` 里 grep `friendly_name` 定位 entity_id → `on/off/state`。
3. **查询状态**：`state <entity_id>`，读 `state` + `attributes.brightness/color_temp`。
4. 控制后向御主回复时**注明走了 HA 备用链路**（如"书房灯已开（注：米家后端故障，本次走 HA 备用通道）"），并提示主链路待修。

## 已知 entity 映射（2026-09 快照，以 `lights` 实时输出为准）

| 设备 | 房间 | entity_id |
| --- | --- | --- |
| 少商剑 | 客厅 | `light.yeelink_cn_573493434_ceil40_s_2_light` |
| 关冲剑 | 书房 | `light.yeelink_cn_821456659_ceil39_s_2_light` |
| 商阳剑 | 卧室 | `light.yeelink_cn_822387566_ceil39_s_2_light` |
| 中冲剑 | 次卧 | `light.yeelink_cn_821027308_ceil39_s_2_light`（常 offline→unavailable） |
| 少冲剑 | 阳台 | `light.gtop_cn_697073856_yl03_s_2_light` |

> did 与 miloco 设备列表一致，可互相对账。设备离线时 HA 侧显示 `unavailable`。

## 边界与安全

- ❌ 不用于触发米家场景 / 音箱播报 / 空调精细控制（spec 枚举在 HA 侧不完整，这些需求应修 miloco 链路后做）。
- ⚠️ 门锁/摄像头/燃气阀/烟雾报警器等安全设备的控制**同样遵循 miloco-devices 的二次确认规则**。
- ✅ 只读查询（`state`/`states`/`lights`）无风险，可直接执行。
- HA 服务器本身不可达（curl 8123 超时/拒绝）→ 两链路全断，如实报御主"家中控制链路全挂"，勿重试刷屏。
