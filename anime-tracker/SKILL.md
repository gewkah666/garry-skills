---
name: anime-tracker
description: >
  Automated anime tracking system that combines Bangumi metadata with DMHY magnet search,
  driven by a curated watchlist. Bangumi resolves completion status (subject_id overrides
  keyword search); DMHY finds the latest magnets; NAS qBittorrent WebAPI is the default
  download engine (local aria2 only via --fallback-aria2). Use when the user wants to
  track ongoing anime series, fetch new episode magnets, or fix downloaded episodes
  (missing subtitles, naming, duplicates).
---

# Anime Tracker

自动追剧流水线，整合 **Bangumi（状态判定）+ DMHY（磁力搜索）+ aria2（下载）**。

## 数据流

```
~/.config/anime-tracker/watchlist.yaml  (追剧清单)
   ↓
Bangumi API → subject_id → 连载中/完结判定
   ↓ (only if ongoing)
DMHY RSS → 关键词匹配最新磁力
   ↓
NAS qBittorrent WebAPI → /downloads/<剧名>/  (= NAS /sata11/my/data/qb/Downloads)
   ↓
极空间 NAS → 极影视自动扫描入库
```

下载默认走 **NAS qBittorrent**（Bearer key 认证，`QBT_URL`/`QBT_API_KEY` 存
`~/.hermes/.env`）。本机 aria2 仅是 `--fallback-aria2` 备用通道——它会直写
rclone 挂载目录，曾产生 0 字节占位假文件，勿作默认。

## 配置：追剧清单

`~/.config/anime-tracker/watchlist.yaml`

```yaml
- name_cn: 葬送的芙莉莲
  bangumi_id: 305429         # 可选:直接指定 Bangumi subject_id
  subdir: 葬送的芙莉莲       # 可选:覆盖默认目录名

- name_cn: 关于我转生变成史莱姆这档事 第四季
  bangumi_id: 515594        # 第4期(年番切 4 季度播放)
  subdir: 转生史莱姆S4

- name_cn: 进击的巨人
  # 不指定 bangumi_id → 用关键词搜 (eps==total 时跳过)
```

## 脚本

| 脚本 | 用途 |
|------|------|
| `scripts/anime-tracker.py` | 主入口: 读 watchlist → Bangumi → DMHY → qb（`--fallback-aria2` 备用） |
| `scripts/setup-watchlist.py` | 交互式生成 watchlist.yaml |

## 使用

```bash
# 单次运行 (dry-run)
python ~/.hermes/skills/anime-tracker/scripts/anime-tracker.py --dry-run

# 真正下载
python ~/.hermes/skills/anime-tracker/scripts/anime-tracker.py

# 自定义 watchlist 路径
python ~/.hermes/skills/anime-tracker/scripts/anime-tracker.py --watchlist ~/my-watchlist.yaml
```

## 输出目录

默认（qb）: `/downloads/<剧名>/` → NAS 实际路径 `/sata11/my/data/qb/Downloads/<剧名>/`，极影视已覆盖扫描。
备用（--fallback-aria2）: rclone 挂载 `~/临时/zspace/.../电影&电视剧/Anime/<剧名>/`（不推荐）。

## Cron 调度

每日凌晨 02:30 自动跑（由 Hermes cron job `anime-track-and-fetch` 触发）。

## 下载完成推送（anime_download_notify，2026-09-14 上线）

`scripts/anime_download_notify.py` + cron job `anime-download-notify`（*/30 分，no_agent）：扫 qb torrents/info，watchlist 目录（无职转生/转生史莱姆/芙莉莲）里首次 100% 的任务 → Bark 推「📥 新番下载完成」。去重状态 `~/.cache/anime-tracker/download_notify_state.json`。

> 曾同时上线「极影视观看记录 → Notion 建档 + 推送」（anime_watch_sync），御主 2026-09-14 当日撤销：不监控看了什么。逆向到的端点（`/zvideo/video/v2/playlist` 等）仍存于 zspace-nas skill 的 references/zvideo-api.md，御主日后再开口才可复用。教训一并记：极影视 API 不返回观看时间戳，任何自动记账禁止编造时刻——数据能承载多少信息就写多少。

### Bark 直推格式（脚本内 bark_push，已实测）
`POST {BARK_SERVER_URL}/push`，**JSON body**（form 编码会 400），字段单数 `device_key`（非 device_keys）；server 在 ~/.hermes/.env，level=active 带声。

## 与其他 skill 的关系

- **bangumi-resolve**：被本 skill 复用（搜索/判定）
- **dmhy-search**：被本 skill 复用（RSS 抓取/磁力提取）
- **download-anything**：被本 skill 复用（aria2 RPC 调用）

