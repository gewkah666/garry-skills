---
name: episode-renamer
description: >
  Inject S##E## episode markers into verbose subtitle-group filenames so 极影视 (Z-Space
  video library) can correctly identify season and episode. Preserves all existing tags
  (subgroup, resolution, codec, language). Works on patterns like [01_73], [S02E05],
  第12话, EP12, etc. Dry-run by default; reversible via --undo.
---

# Episode Marker Injector

为已有视频文件名**插入** `S##E##` 季/集标记，保留字幕组/分辨率/编码等所有元数据。

## 重要：保留原文件名

本工具**不重命名文件**，仅在合适位置插入 `[S04E01]` 标记片段，让极影视识别季/集。

## 转换示例

**原**：`[BeanSub][Tensei Shitara Slime Datta Ken S4][01_73][CHS][1080P][x264_AAC].mp4`

**新**：`[BeanSub][Tensei Shitara Slime Datta Ken S4][S04E01][01_73][CHS][1080P][x264_AAC].mp4`

或更通用的前插版：`[S04E01][BeanSub][Tensei...][01_73][CHS][1080P][x264_AAC].mp4`

## 支持的提取模式

| 文件名模式 | 提取 | 注入标记 |
|----------|------|---------|
| `[Title S4][01_73]` | 第4季第1集 | `S04E01` |
| `[Title S02][05]` | season=2, ep=5 | `S02E05` |
| `S04E07.mp4` (已是标准) | - | 跳过 |
| `第12话` / `EP12` / `E12` | ep=12 | `S01E12` |

## 用法

```bash
# Dry-run 预览
python ~/.hermes/skills/episode-renamer/scripts/episode-rename.py \
  "/Volumes/sata11-157XXXX5549/电影&电视剧/转生史莱姆/S4" --dry-run

# 真正改名（注入标记）
python ~/.hermes/skills/episode-renamer/scripts/episode-rename.py \
  "/Volumes/sata11-157XXXX5549/电影&电视剧/转生史莱姆/S4"

# 还原
python ~/.hermes/skills/episode-renamer/scripts/episode-rename.py \
  "/Volumes/sata11-157XXXX5549/电影&电视剧/转生史莱姆/S4" --undo

# 强制前插（而不是插在 S4 标识后）
python ~/.hermes/skills/episode-renamer/scripts/episode-rename.py \
  "/Volumes/.../转生史莱姆/S4" --mode prefix
```

## 插入位置策略

1. **默认 (after-S) 模式**：在文件名中已有的 `S4`/`S04` 标识**后面**插入 `[S04E01]`
2. **prefix 模式**：在文件名**开头**插入 `[S04E01]`

## 安全机制

- 默认 `--dry-run`（仅打印，不改名）
- 改名映射保存到 `<dir>/.episode-rename-map.json`
- 已含 `S##E##` 标记的文件自动跳过（除非 `--force`）
- `--undo` 严格按映射还原

## 季数推断

- 从 `[NN_MM]` 模式自动识别（如 `[01_73]` = 第4季01）
- 从父目录名（如 `S4/`）识别
- 从文件名中 `S##` 标识（如 `[Tensei S4]`）识别
- 失败则默认 `S01`