## 坑点
- 旧版流水线曾用 Mac 本机 aria2 直写 NAS 挂载目录（Anime/<剧名>/），中断后留下
  「文件名齐全、内容全 0 字节」的假文件（伴 .aria2 控制文件），极影视会把它和
  qb 完整版各识别一条，造成每集两份、一份播不了。2026-09 已全量迁 qb，旧目录已清。
  再见到 0 字节+同名完整文件成对出现 → 删 0 字节那份。
- 绝不要经 Mac rclone 挂载往 NAS 复制视频：会附带 AppleDouble `._xxx` 垃圾文件。
  NAS 侧文件操作（list/move/remove）直接走 zspace-mcp 的 /v2/file/* API。
- 写脚本文件时勿用 `QB_KEY="$(grep…)"` / `*_TOKEN=*** 形态赋值：工具链脱敏层会把
  命令替换损坏成字面 `***`。改用 QB_BEARER 之类避开 KEY/TOKEN 字样的变量名。
- qb v5 `torrents/add` 返回 JSON（added_torrent_ids/failure_count），非旧版 `ok`。
- qb v5 `torrents/renameFile` 参数是驼峰 `oldPath`/`newPath`（snake_case 报 400）。
  任务未下完即可用它给包内文件预先注入 S##E## 标记，比下载完再在文件系统改名省事。
- 探测未知磁力内容：暂停提交到临时目录（如 `/downloads/_probe`），读
  `/api/v2/torrents/files` 文件清单核验，完事 delete——不必真下载。
- 查 MKV 内封字幕轨：经 zspace `/v2/file/download` 带 Range 取文件头 ~1MB，
  在字节里扫 Language 元素（hex `22B59C`）提取 jpn/chi 等；别手写完整 EBML 树
  解析——极易误解析出 0 条轨道。PGS（`S_HDMV/PGS`）是图形字幕，多数播放器渲染差。

## 缺中文字幕的修复：先字幕，后换源，先请示再大下载

BDRip 源（DBD-Raws 等原盘压制）常只内封日方 PGS 字幕。发现缺中字时的行动顺序：
1. 先找独立外挂字幕：字幕组 GitHub org 仓库（如 Kitauji-Sub/Subtitles 按
   `TV/<年>/<季>/<作品>/` 组织）、acgrip 论坛帖。注意多数组已不发独立 .ass
   （README 下载链接为空占位符），且 WebRip 字幕与 BDRip 帧率/时间轴常不兼容。
2. 字幕路线走不通才考虑换视频源（内封简繁的 WebRip 整季 Fin 合集包，爱恋&漫猫等
   组有）。两条路线画质/流量各有代价，属真正的利弊权衡——**报告御主选定后，
   再提交 >5GB 的下载**；勿自行开下（御主纠正过：「不是下字幕就好了么」）。

## 报障「重复 / 下载不完整」时的诊断顺序（勿直接重下）

1. **先校验种子完整性**:qb `POST /api/v2/torrents/recheck`(form: hashes=...)，轮询
   `/api/v2/torrents/info` 直到无 checkingUP 态再看 amount_left=0。progress=1.00 单独
   不足为信——那是上次校验的陈旧结果，被质疑时必须 recheck 复验。
2. **集数缺口 ≠ 漏下**:把 Bangumi/源站登记的集数与 DMHY RSS(fetch_rss(force=True))
   各源最新实发集对照——周更在播番「缺」的后几集多半还没播出，先看源里最大集号再下结论。
3. **「重复」主因在库端不在文件系统**:极影视会把包内非正片(NC.Ver/PV/menu/OP/ED/特典)
   和 .ass 外挂字幕刮进剧集列表，且同一剧常被拆成多个合集(每季一个 + 一个 extend_type=7
   的无季号「父合集」)，片库看似每集多份。修法＝把非正片移出扫描根(见 episode-renamer，
   `_Extras/` 之类也要挪出极影视源目录)→ `/zvideo/classification/rescan` 重扫 →
   仍残留的父合集让御主在极影视 UI 手动删。
4. **判定 MKV 截断**:zspace `/v2/file/download?path=` 带 `Range: bytes=0-63`(返回 206)，
   解析 Segment 元素(ID hex `18538067`)声明长度与实际文件大小比对；
   declared+头部开销 ≈ 实际大小即完整，实际远小于 declared 才是截断。

## 已知限制

- DMHY RSS 仅返回最近 100 条，极冷门新番可能漏抓
- Bangumi 季级 subject 录入滞后 1-3 个月（2026 年新季度可能未收录）
- Bangumi `eps` 字段对年番切季度播放的作品（如转生史莱姆S4）数据不准确，
  推荐手动指定 bangumi_id 而非依赖关键词搜索